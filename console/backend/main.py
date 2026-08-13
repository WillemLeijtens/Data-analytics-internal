"""Retailer Console API (FastAPI). Start: uvicorn main:app --reload --port 8000"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from engine import analytics, contracts, importer, signals
from engine import parser as parser_mod
from engine.profile import (Profile, active_profile, capabilities, get_profiles,
                            missing_required, save_profile)

app = FastAPI(title="Retailer Console")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
db.init_db()

# A fresh install must not boot without parser profiles — bootstrap loads the
# profiles/settings/contracts (no sales facts). Idempotent, so it is a no-op
# on every start after the first. Demo sales data: `make seed`.
with db.get_conn() as _conn:
    _needs_bootstrap = not _conn.execute(
        "SELECT 1 FROM parser_profiles LIMIT 1").fetchone()
if _needs_bootstrap:
    import seed as _seed
    _seed.bootstrap()


def _retailer_or_404(conn, retailer_id: str):
    row = conn.execute("SELECT * FROM retailers WHERE id=?", (retailer_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"onbekende retailer {retailer_id!r}")
    return row


# ---------------------------------------------------------------- overview

@app.get("/api/overview")
def overview():
    with db.get_conn() as conn:
        return signals.overview(conn)


# ---------------------------------------------------------------- analyses

@app.get("/api/{retailer_id}/dashboard")
def dashboard(retailer_id: str, merk: str | None = None, land: str | None = None,
              banner: str | None = None):
    split = lambda v: v.split(",") if v else None  # noqa: E731
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return analytics.dashboard(conn, retailer_id, split(merk), split(land), split(banner))


@app.get("/api/{retailer_id}/artikelen")
def artikelen(retailer_id: str):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return analytics.articles(conn, retailer_id)


@app.get("/api/{retailer_id}/promoties")
def promoties(retailer_id: str):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return analytics.promotions(conn, retailer_id)


class PromoConfirmations(BaseModel):
    bevestigd: list[dict]  # [{merk, land, banner, periode}]


@app.put("/api/{retailer_id}/promoties")
def save_promoties(retailer_id: str, body: PromoConfirmations):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        conn.execute("DELETE FROM promo_confirmations WHERE retailer_id=?", (retailer_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO promo_confirmations (retailer_id, merk, land, banner, periode) "
            "VALUES (?,?,?,?,?)",
            [(retailer_id, c["merk"], c["land"], c.get("banner"), c["periode"])
             for c in body.bevestigd])
        return {"ok": True, "aantal": len(body.bevestigd)}


@app.get("/api/{retailer_id}/assortiment")
def assortiment(retailer_id: str):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return analytics.assortment(conn, retailer_id)


# ---------------------------------------------------------------- import

@app.post("/api/import")
async def do_import(files: list[UploadFile]):
    results = []
    with db.get_conn() as conn:
        for f in files:
            content = await f.read()
            try:
                results.append(importer.run_import(conn, f.filename, content))
            except Exception as e:  # noqa: BLE001 - one bad file must not kill the batch
                conn.rollback()
                results.append({"filename": f.filename, "status": "error", "detail": str(e)})
    return {"results": results}


@app.get("/api/imports")
def list_imports(retailer_id: str | None = None, limit: int = 50):
    with db.get_conn() as conn:
        sql = ("SELECT im.*, p.version AS profiel_versie FROM imports im "
               "LEFT JOIN parser_profiles p ON p.id = im.profile_id ")
        params: tuple = ()
        if retailer_id:
            sql += "WHERE im.retailer_id = ? "
            params = (retailer_id,)
        sql += "ORDER BY im.created_at DESC, im.id DESC LIMIT ?"
        rows = conn.execute(sql, (*params, limit)).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/import-status")
def import_status(retailer_id: str | None = None):
    """Feed freshness per retailer: per merk (feed) the newest period."""
    with db.get_conn() as conn:
        retailers = conn.execute("SELECT * FROM retailers ORDER BY rowid").fetchall()
        out = []
        for r in retailers:
            if retailer_id and r["id"] != retailer_id:
                continue
            prof = active_profile(conn, r["id"])
            rows = conn.execute(
                "SELECT f.merk, f.land, f.banner, f.winkel_id, f.periode, MAX(im.created_at) AS ts, "
                "SUM(1) AS rijen FROM sellout_facts f JOIN imports im ON im.id=f.import_id "
                "AND im.status IN ('ingelezen','test') WHERE f.retailer_id=? "
                "GROUP BY f.merk", (r["id"],)).fetchall()
            caps = capabilities(prof.definition) if prof else None
            feeds = []
            for row in rows:
                scope = "per winkel" if caps and caps["winkel"] and not caps["banner"] else \
                    "/".join(x for x in (row["land"], row["banner"]) if x) or "—"
                feeds.append({"feed": row["merk"] or "—", "scope": scope,
                              "periode": row["periode"], "ts": row["ts"], "rijen": row["rijen"]})
            out.append({"retailer": r["id"], "naam": r["naam"],
                        "profiel": {"versie": prof.version, "status": prof.status} if prof else None,
                        "periode_type": caps["periode"] if caps else None,
                        "feeds": feeds,
                        "signaal": signals.data_signal(conn, r["id"])[0]})
        return out


# ---------------------------------------------------------------- parser

@app.get("/api/parser/profielen")
def list_profiles():
    with db.get_conn() as conn:
        out = []
        for p in get_profiles(conn):
            out.append({"id": p.id, "retailer_id": p.retailer_id, "version": p.version,
                        "status": p.status, "definition": p.definition,
                        "capabilities": capabilities(p.definition),
                        "ontbreekt": sorted(missing_required(p.definition))})
        return out


class ProfileBody(BaseModel):
    definition: dict
    status: str = "concept"   # concept | test | live


@app.post("/api/parser/{retailer_id}/profielen")
def publish_profile(retailer_id: str, body: ProfileBody):
    if body.status not in ("concept", "test", "live"):
        raise HTTPException(422, "status moet concept|test|live zijn")
    if body.status == "live" and missing_required(body.definition):
        raise HTTPException(422, "profiel mist verplichte velden: "
                            + ", ".join(sorted(missing_required(body.definition))))
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        p = save_profile(conn, retailer_id, body.definition, body.status)
        if body.status == "live":
            conn.execute("UPDATE retailers SET aangesloten=1 WHERE id=?", (retailer_id,))
        return {"id": p.id, "version": p.version, "status": p.status}


@app.post("/api/parser/{retailer_id}/test")
async def test_profile(retailer_id: str, file: UploadFile):
    """'Testen op bestand': parse with the newest profile, store nothing."""
    with db.get_conn() as conn:
        profs = get_profiles(conn, retailer_id)
        if not profs:
            raise HTTPException(404, "geen profiel")
        content = await file.read()
        try:
            result = parser_mod.parse_file(file.filename, content, profs[0])
            return {"ok": True, "rijen": len(result["facts"]),
                    "periodes": result["periodes"],
                    "voorbeeld": result["facts"][:5]}
        except parser_mod.ParseError as e:
            return {"ok": False, "fout": str(e), "rijen_fouten": e.row_errors[:20]}


# ---------------------------------------------------------------- settings

@app.get("/api/{retailer_id}/instellingen")
def get_settings(retailer_id: str):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        prof = active_profile(conn, retailer_id)
        caps = capabilities(prof.definition) if prof else None
        return {
            "capabilities": caps,
            "winkels_targets": [dict(r) for r in conn.execute(
                "SELECT * FROM retailer_settings WHERE retailer_id=? ORDER BY merk, land, banner",
                (retailer_id,))],
            "rotatie_targets": [dict(r) for r in conn.execute(
                "SELECT * FROM rotatie_targets WHERE retailer_id=? ORDER BY merk", (retailer_id,))],
            "mail_rules": [dict(r) for r in conn.execute(
                "SELECT * FROM mail_rules WHERE retailer_id=? ORDER BY id", (retailer_id,))],
            "sharepoint": (lambda r: dict(r) if r else None)(conn.execute(
                "SELECT * FROM sharepoint_links WHERE retailer_id=?", (retailer_id,)).fetchone()),
            "documenten": [dict(r) for r in conn.execute(
                "SELECT * FROM contract_documents WHERE retailer_id=? ORDER BY naam", (retailer_id,))],
        }


class SettingsBody(BaseModel):
    winkels_targets: list[dict] | None = None   # [{merk, land, banner, aantal_winkels, target_per_winkel}]
    rotatie_targets: list[dict] | None = None   # [{merk, stuks_per_winkel_per_week}]
    mail_rules: list[dict] | None = None        # [{naam, afzender, bijlage_glob, actief}]


@app.put("/api/{retailer_id}/instellingen")
def save_settings(retailer_id: str, body: SettingsBody):
    """'Alles opslaan' — atomic: one transaction for the whole payload."""
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        if body.winkels_targets is not None:
            conn.execute("DELETE FROM retailer_settings WHERE retailer_id=?", (retailer_id,))
            conn.executemany(
                "INSERT INTO retailer_settings (retailer_id, merk, land, banner, aantal_winkels, "
                "target_per_winkel) VALUES (?,?,?,?,?,?)",
                [(retailer_id, s["merk"], s["land"], s.get("banner"),
                  s.get("aantal_winkels"), s.get("target_per_winkel"))
                 for s in body.winkels_targets])
        if body.rotatie_targets is not None:
            conn.execute("DELETE FROM rotatie_targets WHERE retailer_id=?", (retailer_id,))
            conn.executemany(
                "INSERT INTO rotatie_targets (retailer_id, merk, stuks_per_winkel_per_week) "
                "VALUES (?,?,?)",
                [(retailer_id, t["merk"], t["stuks_per_winkel_per_week"])
                 for t in body.rotatie_targets])
        if body.mail_rules is not None:
            conn.execute("DELETE FROM mail_rules WHERE retailer_id=?", (retailer_id,))
            conn.executemany(
                "INSERT INTO mail_rules (retailer_id, naam, afzender, bijlage_glob, actief, laatste_run) "
                "VALUES (?,?,?,?,?,?)",
                [(retailer_id, m["naam"], m.get("afzender"), m.get("bijlage_glob"),
                  1 if m.get("actief", True) else 0, m.get("laatste_run"))
                 for m in body.mail_rules])
        return {"ok": True}


class SharepointBody(BaseModel):
    map_url: str


@app.post("/api/{retailer_id}/sharepoint")
def link_sharepoint(retailer_id: str, body: SharepointBody):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        conn.execute(
            "INSERT INTO sharepoint_links (retailer_id, map_url) VALUES (?,?) "
            "ON CONFLICT(retailer_id) DO UPDATE SET map_url=excluded.map_url",
            (retailer_id, body.map_url))
        docs = contracts.sync_documents(conn, retailer_id)
        return {"ok": True, "documenten": docs}


# ---------------------------------------------------------------- frontend
# In the container the built SPA sits in backend/static; in local dev it is
# absent and Vite serves the frontend on :5173 instead.

STATIC = Path(__file__).resolve().parent / "static"
if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Client-side routing: every non-API path renders the SPA."""
        candidate = STATIC / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC / "index.html")
