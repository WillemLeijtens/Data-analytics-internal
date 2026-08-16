import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";

const STATUS_LABEL: Record<string, [string, boolean]> = {
  ingelezen: ["INGELEZEN", false],
  test: ["INGELEZEN (TEST)", false],
  profiel_nodig: ["PROFIEL NODIG", true],
  error: ["FOUT", true],
};

type Pending = { file: File; preview: any };

function Vink() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function Kruis() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="3" strokeLinecap="round">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export default function ImportScreen({ ctx }: { ctx: ShellCtx }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<any | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [uploadResults, setUploadResults] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    apiGet(`/imports${ctx.retailer !== "alle" ? `?retailer_id=${ctx.retailer}` : ""}`)
      .then((r) => { setRows(r); setError(null); })
      .catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { refresh(); }, [ctx.retailer]);

  /** Stap 1: kijk in het bestand, sla nog niets op. */
  const inspect = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setUploadResults([]);
    const lijst = Array.from(files);
    const fd = new FormData();
    for (const f of lijst) fd.append("files", f);
    try {
      const r = await apiSend<{ results: any[] }>("/import/controle", "POST", fd);
      setPending(lijst.map((file, i) => ({ file, preview: r.results[i] })));
      setError(null);
    } catch (e: any) {
      setError(`Controleren mislukt: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  };

  /** Stap 2: pas ná bevestiging echt importeren. */
  const bevestig = async (item: Pending) => {
    setBusy(true);
    const fd = new FormData();
    fd.append("files", item.file);
    try {
      const r = await apiSend<{ results: any[] }>("/import", "POST", fd);
      setUploadResults((prev) => [...prev, ...(r.results ?? [])]);
      setError(null);
    } catch (e: any) {
      setError(`Import mislukt: ${e?.message ?? e}`);
    } finally {
      setPending((p) => p.filter((x) => x !== item));
      setBusy(false);
      refresh();
    }
  };

  const annuleer = (item: Pending) =>
    setPending((p) => p.filter((x) => x !== item));

  return (
    <>
      <h1>Import{ctx.card ? ` — ${ctx.card.naam}` : ""}</h1>
      <p className="sub">De import herkent de retailer aan de inhoud en indeling van het bestand
        en kiest zelf de juiste parser. Je krijgt eerst te zien om welke retailer het gaat en
        bevestigt daarna pas.</p>

      {error && (
        <div className="level-strip" style={{ borderLeft: "3px solid oklch(0.55 0.18 27)" }}>
          <span className="sub">{error}</span>
          <a style={{ cursor: "pointer", marginLeft: "auto" }} onClick={() => refresh()}>Opnieuw proberen</a>
        </div>
      )}

      <div className="dropzone" style={{ margin: "20px 0" }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); inspect(e.dataTransfer.files); }}>
        <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? "Bezig…" : "Bestanden kiezen"}
        </button>
        <p className="sub" style={{ marginTop: 12 }}>Of sleep ze hierheen — XLSX of CSV, max 200 MB.</p>
        <input ref={fileRef} type="file" multiple hidden accept=".xlsx,.csv,.txt"
          onChange={(e) => { inspect(e.target.files); e.target.value = ""; }} />
      </div>

      {pending.map((item, i) => {
        const p = item.preview;
        const anderTabblad = p.herkend && ctx.retailer !== "alle" && p.retailer_id !== ctx.retailer;
        return (
          <div key={`${p.filename}-${i}`} className="card" style={{ marginBottom: 12 }}>
            <div className="eyebrow">Controleer vóór importeren</div>
            <p className="mono" style={{ margin: "8px 0 4px" }}>{p.filename}</p>
            {p.herkend ? (
              <>
                <p style={{ fontSize: 15, margin: "6px 0 2px" }}>
                  Dit is een bestand voor <b>{p.retailer_naam ?? p.retailer_id}</b>. Klopt dat?
                </p>
                {anderTabblad && (
                  <p className="sub" style={{ color: "#B4690E" }}>
                    Let op: je staat op het tabblad {ctx.card?.naam}. Bevestig je, dan komt het
                    bestand onder {p.retailer_naam ?? p.retailer_id} te staan — niet onder {ctx.card?.naam}.
                  </p>
                )}
              </>
            ) : (
              <p style={{ fontSize: 15, margin: "6px 0 2px" }}>
                Voor dit bestandsformaat bestaat nog <b>geen parser</b>. Bevestig je,
                dan wordt het geregistreerd als “profiel nodig”. Deel het bestand —
                de parser wordt in het Claude&nbsp;Code-project gebouwd en komt mee
                met een update.
              </p>
            )}
            {!p.herkend && p.detail && (
              // Onderscheid "parser nodig" van "bestand onleesbaar".
              <p className="sub" style={{ color: "#B4690E" }}>{p.detail}</p>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
              <button className="btn" disabled={busy} onClick={() => bevestig(item)}
                style={{ display: "inline-flex", alignItems: "center", gap: 8,
                         background: "var(--pos)", borderColor: "var(--pos)" }}>
                <Vink /> Ja, importeren
              </button>
              <button className="btn ghost" disabled={busy} onClick={() => annuleer(item)}
                style={{ display: "inline-flex", alignItems: "center", gap: 8,
                         color: "var(--neg)", borderColor: "var(--neg)" }}>
                <Kruis /> Nee, niet importeren
              </button>
            </div>
          </div>
        );
      })}

      {uploadResults.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="eyebrow">Resultaat van deze upload</div>
          {uploadResults.map((r, i) => {
            const [label, accent] = STATUS_LABEL[r.status] ?? [String(r.status).toUpperCase(), true];
            return (
              <div key={`${r.filename}-${i}`} style={{ display: "flex", gap: 12, alignItems: "center", paddingTop: 9, flexWrap: "wrap" }}>
                <span className={`status-label ${accent ? "need" : ""}`}>{label}</span>
                <span className="mono">{r.filename}</span>
                <span className="sub">{r.retailer_id ?? "retailer onbekend"} · {r.rows ?? 0} rijen</span>
                {r.retailer_id && ctx.retailer !== "alle" && r.retailer_id !== ctx.retailer && (
                  // Het bestand hoorde bij een andere retailer, dus staat het
                  // niet in de lijst hieronder — wijs de weg ernaartoe.
                  <a style={{ cursor: "pointer" }} onClick={() => ctx.go(r.retailer_id, "dashboard")}>
                    Bekijk bij {r.retailer_id}
                  </a>
                )}
                {r.detail && (
                  <span className="sub" style={{ marginLeft: "auto", maxWidth: "48%", textAlign: "right" }}>
                    {r.status === "error" ? r.detail : `Let op: ${r.detail}`}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      <table className="data">
        <thead><tr><th>Bestand</th><th>Retailer</th><th>Profiel</th><th>Periode</th><th>Rijen</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((r) => {
            const [label, accent] = STATUS_LABEL[r.status] ?? [r.status.toUpperCase(), true];
            return (
              <tr key={r.id}>
                <td className="mono">{r.filename}</td>
                <td>{r.retailer_id ?? "—"}</td>
                <td>{r.profiel_versie ? `v${r.profiel_versie}` : "—"}</td>
                <td>{r.periode ?? "—"}</td>
                <td>{r.row_count ?? "—"}</td>
                <td>
                  <span className={`status-label ${accent ? "need" : ""}`}>{label}</span>
                  {r.status !== "error" && r.error_detail && (
                    <span className="status-label need" style={{ marginLeft: 6 }}>LET OP</span>
                  )}
                </td>
                <td>
                  {r.status === "profiel_nodig"
                    ? ctx.retailer === "alle"
                      ? <span className="sub">Kies bovenaan eerst de juiste retailer</span>
                      : <a style={{ cursor: "pointer" }} onClick={() => ctx.go(ctx.retailer, "parser")}>Nog geen parser — bekijken</a>
                    : r.error_detail
                      ? <a style={{ cursor: "pointer" }} onClick={() => {
                        try { setDetail(JSON.parse(r.error_detail)); }
                        catch { setDetail({ message: r.error_detail }); }
                      }}>Bekijk</a>
                      : null}
                </td>
              </tr>
            );
          })}
          {!rows.length && <tr><td colSpan={7} className="sub">Nog geen imports.</td></tr>}
        </tbody>
      </table>

      {detail && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <div className="eyebrow">{detail.warnings ? "Waarschuwingen" : "Foutdetail"}</div>
            <a style={{ cursor: "pointer" }} onClick={() => setDetail(null)}>Sluiten</a>
          </div>
          {detail.message && <p>{detail.message}</p>}
          <ul className="sub">
            {(detail.rijen ?? []).slice(0, 15).map((e: any, i: number) => (
              <li key={i}>rij {e.rij} · {e.veld}: {e.fout}</li>
            ))}
            {(detail.warnings ?? []).map((w: string, i: number) => <li key={`w${i}`}>{w}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}
