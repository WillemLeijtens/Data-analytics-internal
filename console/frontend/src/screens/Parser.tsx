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

  const [voorstel, setVoorstel] = useState<any | null>(null);
  const refresh = () => apiGet("/parser/profielen").then((ps) => {
    setProfiles(ps);
    const mine = ps.filter((p: any) => p.retailer_id === ctx.retailer);
    if (mine.length && (selId == null || !ps.some((p: any) => p.id === selId))) setSelId(mine[0].id);
  }).catch((e) => setMsg(`Profielen laden mislukt: ${e?.message ?? e}`));
  useEffect(() => {
    refresh(); setDraft(null); setTestResult(null);
    apiGet("/parser/voorstel").then(setVoorstel).catch(() => setVoorstel(null));
  }, [ctx.retailer]);

  const adoptVoorstel = () => {
    // Neem detectie + kolommen van de laatste onbekende import over,
    // maar bewaar wat de gebruiker al instelde (periodiciteit e.d.).
    if (!voorstel?.beschikbaar) return;
    const v = voorstel.definition;
    setDraft((d: any) => ({
      ...(d ?? {}),
      detection: v.detection,
      mapping: v.mapping,
      period: d?.period?.source_column ? d.period : v.period,
      constants: d?.constants ?? v.constants,
      thresholds: d?.thresholds ?? v.thresholds,
    }));
  };

  const sel = profiles.find((p) => p.id === selId) ?? null;
  useEffect(() => {
    setDraft(sel ? JSON.parse(JSON.stringify(sel.definition)) : null);
    setTestResult(null); setMsg(null);
  }, [selId, profiles.length]);

  const isBuiltin = !!draft?.builtin;
  const caps = useMemo(() => {
    if (!draft) return null;
    if (draft.builtin === "kruidvat_dwh")
      return { periode: "week", merk: true, artikel: true, winkel: false,
        banner: true, land: true, volume: true, omzet: true };
    const t = new Set([
      ...draft.mapping.filter((m: any) => m.target).map((m: any) => m.target),
      ...Object.keys(draft.constants ?? {}),
    ]);
    return { periode: draft.period?.type ?? "week", merk: t.has("merk"), artikel: t.has("artikel_ean"),
      winkel: t.has("winkel_id"), banner: t.has("banner"), land: t.has("land"),
      volume: t.has("volume"), omzet: t.has("omzet") };
  }, [draft]);

  const missing = !caps || isBuiltin ? [] : [
    !caps.volume && "volume",
    !caps.omzet && "omzet",
    !draft?.period?.source_column && "periodekolom",
  ].filter(Boolean) as string[];

  const publish = async (status: "live" | "test" | "concept") => {
    try {
      const r = await apiSend(`/parser/${sel.retailer_id}/profielen`, "POST", { definition: draft, status });
      setMsg(`Gepubliceerd als v${r.version} (${status}).` +
        (status !== "concept" ? " Upload het bestand nu opnieuw via Import — dan wordt het herkend en ingelezen." : ""));
      await refresh();
    } catch (e: any) { setMsg(String(e.message ?? e)); }
  };

  const test = async (f: File | null) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    // Test wat er op het scherm staat, inclusief nog niet opgeslagen mapping.
    fd.append("definition", JSON.stringify(draft));
    try {
      setTestResult(await apiSend(`/parser/${sel.retailer_id}/test`, "POST", fd));
    } catch (e: any) {
      setMsg(`Testen mislukt: ${e?.message ?? e}`);
    }
  };

  if (!sel || !draft) {
    return (<>
      <h1>Parser — {ctx.card?.naam}</h1>
      <div className="card empty-card">
        <p className="sub">Nog geen profiel voor deze retailer.</p>
        {voorstel?.beschikbaar && (
          <p className="sub">Laatst onbekende import: <span className="mono">{voorstel.filename}</span> —
            de kolommen daaruit worden alvast ingevuld.</p>
        )}
        <button className="btn" onClick={async () => {
          await apiSend(`/parser/${ctx.retailer}/profielen`, "POST", {
            status: "concept",
            definition: voorstel?.beschikbaar ? voorstel.definition : {
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
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <span className="eyebrow">Periodiciteit</span>
              <span className="seg">
                {["week", "maand"].map((t) => (
                  <button key={t} className={draft.period.type === t ? "on" : ""}
                    onClick={() => setDraft({
                      ...draft,
                      period: {
                        ...draft.period, type: t,
                        // formaat mee laten schakelen als het nog op het
                        // andere graan staat
                        format: t === "maand" && ["yyyyww", "yyyy-Www"].includes(draft.period.format) ? "mm-yyyy"
                          : t === "week" && ["mm-yyyy", "yyyy-mm"].includes(draft.period.format) ? "yyyyww"
                          : draft.period.format,
                      },
                    })}>{t}</button>
                ))}
              </span>
              <span className="sub">
                bron: <span className="mono">{draft.period.source_column || "— kies 'periode' in de mapping"}</span>
              </span>
              <span className="sub">formaat:</span>
              <select className="pill" value={draft.period.format}
                onChange={(e) => setDraft({ ...draft, period: { ...draft.period, format: e.target.value } })}>
                {(draft.period.type === "week" ? ["yyyyww", "yyyy-Www"] : ["mm-yyyy", "yyyy-mm"]).map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
              <span className="sub">decimaal:</span>
              <select className="pill" value={det.decimal ?? ","}
                onChange={(e) => setDraft({ ...draft, detection: { ...det, decimal: e.target.value } })}>
                <option value=",">komma (1.234,56)</option>
                <option value=".">punt (1,234.56)</option>
              </select>
            </div>
          </div>

          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div className="eyebrow">Kolom-mapping</div>
              {voorstel?.beschikbaar && draft.mapping.length === 0 && (
                <button className="btn ghost" onClick={adoptVoorstel}>
                  Kolommen overnemen uit {voorstel.filename}
                </button>
              )}
            </div>
            {isBuiltin && (
              <p className="sub">Dit profiel gebruikt een <b>ingebouwde parser</b> voor het echte
                DWH-exportformaat (metadatablok + weekkolommen naast elkaar). Kolommen worden
                automatisch herkend — een mapping is niet nodig.</p>
            )}
            {!isBuiltin && draft.mapping.length === 0 && (
              <p className="sub">Nog geen kolommen. Upload het bestand eerst via <b>Import</b> —
                een onbekend bestand krijgt daar de status PROFIEL NODIG en zijn kolommen
                verschijnen hier vanzelf.</p>
            )}
            <table className="data" style={{ border: 0 }}>
              <thead><tr><th>Bronkolom</th><th>Canoniek veld</th><th>Voorbeeldwaarde</th><th>Niveau</th></tr></thead>
              <tbody>
                {draft.mapping.map((m: any, i: number) => {
                  const isPeriod = draft.period?.source_column === m.source;
                  const value = isPeriod ? "periode" : m.target ?? "";
                  return (
                    <tr key={m.source}>
                      <td className="mono">{m.source}{m.note && !isPeriod && !m.target && <div className="sub">{m.note}</div>}</td>
                      <td>
                        <select className={`pill ${value ? "" : m.note ? "open" : "unused"}`}
                          value={value}
                          onChange={(e) => {
                            const v = e.target.value;
                            const mapping = [...draft.mapping];
                            let period = { ...draft.period };
                            if (isPeriod && v !== "periode") period = { ...period, source_column: "" };
                            if (v === "periode") {
                              period = { ...period, source_column: m.source };
                              mapping[i] = { ...m, target: null };
                            } else {
                              mapping[i] = { ...m, target: v || null };
                            }
                            setDraft({ ...draft, mapping, period });
                          }}>
                          <option value="">{m.note ? "KIES VELD" : "bewust ongebruikt"}</option>
                          <option value="periode">periode</option>
                          {CANONICAL.filter((c) => c !== "periode").map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </td>
                      <td className="mono sub">{m.voorbeeld ?? ""}</td>
                      <td>{isPeriod
                        ? <span className="tag pos">PERIODE</span>
                        : m.target
                          ? <span className="tag pos">GEMAPT</span>
                          : m.note ? <span className="tag accent">ONTBREEKT</span> : <span className="tag">ONGEBRUIKT</span>}
                      </td>
                    </tr>
                  );
                })}
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
