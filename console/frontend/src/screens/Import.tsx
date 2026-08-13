import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";

const STATUS_LABEL: Record<string, [string, boolean]> = {
  ingelezen: ["INGELEZEN", false],
  test: ["INGELEZEN (TEST)", false],
  profiel_nodig: ["PROFIEL NODIG", true],
  error: ["FOUT", true],
};

export default function ImportScreen({ ctx }: { ctx: ShellCtx }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<any | null>(null);

  const refresh = () =>
    apiGet(`/imports${ctx.retailer !== "alle" ? `?retailer_id=${ctx.retailer}` : ""}`).then(setRows);
  useEffect(() => { refresh(); }, [ctx.retailer]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append("files", f);
    try { await apiSend("/import", "POST", fd); } finally { setBusy(false); refresh(); }
  };

  return (
    <>
      <h1>Import{ctx.card ? ` — ${ctx.card.naam}` : ""}</h1>
      <p className="sub">De import herkent de retailer aan bestandsnaam, werkblad en kolomkoppen
        en kiest zelf het juiste parser-profiel. Onbekend bestand? Dan vraagt de Parser één keer om een mapping.</p>

      <div className="dropzone" style={{ margin: "20px 0" }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}>
        <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
          {busy ? "Bezig…" : "Bestanden kiezen"}
        </button>
        <p className="sub" style={{ marginTop: 12 }}>Of sleep ze hierheen — XLSX of CSV, max 200 MB.</p>
        <input ref={fileRef} type="file" multiple hidden accept=".xlsx,.csv,.txt"
          onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
      </div>

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
                <td><span className={`status-label ${accent ? "need" : ""}`}>{label}</span></td>
                <td>
                  {r.status === "profiel_nodig"
                    ? <a style={{ cursor: "pointer" }} onClick={() => ctx.go(ctx.retailer === "alle" ? "douglas" : ctx.retailer, "parser")}>Kolommen mappen</a>
                    : r.error_detail
                      ? <a style={{ cursor: "pointer" }} onClick={() => setDetail(JSON.parse(r.error_detail))}>Bekijk</a>
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
            <div className="eyebrow">Foutdetail</div>
            <a style={{ cursor: "pointer" }} onClick={() => setDetail(null)}>Sluiten</a>
          </div>
          <p>{detail.message}</p>
          <ul className="sub">
            {(detail.rijen ?? []).slice(0, 15).map((e: any, i: number) => (
              <li key={i}>rij {e.rij} · {e.veld}: {e.fout}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
