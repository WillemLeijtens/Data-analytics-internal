import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";

const CANONICAL = ["periode", "merk", "artikel_ean", "artikel_naam", "winkel_id",
  "winkel_naam", "land", "banner", "volume", "omzet"];

const ANALYSES: [string, (c: any) => string][] = [
  ["Dashboard", (c) => (c.winkel ? "VOLLEDIG" : "SCHATTING")],
  ["Artikelanalyse", (c) => (c.artikel ? "VOLLEDIG" : c.merk ? "OP MERKNIVEAU" : "NIET BESCHIKBAAR")],
  ["Promoties", (c) => (c.periode === "maand" ? "OP MAANDNIVEAU" : "VOLLEDIG")],
  ["Assortimentsanalyse", (c) => (c.artikel ? (c.winkel ? "VOLLEDIG" : "SCHATTING") : "NIET BESCHIKBAAR")],
];

export default function Parser({ ctx }: { ctx: ShellCtx }) {
  const [profiles, setProfiles] = useState<any[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [draft, setDraft] = useState<any | null>(null);
  const [testResult, setTestResult] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => apiGet("/parser/profielen").then((ps) => {
    setProfiles(ps);
    const mine = ps.filter((p: any) => p.retailer_id === ctx.retailer);
    if (mine.length && (selId == null || !ps.some((p: any) => p.id === selId))) setSelId(mine[0].id);
  });
  useEffect(() => { refresh(); setDraft(null); setTestResult(null); }, [ctx.retailer]);

  const sel = profiles.find((p) => p.id === selId) ?? null;
  useEffect(() => {
    setDraft(sel ? JSON.parse(JSON.stringify(sel.definition)) : null);
    setTestResult(null); setMsg(null);
  }, [selId, profiles.length]);

  const caps = useMemo(() => {
    if (!draft) return null;
    const t = new Set([
      ...draft.mapping.filter((m: any) => m.target).map((m: any) => m.target),
      ...Object.keys(draft.constants ?? {}),
    ]);
    return { periode: draft.period?.type ?? "week", merk: t.has("merk"), artikel: t.has("artikel_ean"),
      winkel: t.has("winkel_id"), banner: t.has("banner"), land: t.has("land"),
      volume: t.has("volume"), omzet: t.has("omzet") };
  }, [draft]);

  const missing = caps ? [!caps.volume && "volume", !caps.omzet && "omzet"].filter(Boolean) as string[] : [];

  const publish = async (status: "live" | "test" | "concept") => {
    try {
      const r = await apiSend(`/parser/${sel.retailer_id}/profielen`, "POST", { definition: draft, status });
      setMsg(`Gepubliceerd als v${r.version} (${status}).`);
      await refresh();
    } catch (e: any) { setMsg(String(e.message ?? e)); }
  };

  const test = async (f: File | null) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    setTestResult(await apiSend(`/parser/${sel.retailer_id}/test`, "POST", fd));
  };

  if (!sel || !draft) {
    return (<>
      <h1>Parser — {ctx.card?.naam}</h1>
      <div className="card empty-card">
        <p className="sub">Nog geen profiel voor deze retailer.</p>
        <button className="btn" onClick={async () => {
          await apiSend(`/parser/${ctx.retailer}/profielen`, "POST", {
            status: "concept",
            definition: {
              detection: { filename_glob: "*.xlsx", sheet: null, header_row: 1, required_headers: [], filetype: "xlsx", csv_delimiter: null, decimal: "," },
              period: { type: "week", source_column: "", format: "yyyyww" },
              mapping: [], constants: {}, thresholds: { promo_price_drop: 0.05 },
            },
          });
          refresh();
        }}>Nieuw profiel</button>
      </div>
    </>);
  }

  const det = draft.detection;
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
        <div>
          <h1>Parser — {ctx.card?.naam}</h1>
          <p className="sub">Bronkolommen → canoniek model. Publiceren maakt een nieuwe versie; oude versies blijven leesbaar.</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn ghost" onClick={() => fileRef.current?.click()}>Testen op bestand</button>
          <input ref={fileRef} type="file" hidden accept=".xlsx,.csv"
            onChange={(e) => { test(e.target.files?.[0] ?? null); e.target.value = ""; }} />
          <button className="btn" disabled={missing.length > 0} title={missing.length ? `ontbreekt: ${missing.join(", ")}` : ""}
            onClick={() => publish("live")}>Profiel publiceren</button>
        </div>
      </div>
      {msg && <p className="sub" style={{ color: "var(--main)" }}>{msg}</p>}

      <div style={{ display: "grid", gridTemplateColumns: "230px 1fr", gap: 20, marginTop: 16, alignItems: "start" }}>
        <div className="card" style={{ padding: 12 }}>
          {profiles.map((p) => (
            <button key={p.id} className={`nav-item ${p.id === selId ? "active" : ""}`}
              style={{ color: "var(--main)", borderRadius: 6 }}
              onClick={() => { if (p.retailer_id !== ctx.retailer) ctx.go(p.retailer_id, "parser"); else setSelId(p.id); }}>
              <span className={`brand-dot ${p.status === "live" ? "dot-green" : p.status === "test" ? "dot-orange" : "dot-grey"}`} />
              {p.retailer_id} <span className="sub">v{p.version} · {p.definition.period?.type}</span>
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <div className="eyebrow">Profiel · versie {sel.version}</div>
              <span className={`tag ${sel.status === "live" ? "pos" : "accent"}`}>{sel.status}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, margin: "14px 0" }}>
              {[["Bestandstype", det.filetype], ["Bestandsnaam-patroon", det.filename_glob],
                ["Werkblad", det.sheet ?? "—"], ["Header-rij", det.header_row]].map(([l, v]) => (
                <div key={l as string}><div className="eyebrow" style={{ fontSize: 9 }}>{l}</div>
                  <div className="mono" style={{ marginTop: 4 }}>{String(v)}</div></div>
              ))}
            </div>
            <div>
              <span className="eyebrow" style={{ marginRight: 10 }}>Periodiciteit</span>
              <span className="seg">
                {["week", "maand"].map((t) => (
                  <button key={t} className={draft.period.type === t ? "on" : ""}
                    onClick={() => setDraft({ ...draft, period: { ...draft.period, type: t } })}>{t}</button>
                ))}
              </span>
              <span className="sub" style={{ marginLeft: 12 }}>
                bron: <span className="mono">{draft.period.source_column || "—"}</span> · formaat {draft.period.format}
              </span>
            </div>
          </div>

          <div className="card">
            <div className="eyebrow" style={{ marginBottom: 10 }}>Kolom-mapping</div>
            <table className="data" style={{ border: 0 }}>
              <thead><tr><th>Bronkolom</th><th>Canoniek veld</th><th>Niveau</th></tr></thead>
              <tbody>
                {draft.mapping.map((m: any, i: number) => (
                  <tr key={m.source}>
                    <td className="mono">{m.source}{m.note && <div className="sub">{m.note}</div>}</td>
                    <td>
                      <select className={`pill ${m.target ? "" : m.note ? "open" : "unused"}`}
                        value={m.target ?? ""}
                        onChange={(e) => {
                          const mapping = [...draft.mapping];
                          mapping[i] = { ...m, target: e.target.value || null };
                          setDraft({ ...draft, mapping });
                        }}>
                        <option value="">{m.note ? "KIES VELD" : "bewust ongebruikt"}</option>
                        {CANONICAL.filter((c) => c !== "periode").map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </td>
                    <td>{m.target
                      ? <span className="tag pos">GEMAPT</span>
                      : m.note ? <span className="tag accent">ONTBREEKT</span> : <span className="tag">ONGEBRUIKT</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.keys(draft.constants ?? {}).length > 0 && (
              <p className="sub" style={{ marginTop: 10 }}>
                Vaste waarden: {Object.entries(draft.constants).map(([k, v]) => `${k} = ${v}`).join(", ")}
              </p>
            )}
          </div>

          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <div className="card">
              <div className="eyebrow" style={{ marginBottom: 10 }}>Dit profiel levert</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <span className="chip static">{caps!.periode}</span>
                {(["merk", "artikel", "winkel", "banner", "land"] as const).map((c) => (
                  <span key={c} className={`chip static ${caps![c] ? "" : "off"}`}>{c}</span>
                ))}
              </div>
              {missing.length > 0 && <p className="sub" style={{ marginTop: 10 }}>
                Ontbreekt nog voor publicatie: <b>{missing.join(", ")}</b></p>}
            </div>
            <div className="card">
              <div className="eyebrow" style={{ marginBottom: 10 }}>Gevolgen voor analyses</div>
              {ANALYSES.map(([naam, f]) => {
                const level = missing.length ? "NA MAPPING" : f(caps);
                return (
                  <div key={naam} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderTop: "1px solid var(--quiet)" }}>
                    <span>{naam}</span>
                    <span className={`tag ${level === "VOLLEDIG" ? "pos" : level === "NIET BESCHIKBAAR" ? "neg" : ""}`}>{level}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {testResult && (
            <div className="card">
              <div className="eyebrow">Testresultaat</div>
              {testResult.ok ? (
                <p className="sub">✓ {testResult.rijen} rijen parsebaar · periodes {testResult.periodes.join(", ")}</p>
              ) : (
                <>
                  <p className="sub sig-red">{testResult.fout}</p>
                  <ul className="sub">{(testResult.rijen_fouten ?? []).map((e: any, i: number) => (
                    <li key={i}>rij {e.rij} · {e.veld}: {e.fout}</li>))}</ul>
                </>
              )}
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn ghost" onClick={() => publish("concept")}>Opslaan als concept</button>
            <button className="btn ghost" onClick={() => publish("test")}>Publiceren als test</button>
          </div>
        </div>
      </div>
    </>
  );
}
