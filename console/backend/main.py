"""Retailer Console API (FastAPI). Start: uvicorn main:app --reload --port 8000"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import logging
import os
import re
import secrets
import sys
import zipfile
from ipaddress import ip_address
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from engine import (analytics, contracts, datagaten, importer, projecten,
                    signals, winkelhistorie)
from engine import parser as parser_mod
from engine.periods import sort_key
from engine.profile import active_profile, capabilities, get_profiles

# Eén regel per bericht, met tijdstip en niveau — bruikbaar voor
# logaggregatie (bv. `docker logs` doorheen journald/Loki), i.p.v. kale
# print()-regels zonder niveau of tijdstip. Uvicorn's eigen access-log
# blijft apart lopen; dit is alleen voor de eigen berichten van de app.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [console] %(message)s")
logger = logging.getLogger("console")

app = FastAPI(title="Retailer Console")

# ---------------------------------------------------------------- access
# ONE switch decides how the console is protected, so the settings can never
# contradict each other (an earlier version let a stray CONSOLE_PASSWORD in
# .env silently re-enable basic auth behind the portal, producing a browser
# prompt for a password nobody has):
#
#   CONSOLE_AUTH=gateway  (default) — no auth in the app; the portal's
#       forward-auth is the gatekeeper. Only allowed on a private bind.
#   CONSOLE_AUTH=password           — HTTP basic auth in the app; needs
#       CONSOLE_PASSWORD and a gateway that injects the Authorization header.
#
# CONSOLE_PASSWORD alone no longer switches modes: it is only *used* in
# password mode, and ignored (with a warning) in gateway mode.
CONSOLE_PASSWORD = os.environ.get("CONSOLE_PASSWORD", "")
CONSOLE_USER = os.environ.get("CONSOLE_USER", "console")
CONSOLE_BIND = os.environ.get("CONSOLE_BIND", "127.0.0.1")

try:
    MAX_UPLOAD_MB = int(os.environ.get("CONSOLE_MAX_UPLOAD_MB", "200"))
except ValueError as e:
    raise RuntimeError("CONSOLE_MAX_UPLOAD_MB moet een geheel getal zijn") from e
if MAX_UPLOAD_MB <= 0:
    raise RuntimeError("CONSOLE_MAX_UPLOAD_MB moet groter dan nul zijn")
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def _is_private_bind(value: str) -> bool:
    """Gateway-modus mag alleen op loopback/privé/link-local binden. Een
    lijst met wildcards afwijzen is niet genoeg: een publiek IP invullen
    zou de console net zo goed onbeschermd publiceren."""
    try:
        address = ip_address(value.strip().strip("[]").split("%", 1)[0])
    except ValueError:
        return value.strip().lower() == "localhost"
    return (address.is_loopback or address.is_private or address.is_link_local) \
        and not address.is_unspecified

CONSOLE_AUTH = os.environ.get("CONSOLE_AUTH", "").strip().lower()
if not CONSOLE_AUTH:
    # Legacy switches, kept working: CONSOLE_ALLOW_OPEN=1 states "the gateway
    # authenticates", so it wins over a leftover password.
    if os.environ.get("CONSOLE_ALLOW_OPEN") == "1":
        CONSOLE_AUTH = "gateway"
    elif CONSOLE_PASSWORD:
        CONSOLE_AUTH = "password"
    else:
        raise RuntimeError(
            "Geen toegangsmodus gekozen. Zet CONSOLE_AUTH=gateway (het "
            "portaal doet de authenticatie; alleen bij een prive binding) of "
            "CONSOLE_AUTH=password samen met CONSOLE_PASSWORD."
        )
if CONSOLE_AUTH not in ("gateway", "password"):
    raise RuntimeError(
        f"CONSOLE_AUTH={CONSOLE_AUTH!r} is ongeldig; kies 'gateway' of 'password'."
    )
if CONSOLE_AUTH == "password" and not CONSOLE_PASSWORD:
    raise RuntimeError("CONSOLE_AUTH=password vereist een gevulde CONSOLE_PASSWORD.")
if CONSOLE_AUTH == "gateway" and not _is_private_bind(CONSOLE_BIND):
    raise RuntimeError(
        f"CONSOLE_AUTH=gateway samen met CONSOLE_BIND={CONSOLE_BIND!r} zou de "
        "console zonder toegangscontrole publiek kunnen publiceren. "
        "Bind op 127.0.0.1 of het prive-adres, of kies CONSOLE_AUTH=password."
    )

# Kept in one place so the auth exemption and the routes can never drift.
HEALTH_PATHS = {"/healthz", "/healthz/"}

if CONSOLE_AUTH == "password":
    @app.middleware("http")
    async def require_password(request, call_next):
        from starlette.responses import Response

        # The health probe stays open: uptime monitoring must not need
        # credentials, and the route exposes no data. Both spellings are
        # exempt — a monitor appending a slash must not read as "down".
        if request.url.path in HEALTH_PATHS:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                # compare_digest on both halves: no early-exit timing leak.
                ok = (secrets.compare_digest(user, CONSOLE_USER)
                      and secrets.compare_digest(pw, CONSOLE_PASSWORD))
            except Exception:  # noqa: BLE001 - malformed header is just a failed login
                ok = False
        if not ok:
            return Response(status_code=401, content="Inloggen vereist",
                            headers={"WWW-Authenticate": 'Basic realm="Retailer Console"'})
        return await call_next(request)
else:
    # Gateway mode: no auth layer at all, so a successful portal login is
    # enough. Never any WWW-Authenticate response from this app.
    logger.info("CONSOLE_AUTH=gateway — geen eigen inlog; het portaal "
               "authenticeert. Gebonden op %s.", CONSOLE_BIND)
    if CONSOLE_PASSWORD:
        logger.warning("CONSOLE_PASSWORD is gezet maar wordt genegeerd in "
                       "gateway-modus. Haal hem uit .env, of kies "
                       "CONSOLE_AUTH=password als je die laag wél wilt.")

# No CORS middleware on purpose: the SPA is served by this same app (and the
# Vite dev server proxies /api), so every request is same-origin. A wildcard
# CORS header would only widen the surface behind the gateway for nothing.
db.init_db()

# Bootstrap draait bij ELKE start, niet alleen bij een lege database: hij is
# idempotent (INSERT OR IGNORE per retailer/versie), en alleen zo komt een
# NIEUW meegeleverd parser-profiel (zoals Etos) ook aan op een bestaande
# installatie — de oude alleen-bij-lege-tabel-check hield dat tegen.
import seed as _seed  # noqa: E402
_seed.bootstrap()


def _contract_doc(row) -> dict:
    """condities staat als JSON-tekst in de database; de frontend krijgt
    een echte lijst."""
    d = dict(row)
    d["condities"] = json.loads(d["condities"]) if d.get("condities") else []
    return d


def _retailer_or_404(conn, retailer_id: str):
    row = conn.execute("SELECT * FROM retailers WHERE id=?", (retailer_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"onbekende retailer {retailer_id!r}")
    return row


# ---------------------------------------------------------------- overview

@app.get("/api/overview")
def overview():
    with db.get_conn() as conn:
        return _gecachet(("overview",), lambda: signals.overview(conn), conn)


# ---------------------------------------------------------------- analyses

# De analyses lezen álle feiten van een retailer in geheugen en lopen daar
# een stuk of tien keer overheen. Gemeten: ~28 ms per 1000 feitregels, dus
# 104k regels kost bijna drie seconden — en elke schermwissel rekent alles
# opnieuw. Deze cache haalt de herhaalkosten weg zonder aan de rekenlogica
# te komen.
#
# Invalidatie is bewust op de DATA gebaseerd, niet op een teller die dit
# proces zelf bijhoudt: seed.py, cleanup_demo.py, cleanup_duplicates.py en
# tools/ schrijven buiten dit proces om. Een teller zou die missen en
# stilzwijgend verouderde cijfers blijven tonen — precies het soort stille
# fout dat deze app juist probeert te vermijden.
#
# Ook NIET op de bestandstijd van de database: in WAL-modus raakt élke
# lezende verbinding het -wal-bestand, waardoor de stempel bij elk verzoek
# verandert en de cache nooit raakt (gemeten: 0% winst).
#
# Wel: een telling per tabel. COUNT(*) én MAX(rowid), want alleen MAX mist
# een verwijdering (cleanup_duplicates) en alleen COUNT mist een even groot
# verwijder-en-invoegen (de herlevering van feiten).
#
# De tabellen worden UIT DE DATABASE gehaald, niet uit een lijst hier. Een
# handmatige lijst was de eerste opzet en die miste meteen
# contract_documents, waardoor een geüpload contract het Overzicht niet
# ververste. Een tabel vergeten mag geen stille fout kunnen zijn.
#
# De datum hoort er ook bij: `is_afgesloten()` bepaalt of de laatste periode
# nog loopt, en dat verandert met de klok en niet met de data. Zonder de
# datum zou een dashboard van gisteren vandaag nog "week loopt nog" melden.
_ANALYSE_CACHE: dict = {}
_CACHE_MAX = 64


def _data_versie(conn) -> tuple:
    from engine.periods import _vandaag_nl

    tabellen = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    vraag = " UNION ALL ".join(
        f"SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM {t}" for t in tabellen)
    tellingen = tuple(tuple(r) for r in conn.execute(vraag)) if tabellen else ()
    return (_vandaag_nl().isoformat(), tellingen)


def _gecachet(sleutel: tuple, bereken, conn):
    versie = _data_versie(conn)
    gevonden = _ANALYSE_CACHE.get(sleutel)
    if gevonden is not None and gevonden[0] == versie:
        return gevonden[1]
    uitkomst = bereken()
    if len(_ANALYSE_CACHE) >= _CACHE_MAX:
        _ANALYSE_CACHE.clear()          # klein en zeldzaam: geen LRU nodig
    _ANALYSE_CACHE[sleutel] = (versie, uitkomst)
    return uitkomst


@app.get("/api/{retailer_id}/dashboard")
def dashboard(retailer_id: str, merk: str | None = None, land: str | None = None,
              banner: str | None = None):
    split = lambda v: v.split(",") if v else None  # noqa: E731
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return _gecachet(
            ("dashboard", retailer_id, merk, land, banner),
            lambda: analytics.dashboard(conn, retailer_id,
                                        split(merk), split(land), split(banner)), conn)


@app.get("/api/{retailer_id}/artikelen")
def artikelen(retailer_id: str, merk: str | None = None):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return _gecachet(
            ("artikelen", retailer_id, merk),
            lambda: analytics.articles(conn, retailer_id,
                                       merk.split(",") if merk else None), conn)


@app.get("/api/{retailer_id}/promoties")
def promoties(retailer_id: str):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return _gecachet(("promoties", retailer_id),
                         lambda: analytics.promotions(conn, retailer_id), conn)


class PromoConfirmations(BaseModel):
    bevestigd: list[dict]  # [{merk, land, banner, periode}]


@app.put("/api/{retailer_id}/promoties")
def save_promoties(retailer_id: str, body: PromoConfirmations):
    try:
        rows = [(retailer_id, c["merk"], c["land"], c.get("banner"), c["periode"])
                for c in body.bevestigd]
    except (KeyError, TypeError) as e:
        raise HTTPException(422, f"onvolledige bevestiging: {e}")
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        # Een bevestiging voor een periode die niet in de feiten voorkomt zou
        # onzichtbaar opgeslagen worden — en later, zodra die periode alsnog
        # geladen wordt, ineens als actie meetellen. Weigeren dus.
        bestaand = {r["periode"] for r in conn.execute(
            "SELECT DISTINCT periode FROM sellout_facts WHERE retailer_id=?",
            (retailer_id,))}
        spook = sorted({p for (_, _, _, _, p) in rows} - bestaand)
        if spook:
            raise HTTPException(
                422, f"periode(s) niet in de data van deze retailer: {', '.join(spook)}")
        conn.execute("DELETE FROM promo_confirmations WHERE retailer_id=?", (retailer_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO promo_confirmations (retailer_id, merk, land, banner, periode) "
            "VALUES (?,?,?,?,?)", rows)
        return {"ok": True, "aantal": len(rows)}


@app.get("/api/{retailer_id}/assortiment")
def assortiment(retailer_id: str):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return _gecachet(("assortiment", retailer_id),
                         lambda: analytics.assortment(conn, retailer_id), conn)


# ---------------------------------------------------------------- datagaten

@app.get("/api/{retailer_id}/datagaten")
def lees_datagaten(retailer_id: str):
    """Jaren die tussen twee leveringen ontbreken, met het eerder gegeven
    oordeel. Zie engine/datagaten.py voor waarom dit niet uit de data zelf
    op te maken is."""
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)

        def bereken():
            caps, _ = analytics.retailer_caps(conn, retailer_id)
            if caps is None:
                return {"beschikbaar": False, "gaten": []}
            rows = analytics.load_facts(conn, retailer_id)
            return {"beschikbaar": True,
                    "gaten": datagaten.met_oordeel(conn, retailer_id, rows, caps)}

        return _gecachet(("datagaten", retailer_id), bereken, conn)


class DatagatOordeelBody(BaseModel):
    merk: str | None = None
    land: str | None = None
    banner: str | None = None
    van_jaar: int
    tot_jaar: int
    oordeel: str                      # 'klopt' | 'klopt_niet'
    toelichting: str | None = None
    door: str | None = None


@app.put("/api/{retailer_id}/datagaten")
def beoordeel_datagat(retailer_id: str, body: DatagatOordeelBody, request: Request):
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        try:
            datagaten.bewaar_oordeel(
                conn, retailer_id, body.merk, body.land, body.banner,
                body.van_jaar, body.tot_jaar, body.oordeel, body.toelichting,
                _gebruiker(request, body.door))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}


# ---------------------------------------------------------------- milestones

@app.get("/api/{retailer_id}/milestones")
def lees_milestones(retailer_id: str, merk: str | None = None):
    """De mijlpalen van deze retailer, desgewenst beperkt tot een merkselectie.

    Zonder merkfilter komt alles terug. Mét filter alleen de gekozen merken —
    plus de mijlpalen zonder merk: die dateren van vóór de merkkolom, gelden
    retailer-breed, en horen dus bij elke selectie."""
    gekozen = [m for m in (merk or "").split(",") if m]
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        rijen = [dict(r) for r in conn.execute(
            "SELECT * FROM milestones WHERE retailer_id=? "
            "ORDER BY jaar, periode_nummer", (retailer_id,))]
    if not gekozen:
        return rijen
    return [r for r in rijen if r["merk"] is None or r["merk"] in gekozen]


class MilestoneBody(BaseModel):
    jaar: int
    periode_nummer: int
    tekst: str
    merk: str
    door: str | None = None


def _merken_met_data(conn, retailer_id: str) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT merk FROM sellout_facts WHERE retailer_id=? AND merk IS NOT NULL",
        (retailer_id,))}


@app.post("/api/{retailer_id}/milestones")
def maak_milestone(retailer_id: str, body: MilestoneBody, request: Request):
    tekst = body.tekst.strip()
    if not tekst:
        raise HTTPException(422, "een mijlpaal heeft een omschrijving nodig")
    if not 1 <= body.periode_nummer <= 53:
        raise HTTPException(422, f"periodenummer {body.periode_nummer} valt buiten 1–53")
    merk = body.merk.strip()
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        # Alleen merken waarvan deze retailer ook echt data heeft: een mijlpaal
        # op een merk zonder lijn is een markering die nergens bij hoort, en
        # verdwijnt zodra iemand op merk filtert.
        bekend = _merken_met_data(conn, retailer_id)
        if merk not in bekend:
            raise HTTPException(422, f"onbekend merk {merk!r} voor deze retailer; "
                                     f"kies uit: {', '.join(sorted(bekend)) or 'geen'}")
        cur = conn.execute(
            "INSERT INTO milestones (retailer_id, jaar, periode_nummer, tekst, "
            "merk, aangemaakt_door) VALUES (?,?,?,?,?,?)",
            (retailer_id, body.jaar, body.periode_nummer, tekst[:200], merk,
             _gebruiker(request, body.door)))
        return dict(conn.execute("SELECT * FROM milestones WHERE id=?",
                                 (cur.lastrowid,)).fetchone())


@app.delete("/api/{retailer_id}/milestones/{milestone_id}")
def verwijder_milestone(retailer_id: str, milestone_id: int):
    with db.get_conn() as conn:
        cur = conn.execute("DELETE FROM milestones WHERE id=? AND retailer_id=?",
                           (milestone_id, retailer_id))
        if not cur.rowcount:
            raise HTTPException(404, "mijlpaal niet gevonden")
        return {"ok": True}


# ---------------------------------------------------------------- import

# Een .xlsx is een ZIP: een klein, geldig bestand kan intern uitpakken tot
# vele GB's XML en het proces zo het geheugen uit jagen vóór openpyxl ook
# maar één rij heeft gelezen (een "decompressiebom"). De byte-limiet
# hierboven begrenst alleen de GECOMPRIMEERDE grootte, dus deze check komt
# er los naast — niet-ZIP-bestanden (CSV, PDF) slaan 'm gewoon over.
MAX_UNCOMPRESSED_MB = int(os.environ.get("CONSOLE_MAX_UNCOMPRESSED_MB", "1500"))


def _keur_decompressie_goed(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            totaal = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        return  # geen ZIP/xlsx — niet dit type risico, de parser meldt zelf een nette fout
    limiet = MAX_UNCOMPRESSED_MB * 1024 * 1024
    if totaal > limiet:
        raise ValueError(
            f"bestand pakt uit tot meer dan {MAX_UNCOMPRESSED_MB} MB — "
            "dit lijkt geen geldig Excel-bestand")


async def _read_upload_limited(upload: UploadFile) -> bytes:
    """Lees in stukken en faal vóór een onbegrensde geheugentoewijzing."""
    content = bytearray()
    while chunk := await upload.read(1024 * 1024):
        if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
            raise ValueError(f"bestand is groter dan {MAX_UPLOAD_MB} MB")
        content.extend(chunk)
    _keur_decompressie_goed(content)
    return bytes(content)


def _safe_filename(upload: UploadFile) -> str:
    """Alleen de basisnaam: een pad in de bestandsnaam hoort nooit in de
    importlog of in een foutmelding terecht te komen."""
    return (upload.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1] or "upload"


@app.post("/api/import/controle")
async def import_preview(files: list[UploadFile]):
    """Kijk in het bestand en meld voor welke retailer het herkend wordt,
    ZONDER iets op te slaan. De gebruiker bevestigt daarna pas; zo landt een
    bestand nooit ongemerkt bij de verkeerde retailer."""
    with db.get_conn() as conn:
        profiles = get_profiles(conn)
        namen = {r["id"]: r["naam"] for r in conn.execute("SELECT id, naam FROM retailers")}
    out = []
    for f in files:
        filename = _safe_filename(f)
        try:
            content = await _read_upload_limited(f)
        except ValueError as e:
            out.append({"filename": filename, "herkend": False, "retailer_id": None,
                        "retailer_naam": None, "detail": str(e)})
            continue
        profile = parser_mod.detect(filename, content, profiles)
        if profile:
            detail = None
        elif parser_mod.sniff(filename, content):
            detail = "Geen parser herkent dit bestandsformaat."
        else:
            # Zelfs geen tabel te vinden: waarschijnlijk corrupt of geen
            # spreadsheet — dat is een ander gesprek dan "parser nodig".
            detail = ("Bestand kon niet als tabel gelezen worden — is het een "
                      "geldig XLSX- of CSV-bestand?")
        out.append({
            "filename": filename,
            "herkend": profile is not None,
            "retailer_id": profile.retailer_id if profile else None,
            "retailer_naam": namen.get(profile.retailer_id) if profile else None,
            "profiel_versie": profile.version if profile else None,
            "detail": detail,
        })
    return {"results": out}


# Bestanden die GEEN parser aankan worden bewaard, naast de database.
# Reden: de droplet is voor sommige beheerders alleen via een webconsole
# bereikbaar, en dan is er geen scp om een bestand naartoe te kopieren. Zonder
# deze map is een bestand dat de parser afwijst dus onbereikbaar voor het
# eenmalige inleesgereedschap in tools/. Geslaagde imports worden niet
# bewaard: die zitten al in de feiten.
INBOX = db.DB_PATH.parent / "inbox"
_VEILIG = re.compile(r"[^A-Za-z0-9._-]+")


def _bewaar_in_inbox(filename: str, content: bytes) -> str | None:
    """Schrijf het bestand weg en geef het pad terug (None bij mislukken).

    De naam wordt gestript tot letters, cijfers, punt, streepje en liggend
    streepje: een bestandsnaam uit een upload mag nooit uit de map kunnen
    stappen of aan een shell ontsnappen."""
    naam = _VEILIG.sub("_", filename).strip("._") or "upload.xlsx"
    try:
        INBOX.mkdir(parents=True, exist_ok=True, mode=0o700)
        doel = INBOX / naam
        doel.write_bytes(content)
        # Bestandsinhoud kan bedrijfsgevoelige verkoopcijfers bevatten —
        # niet leesbaar laten voor andere gebruikers op de host dan het
        # eigen procesaccount (anders het default umask-gedrag, doorgaans
        # world-readable).
        doel.chmod(0o600)
    except OSError as e:  # noqa: BLE001 - volle schijf mag de import niet slopen
        logger.error("kon %s niet in de inbox bewaren: %s", naam, e)
        return None
    return str(doel)


@app.post("/api/import")
async def do_import(files: list[UploadFile]):
    # One transaction PER FILE: a crash halfway through file 3 must not roll
    # back files 1 and 2 while the response still reports them as loaded.
    results = []
    for f in files:
        filename = _safe_filename(f)
        try:
            content = await _read_upload_limited(f)
            with db.get_conn() as conn:
                uitkomst = importer.run_import(conn, filename, content)
            if uitkomst.get("status") in ("profiel_nodig", "error"):
                pad = _bewaar_in_inbox(filename, content)
                if pad:
                    uitkomst["bewaard_als"] = pad
                    uitkomst["detail"] = ((uitkomst.get("detail") or "") +
                                          f" — bewaard als {pad}").strip(" —")
            results.append(uitkomst)
        except ValueError as e:
            # Bewust opgeworpen, veilige meldingen (te groot bestand,
            # decompressiebom) — die mogen letterlijk naar de gebruiker.
            results.append({"filename": filename, "status": "error",
                            "rows": 0, "retailer_id": None, "detail": str(e)})
        except Exception as e:  # noqa: BLE001 - one bad file must not kill the batch
            # Onverwachte fout (bug, DB-probleem): niet de ruwe exception-
            # tekst naar de client — die kan interne details lekken. Volledig
            # bericht gaat naar de serverlog, de gebruiker krijgt een veilige
            # samenvatting.
            logger.exception("onverwachte fout bij import van %s", filename)
            results.append({"filename": filename, "status": "error", "rows": 0,
                            "retailer_id": None,
                            "detail": "onverwachte fout bij het verwerken van dit bestand — "
                                      "probeer het opnieuw of neem contact op als dit blijft gebeuren"})
    return {"results": results}


@app.get("/api/imports")
def list_imports(retailer_id: str | None = None, limit: int = 50):
    limit = max(1, min(limit, 200))
    with db.get_conn() as conn:
        sql = ("SELECT im.*, p.version AS profiel_versie FROM imports im "
               "LEFT JOIN parser_profiles p ON p.id = im.profile_id ")
        params: tuple = ()
        if retailer_id:
            # PROFIEL NODIG-rijen hebben nog geen retailer: die moeten op
            # elke retailer-tab zichtbaar blijven, anders lijkt een upload
            # spoorloos te verdwijnen.
            sql += "WHERE (im.retailer_id = ? OR im.retailer_id IS NULL) "
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
            caps = capabilities(prof.definition) if prof else None
            statuses = ("ingelezen", "test") if prof and prof.status == "test" else ("ingelezen",)
            rows = conn.execute(
                "SELECT f.merk, f.land, f.banner, f.periode, im.created_at AS ts "
                "FROM sellout_facts f JOIN imports im ON im.id=f.import_id "
                f"AND im.status IN ({','.join('?' * len(statuses))}) WHERE f.retailer_id=?",
                (*statuses, r["id"])).fetchall()
            # Per feed de LAATSTE periode tonen. De oude query groepeerde op
            # merk maar liet een willekeurige periode zien met het totaal
            # aantal rijen over alle periodes erbij — dat las als "actueel"
            # terwijl het over de hele historie ging.
            grouped: dict[tuple, list] = {}
            for row in rows:
                key = (row["merk"], row["land"],
                       row["banner"] if caps and caps["banner"] else None)
                grouped.setdefault(key, []).append(row)
            feeds = []
            for (merk, land, banner), feed_rows in sorted(
                    grouped.items(), key=lambda kv: tuple(x or "" for x in kv[0])):
                latest = max((row["periode"] for row in feed_rows), key=sort_key)
                latest_rows = [row for row in feed_rows if row["periode"] == latest]
                scope = "per winkel" if caps and caps["winkel"] and not caps["banner"] else \
                    "/".join(x for x in (land, banner) if x) or "—"
                # Versheid per feed, niet alleen per retailer: één merk dat
                # weken achterloopt hoort hier rood te staan, ook als de rest
                # actueel is. Zelfde drempels als signals.data_signal.
                achter = signals.periods_behind(latest, caps["periode"]) if caps else 0
                feeds.append({"feed": merk or "—", "scope": scope, "periode": latest,
                              "ts": max(row["ts"] for row in latest_rows),
                              "rijen": len(latest_rows), "achter": achter,
                              "signaal": ("green" if achter <= 1 else
                                          "orange" if achter <= 4 else "red")})
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
                        "capabilities": capabilities(p.definition)})
        return out


@app.post("/api/parser/{retailer_id}/test")
async def test_profile(retailer_id: str, file: UploadFile):
    """'Controleren op bestand': parse met de parser van deze retailer en
    sla niets op. Alleen lezen — profielen worden in het project gemaakt,
    niet in de app."""
    with db.get_conn() as conn:
        profs = get_profiles(conn, retailer_id)
    if not profs:
        raise HTTPException(404, "geen profiel")
    profile = profs[0]
    try:
        content = await _read_upload_limited(file)
    except ValueError as e:
        raise HTTPException(413, str(e)) from e
    try:
        result = parser_mod.parse_file(_safe_filename(file), content, profile)
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
            # Welke merk/land/banner-combinaties er daadwerkelijk in de feed
            # zitten: het instellingenscherm biedt daarvoor kant-en-klare
            # "rij toevoegen"-knoppen, zodat een verse installatie niet
            # doodloopt op een lege tabel.
            "feed_combinaties": [dict(r) for r in conn.execute(
                "SELECT DISTINCT merk, land, banner FROM sellout_facts "
                "WHERE retailer_id=? ORDER BY merk, land, banner", (retailer_id,))],
            "winkels_targets": [dict(r) for r in conn.execute(
                "SELECT * FROM retailer_settings WHERE retailer_id=? ORDER BY merk, land, banner",
                (retailer_id,))],
            # Elke wijziging van een winkelaantal, zodat het scherm kan tonen
            # dat een merk in minder winkels ligt dan eerst.
            "winkels_historie": [dict(r) for r in conn.execute(
                "SELECT id, merk, land, banner, aantal_winkels, geldig_vanaf, gemeten_op "
                "FROM winkelaantal_historie WHERE retailer_id=? "
                "ORDER BY merk, land, banner, geldig_vanaf", (retailer_id,))],
            "rotatie_targets": [dict(r) for r in conn.execute(
                "SELECT * FROM rotatie_targets WHERE retailer_id=? ORDER BY merk", (retailer_id,))],
            "mail_rules": [dict(r) for r in conn.execute(
                "SELECT * FROM mail_rules WHERE retailer_id=? ORDER BY id", (retailer_id,))],
            "documenten": [_contract_doc(r) for r in conn.execute(
                "SELECT * FROM contract_documents WHERE retailer_id=? ORDER BY naam", (retailer_id,))],
        }


class SettingsBody(BaseModel):
    winkels_targets: list[dict] | None = None   # [{merk, land, banner, aantal_winkels, target_per_winkel}]
    rotatie_targets: list[dict] | None = None   # [{merk, stuks_per_winkel_per_week}]
    mail_rules: list[dict] | None = None        # [{naam, afzender, bijlage_glob, actief}]


def _validate_settings(body: "SettingsBody"):
    """Raise KeyError before the transaction starts, so a malformed row can
    never surface as a 500 halfway through a delete-and-reinsert."""
    for s in body.winkels_targets or []:
        s["merk"], s["land"]
        # Nul of negatief werd stroomafwaarts stil genegeerd; beter meteen
        # weigeren dan een instelling opslaan die nooit iets doet.
        if s.get("aantal_winkels") is not None and s["aantal_winkels"] <= 0:
            raise ValueError(f"aantal_winkels moet groter dan nul zijn ({s['merk']})")
        if s.get("target_per_winkel") is not None and s["target_per_winkel"] < 0:
            raise ValueError(f"target_per_winkel kan niet negatief zijn ({s['merk']})")
    for t in body.rotatie_targets or []:
        t["merk"], t["stuks_per_winkel_per_week"]
        if t["stuks_per_winkel_per_week"] is not None and t["stuks_per_winkel_per_week"] <= 0:
            raise ValueError(f"rotatietarget moet groter dan nul zijn ({t['merk']})")
    for m in body.mail_rules or []:
        m["naam"]


@app.put("/api/{retailer_id}/instellingen")
def save_settings(retailer_id: str, body: SettingsBody):
    """'Alles opslaan' — atomic: one transaction for the whole payload. A
    malformed row is a 422 before anything is touched; the transaction only
    commits when every part succeeded."""
    try:
        _validate_settings(body)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"ongeldige instelling: {e}")
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        if body.winkels_targets is not None:
            conn.executemany(
                "INSERT INTO winkelaantal_historie (retailer_id, merk, land, banner, "
                "aantal_winkels, geldig_vanaf) VALUES (?,?,?,?,?,?)",
                winkelhistorie.nieuwe_metingen(conn, retailer_id, body.winkels_targets))
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


class WinkelaantalBody(BaseModel):
    merk: str
    land: str | None = None
    banner: str | None = None
    aantal_winkels: int
    geldig_vanaf: str          # YYYY-MM-DD: vanaf wanneer dit aantal gold


@app.post("/api/{retailer_id}/winkelaantallen")
def add_winkelaantal(retailer_id: str, body: WinkelaantalBody):
    """Een winkelaantal met terugwerkende kracht vastleggen.

    Zonder datums zou de omzet per winkel over de hele historie door het
    getal van vandaag gedeeld worden — precies het effect dat zichtbaar moet
    worden verdwijnt dan. Hiermee leg je vast dat er bijvoorbeeld 530 winkels
    waren vanaf 01-2025 en 470 vanaf 06-2026."""
    if body.aantal_winkels <= 0:
        raise HTTPException(422, "aantal_winkels moet groter dan nul zijn")
    try:
        datum = dt.date.fromisoformat(body.geldig_vanaf)
    except ValueError:
        raise HTTPException(422, f"geldig_vanaf {body.geldig_vanaf!r} is geen datum (YYYY-MM-DD)")
    if datum > dt.date.today():
        raise HTTPException(422, "geldig_vanaf ligt in de toekomst")
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        # Eén meting per scope per datum: opnieuw invoeren corrigeert de
        # vorige in plaats van er een tweede waarheid naast te zetten.
        conn.execute(
            "DELETE FROM winkelaantal_historie WHERE retailer_id=? AND geldig_vanaf=? "
            "AND COALESCE(merk,'')=COALESCE(?,'') AND COALESCE(land,'')=COALESCE(?,'') "
            "AND COALESCE(banner,'')=COALESCE(?,'')",
            (retailer_id, datum.isoformat(), body.merk, body.land, body.banner))
        conn.execute(
            "INSERT INTO winkelaantal_historie (retailer_id, merk, land, banner, "
            "aantal_winkels, geldig_vanaf) VALUES (?,?,?,?,?,?)",
            (retailer_id, body.merk, body.land, body.banner, body.aantal_winkels,
             datum.isoformat()))
        return {"ok": True}


@app.delete("/api/{retailer_id}/winkelaantallen/{meting_id}")
def delete_winkelaantal(retailer_id: str, meting_id: int):
    with db.get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM winkelaantal_historie WHERE id=? AND retailer_id=?",
            (meting_id, retailer_id))
        if not cur.rowcount:
            raise HTTPException(404, "meting niet gevonden")
        return {"ok": True}


@app.post("/api/{retailer_id}/contract")
async def upload_contract(retailer_id: str, request: Request, file: UploadFile, door: str | None = None):
    """PDF uploaden: vervangt het huidige contract van deze retailer. Claude
    haalt looptijd, conclusie en condities eruit; het signaal blijft
    daarna live herberekend uit de gevonden einddatum (signals.py)."""
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        try:
            content = await _read_upload_limited(file)
        except ValueError as e:
            raise HTTPException(422, str(e))
        wie = _gebruiker(request, door)
        try:
            doc = contracts.verwerk_upload(conn, retailer_id, _safe_filename(file), content, wie)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True, "document": _contract_doc(doc)}


@app.get("/api/{retailer_id}/contract/historie")
def contract_historie(retailer_id: str):
    """Eerder vervangen contracten — ter inzage, nooit sturend voor het
    actuele signaal (dat blijft uitsluitend op contract_documents staan)."""
    with db.get_conn() as conn:
        _retailer_or_404(conn, retailer_id)
        return {"historie": [_contract_doc(r) for r in contracts.historie(conn, retailer_id)]}


def _masker(sleutel: str) -> str:
    """Nooit de volledige sleutel teruggeven aan de frontend."""
    if len(sleutel) <= 12:
        return "•••• (ingesteld)"
    return f"{sleutel[:10]}…{sleutel[-4:]}"


def _bedrijf(conn) -> dict:
    row = conn.execute("SELECT * FROM bedrijfsinstellingen WHERE id=1").fetchone()
    return dict(row) if row else {"drempel_eenmalig_pct": None,
                                  "drempel_terugkerend_pct": None}


def _drempels(conn) -> dict:
    r = _bedrijf(conn)
    return {"eenmalig": r["drempel_eenmalig_pct"],
            "terugkerend": r["drempel_terugkerend_pct"]}


@app.get("/api/systeem/bedrijf")
def lees_bedrijfsinstellingen():
    with db.get_conn() as conn:
        return _bedrijf(conn)


class BedrijfBody(BaseModel):
    # None = geen drempel; dan meet het scherm niets en meldt het niets.
    drempel_eenmalig_pct: float | None = None
    drempel_terugkerend_pct: float | None = None
    door: str | None = None


@app.put("/api/systeem/bedrijf")
def zet_bedrijfsinstellingen(body: BedrijfBody, request: Request):
    for naam, waarde in (("eenmalige omzet", body.drempel_eenmalig_pct),
                         ("terugkerende omzet", body.drempel_terugkerend_pct)):
        # 100% marge kan niet (dan is de kostprijs nul) en negatief is geen
        # drempel maar een doel om verlies te maken.
        if waarde is not None and not 0 <= waarde < 100:
            raise HTTPException(422, f"drempel voor {naam} moet tussen 0 en 100 liggen, "
                                     f"niet {waarde}")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE bedrijfsinstellingen SET drempel_eenmalig_pct=?, "
            "drempel_terugkerend_pct=?, bijgewerkt_op=?, bijgewerkt_door=? WHERE id=1",
            (body.drempel_eenmalig_pct, body.drempel_terugkerend_pct,
             dt.datetime.now().isoformat(timespec="seconds"),
             _gebruiker(request, body.door)))
        return _bedrijf(conn)


def _anthropic_status(conn) -> dict:
    row = conn.execute("SELECT * FROM anthropic_config WHERE id=1").fetchone()
    sleutel, bron = contracts.haal_api_key(conn)
    return {
        "ingesteld": sleutel is not None,
        "gemaskeerd": _masker(sleutel) if sleutel else None,
        "bron": bron,
        "bijgewerkt_op": row["bijgewerkt_op"] if row else None,
        "bijgewerkt_door": row["bijgewerkt_door"] if row else None,
        "laatst_getest_op": row["laatst_getest_op"] if row else None,
        "laatst_status": row["laatst_status"] if row else None,
        "laatst_melding": row["laatst_melding"] if row else None,
    }


@app.get("/api/systeem/anthropic")
def anthropic_status():
    with db.get_conn() as conn:
        return _anthropic_status(conn)


class AnthropicKeyBody(BaseModel):
    api_key: str


@app.put("/api/systeem/anthropic")
def anthropic_opslaan(body: AnthropicKeyBody, request: Request):
    """Lege sleutel wist de DB-override en valt terug op de
    omgevingsvariabele. Na opslaan wordt de resulterende sleutel meteen
    getest, zodat de status altijd actueel is."""
    with db.get_conn() as conn:
        nu = dt.datetime.now().isoformat(timespec="seconds")
        wie = _gebruiker(request, None)
        conn.execute(
            "UPDATE anthropic_config SET api_key=?, bijgewerkt_op=?, bijgewerkt_door=? WHERE id=1",
            (body.api_key.strip() or None, nu, wie))
        sleutel, _ = contracts.haal_api_key(conn)
        if sleutel:
            ok, melding = contracts.test_sleutel(sleutel)
        else:
            ok, melding = False, "Geen sleutel ingesteld"
        conn.execute(
            "UPDATE anthropic_config SET laatst_getest_op=?, laatst_status=?, laatst_melding=? "
            "WHERE id=1", (nu, "ok" if ok else "fout", melding))
        return _anthropic_status(conn)


@app.post("/api/systeem/anthropic/test")
def anthropic_testen():
    """Hertest de huidige sleutel (DB of terugval op env) zonder hem te
    wijzigen — zo signaleert een extern ingetrokken sleutel zich vanzelf."""
    with db.get_conn() as conn:
        sleutel, _ = contracts.haal_api_key(conn)
        nu = dt.datetime.now().isoformat(timespec="seconds")
        if sleutel:
            ok, melding = contracts.test_sleutel(sleutel)
        else:
            ok, melding = False, "Geen sleutel ingesteld"
        conn.execute(
            "UPDATE anthropic_config SET laatst_getest_op=?, laatst_status=?, laatst_melding=? "
            "WHERE id=1", (nu, "ok" if ok else "fout", melding))
        return _anthropic_status(conn)


# ---------------------------------------------------------------- projecten

# Wie deed dit? De console zelf heeft geen inlog (het portaal authenticeert),
# maar veel portalen geven de ingelogde gebruiker door in een header. Die is
# leidend; anders de naam die de gebruiker in het scherm heeft ingevuld
# (localStorage, gaat mee in de payload); anders "onbekend". Het logboek is
# een werkafspraak, geen beveiliging.
_GEBRUIKER_HEADERS = ("remote-user", "remote-email", "x-forwarded-user",
                      "x-auth-request-user", "x-auth-request-email")


def _gebruiker(request: Request, door: str | None) -> str:
    for h in _GEBRUIKER_HEADERS:
        w = request.headers.get(h)
        if w and w.strip():
            return w.strip()[:80]
    if door and door.strip():
        return door.strip()[:80]
    return "onbekend"


@app.get("/api/wie-ben-ik")
def wie_ben_ik(request: Request):
    """Zodat het scherm het handmatige naamveld kan laten verdwijnen zodra
    het portaal een identiteit meestuurt — automatisch waar het kan,
    handmatig als terugval waar het (nog) niet kan."""
    for h in _GEBRUIKER_HEADERS:
        w = request.headers.get(h)
        if w and w.strip():
            return {"naam": w.strip()[:80], "bron": "portaal"}
    return {"naam": None, "bron": "handmatig"}


def _project_or_404(conn, project_id: int):
    row = conn.execute("SELECT * FROM projecten WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "project niet gevonden")
    return row


def _project_detail(conn, project_id: int) -> dict:
    row = _project_or_404(conn, project_id)
    producten = [dict(r) for r in conn.execute(
        "SELECT * FROM project_producten WHERE project_id=? ORDER BY volgorde, id",
        (project_id,))]
    kosten = [dict(r) for r in conn.execute(
        "SELECT * FROM project_kosten WHERE project_id=? ORDER BY volgorde, id",
        (project_id,))]
    log = [dict(r) for r in conn.execute(
        "SELECT op, door, actie FROM project_log WHERE project_id=? ORDER BY op DESC, id DESC",
        (project_id,))]
    return {**dict(row), "producten": producten, "kosten": kosten, "log": log,
            "berekening": projecten.bereken(dict(row), producten, kosten,
                                            _drempels(conn))}


class ProjectBody(BaseModel):
    naam: str
    retailer_id: str | None = None
    omschrijving: str | None = None
    start_datum: str | None = None
    eind_datum: str | None = None
    status: str = "concept"       # concept | definitief — label, geen slot
    producten: list[dict] = []
    kosten: list[dict] = []
    door: str | None = None       # naam voor het logboek (zie _gebruiker)


def _valideer_project(conn, body: ProjectBody):
    try:
        projecten.valideer(body.model_dump(), body.producten, body.kosten)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"ongeldig project: {e}")
    if body.retailer_id:
        _retailer_or_404(conn, body.retailer_id)


@app.get("/api/projecten")
def list_projecten():
    with db.get_conn() as conn:
        namen = {r["id"]: r["naam"] for r in conn.execute("SELECT id, naam FROM retailers")}
        out = []
        for row in conn.execute("SELECT * FROM projecten ORDER BY COALESCE(gewijzigd_op, aangemaakt_op) DESC"):
            d = _project_detail(conn, row["id"])
            b = d["berekening"]
            out.append({
                "id": row["id"], "naam": row["naam"], "status": row["status"],
                "retailer_id": row["retailer_id"],
                "retailer_naam": namen.get(row["retailer_id"]),
                "start_datum": row["start_datum"], "eind_datum": row["eind_datum"],
                "looptijd_weken": b["looptijd_weken"],
                "aantal_producten": len(d["producten"]),
                "eenmalig": b["eenmalig"], "terugkerend": b["terugkerend"],
                "aangemaakt_op": row["aangemaakt_op"], "aangemaakt_door": row["aangemaakt_door"],
                "gewijzigd_op": row["gewijzigd_op"], "gewijzigd_door": row["gewijzigd_door"],
            })
        return out


@app.post("/api/projecten")
def create_project(body: ProjectBody, request: Request):
    with db.get_conn() as conn:
        _valideer_project(conn, body)
        wie = _gebruiker(request, body.door)
        cur = conn.execute(
            "INSERT INTO projecten (naam, retailer_id, omschrijving, start_datum, "
            "eind_datum, status, aangemaakt_door) VALUES (?,?,?,?,?,?,?)",
            (body.naam.strip(), body.retailer_id, body.omschrijving,
             body.start_datum, body.eind_datum, body.status, wie))
        project_id = cur.lastrowid
        # Elk project start met de vaste kostenregels: bedragen leeg, schakel
        # op de gebruikelijke stand. Weglaten wat niet speelt kan altijd nog.
        conn.executemany(
            "INSERT INTO project_kosten (project_id, volgorde, soort, label, bedrag, terugkerend) "
            "VALUES (?,?,?,?,NULL,?)",
            [(project_id, i, soort, label, terugkerend)
             for i, (soort, label, terugkerend) in enumerate(projecten.STANDAARD_KOSTEN)])
        conn.execute(
            "INSERT INTO project_log (project_id, door, actie) VALUES (?,?,?)",
            (project_id, wie, "aangemaakt"))
        return _project_detail(conn, project_id)


@app.get("/api/projecten/{project_id}")
def get_project(project_id: int):
    with db.get_conn() as conn:
        return _project_detail(conn, project_id)


@app.put("/api/projecten/{project_id}")
def save_project(project_id: int, body: ProjectBody, request: Request):
    """Alles-in-één opslaan, atomair: velden, producten en kosten in één
    transactie vervangen — zelfde patroon als Instellingen.

    Het scherm slaat automatisch op (geen 'Opslaan'-knop meer, gedebounced
    op elke wijziging), dus dit endpoint kan tientallen keren per minuut
    binnenkomen terwijl iemand typt. Zie het log-blok onderaan voor hoe dat
    het logboek niet laat volstromen met één regel per toetsaanslag."""
    with db.get_conn() as conn:
        _project_or_404(conn, project_id)
        _valideer_project(conn, body)
        wie = _gebruiker(request, body.door)
        conn.execute(
            "UPDATE projecten SET naam=?, retailer_id=?, omschrijving=?, start_datum=?, "
            "eind_datum=?, status=?, gewijzigd_op=datetime('now'), gewijzigd_door=? WHERE id=?",
            (body.naam.strip(), body.retailer_id, body.omschrijving,
             body.start_datum, body.eind_datum, body.status, wie, project_id))
        conn.execute("DELETE FROM project_producten WHERE project_id=?", (project_id,))
        conn.executemany(
            "INSERT INTO project_producten (project_id, volgorde, naam, kostprijs, "
            "verkoopprijs, aantal_winkels, stuks_per_winkel, rotatie_per_winkel_per_week) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(project_id, i, p["naam"].strip(), p.get("kostprijs"), p.get("verkoopprijs"),
              p.get("aantal_winkels"), p.get("stuks_per_winkel"),
              p.get("rotatie_per_winkel_per_week"))
             for i, p in enumerate(body.producten)])
        conn.execute("DELETE FROM project_kosten WHERE project_id=?", (project_id,))
        conn.executemany(
            "INSERT INTO project_kosten (project_id, volgorde, soort, label, bedrag, terugkerend) "
            "VALUES (?,?,?,?,?,?)",
            [(project_id, i, k["soort"], k["label"].strip(), k.get("bedrag"),
              1 if k.get("terugkerend") else 0)
             for i, k in enumerate(body.kosten)])
        actie = (f"gewijzigd — {len(body.producten)} product(en), "
                 f"{len(body.kosten)} kostenregel(s)")
        projecten.log_wijziging(conn, project_id, wie, actie)
        return _project_detail(conn, project_id)


@app.delete("/api/projecten/{project_id}")
def delete_project(project_id: int):
    with db.get_conn() as conn:
        _project_or_404(conn, project_id)
        # ON DELETE CASCADE ruimt producten, kosten en log mee op.
        conn.execute("DELETE FROM projecten WHERE id=?", (project_id,))
        return {"ok": True}


# ---------------------------------------------------------------- health
# Unauthenticated, read-only and cheap: verifies the process is up AND that
# its database answers, so a gateway probe fails when the app is truly
# unusable rather than merely slow to render.

@app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/healthz/", methods=["GET", "HEAD"], include_in_schema=False)
def healthz():
    from starlette.responses import JSONResponse
    try:
        with db.get_conn() as conn:
            # Welke parsers deze container daadwerkelijk heeft (hoogste
            # live-versie per retailer): één curl beantwoordt "draait de
            # nieuwe parser hier al?" — onmisbaar bij uitrolvragen, en geen
            # gevoelige informatie.
            profielen = {r["retailer_id"]: r["v"] for r in conn.execute(
                "SELECT retailer_id, MAX(version) v FROM parser_profiles "
                "WHERE status='live' GROUP BY retailer_id")}
    except Exception as e:  # noqa: BLE001 - probe must report, not raise
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)
    return {"status": "ok", "profielen": profielen}


# ---------------------------------------------------------------- frontend
# In the container the built SPA sits in backend/static; in local dev it is
# absent and Vite serves the frontend on :5173 instead.

@app.middleware("http")
async def cache_headers(request, call_next):
    """Expliciete cache-regels per soort verzoek.

    Zonder Cache-Control mag een browser zelf een bewaartermijn verzinnen
    (heuristisch, op basis van Last-Modified). Voor index.html is dat
    gevaarlijk: die verwijst naar een bestandsnaam met een inhoudshash, en na
    een nieuwe build bestaat die naam niet meer. De browser laadt dan een oude
    index.html, vraagt een script op dat 404 geeft, en toont een lege pagina —
    precies het beeld waarbij incognito het wél doet.

      /assets/*  namen bevatten een hash, dus de inhoud wijzigt nooit: een
                 jaar bewaren, en bij een nieuwe build hoort er een nieuwe
                 naam bij. Dit scheelt het opnieuw ophalen van de bundle bij
                 elke schermwissel.
      /api/*     nooit bewaren; verkoopcijfers uit de cache zijn erger dan
                 een verzoek extra.
      overige    (index.html) altijd even navragen; met de ETag kost dat een
                 304 en geen nieuwe download.
    """
    response = await call_next(request)
    pad = request.url.path
    if pad.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif pad.startswith("/api/") or pad in HEALTH_PATHS:
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


STATIC = Path(__file__).resolve().parent / "static"
if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Client-side routing: every non-API path renders the SPA. Only
        files that really live inside the static dir are served — a path
        that escapes it (../…) falls through to index.html."""
        # Een niet-bestaand API-pad hoort een echte 404 te zijn; de SPA-pagina
        # met status 200 teruggeven zou elke frontend-fout maskeren.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404)
        base = STATIC.resolve()
        try:
            candidate = (STATIC / full_path).resolve()
        except (OSError, ValueError):
            candidate = base
        if full_path and candidate.is_file() and candidate.is_relative_to(base):
            return FileResponse(candidate)
        return FileResponse(base / "index.html")
