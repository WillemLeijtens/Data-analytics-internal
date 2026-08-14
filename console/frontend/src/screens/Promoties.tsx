import { useEffect, useMemo, useState } from "react";
import { apiGet, apiSend, fmtEur, YEAR_COLORS } from "../api";
import { ShellCtx } from "../App";
import { BrandDot, EmptyProfileCard, LevelStrip, LoadState } from "../components/shared";

export default function Promoties({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [jaar, setJaar] = useState<string>("ALLE");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/promoties`).then((d) => {
    setData(d);
    setError(null);
    const init: Record<string, boolean> = {};
    for (const s of d.suggesties ?? []) init[key(s)] = s.bevestigd;
    setChecked(init);
  }).catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { setData(null); load(); }, [ctx.retailer]);

  const key = (s: any) => `${s.merk}|${s.land}|${s.banner ?? ""}|${s.periode}`;

  const uplift = useMemo(() => {
    if (!data) return [];
    return (data.uplift as any[]).filter((u) => jaar === "ALLE" || String(u.jaar) === jaar);
  }, [data, jaar]);

  if (!data) return <LoadState error={error} reload={load} />;
  if (!data.available) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const pw = data.periode_type === "maand" ? "Maand" : "Week";
  const nConfirmed = Object.values(checked).filter(Boolean).length;
  const maxAbs = Math.max(1, ...uplift.map((u) => Math.abs(u.uplift_pct ?? 0)));
  const avg = uplift.length ? uplift.reduce((a, u) => a + (u.uplift_pct ?? 0), 0) / uplift.length : null;

  const save = async () => {
    const bevestigd = (data.suggesties as any[])
      .filter((s) => checked[key(s)])
      .map((s) => ({ merk: s.merk, land: s.land, banner: s.banner, periode: s.periode }));
    try {
      await apiSend(`/${ctx.retailer}/promoties`, "PUT", { bevestigd });
      setSaved(`${bevestigd.length} ${pw.toLowerCase()}(en) bevestigd`);
      load();
    } catch (e: any) {
      setSaved(`Opslaan mislukt: ${e?.message ?? e}`);
    }
  };

  return (
    <>
      <h1>Promoties — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer}
        uitleg={data.periode_type === "maand" ? `Drempel ${Math.round(data.drempel * 100)}% op maandniveau.` : undefined} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 20, alignItems: "start" }}>
        <div>
          <table className="data">
            <thead><tr>
              <th>Merk</th><th>Land</th>
              {data.capabilities.banner && <th>Banner</th>}
              <th>{pw}</th><th>Suggestie</th><th>Promotie</th>
            </tr></thead>
            <tbody>
              {data.suggesties.map((s: any) => (
                <tr key={key(s)}>
                  <td><BrandDot merk={s.merk} />{s.merk}</td>
                  <td>{s.land}</td>
                  {data.capabilities.banner && <td>{s.banner ?? "—"}</td>}
                  <td>{s.periode}</td>
                  <td style={{ fontWeight: 500 }}>{s.suggestie ?? "—"}</td>
                  <td>
                    <input type="checkbox" className="checkbox" checked={!!checked[key(s)]}
                      onChange={(e) => setChecked({ ...checked, [key(s)]: e.target.checked })} />
                  </td>
                </tr>
              ))}
              {!data.suggesties.length && (
                <tr><td colSpan={6} className="sub">Geen prijsafwijkingen onder de mediaan gevonden.</td></tr>
              )}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 12 }}>
            <button className="btn" onClick={save}>Opslaan</button>
            <span className="sub">{saved ?? `${nConfirmed} ${pw.toLowerCase()}(en) aangevinkt`}</span>
          </div>

          <h2>Omzeteffect per promotie</h2>
          <div className="card">
            <div className="seg" style={{ marginBottom: 12 }}>
              {["ALLE", "2024", "2025", "2026"].map((j) => (
                <button key={j} className={jaar === j ? "on" : ""} onClick={() => setJaar(j)}>{j}</button>
              ))}
            </div>
            {uplift.length ? (
              <>
                <div className="sub" style={{ marginBottom: 10 }}>
                  {uplift.length} promoties · gem.{" "}
                  <b className={avg != null && avg >= 0 ? "sig-green" : "sig-red"}>
                    {avg != null ? `${avg >= 0 ? "+" : ""}${avg.toFixed(1)}%` : "—"}
                  </b>{" "}
                  · beste <b className="sig-green">+{Math.max(...uplift.map((u) => u.uplift_pct ?? 0)).toFixed(1)}%</b>{" "}
                  · zwakste <b className="sig-red">{Math.min(...uplift.map((u) => u.uplift_pct ?? 0)).toFixed(1)}%</b>
                </div>
                {uplift.map((u) => (
                  <div key={`${u.merk}${u.periode}`} style={{ display: "grid", gridTemplateColumns: "170px 1fr 70px", gap: 10, alignItems: "center", margin: "5px 0" }}>
                    <span style={{ fontSize: 11.5 }}>{u.merk} · {u.periode}</span>
                    <div className="bar-track" style={{ height: 8 }}>
                      <div className="bar-fill" style={{
                        height: 8,
                        width: `${(Math.abs(u.uplift_pct ?? 0) / maxAbs) * 100}%`,
                        background: (u.uplift_pct ?? 0) < 0 ? "oklch(0.55 0.18 27)"
                          : YEAR_COLORS[2026 - u.jaar] ?? "#BAC3C8",
                      }} />
                    </div>
                    <b style={{ fontSize: 12 }} className={(u.uplift_pct ?? 0) >= 0 ? "" : "sig-red"}>
                      {(u.uplift_pct ?? 0) >= 0 ? "+" : ""}{u.uplift_pct}%
                    </b>
                  </div>
                ))}
              </>
            ) : <p className="sub">Nog geen bevestigde promoties{jaar !== "ALLE" ? ` in ${jaar}` : ""}.</p>}
          </div>
        </div>

        <div className="card">
          <div className="eyebrow">Hoe de suggestie werkt</div>
          <p className="sub">De stukprijs per {pw.toLowerCase()} is omzet gedeeld door volume, per merk
            {data.capabilities.banner ? " per banner" : " per land"}.</p>
          <p className="sub">Ligt de stukprijs {Math.round(data.drempel * 100)}% of meer onder de mediaan van de feed,
            dan verschijnt een suggestie ("afgeprijsd, -x%"). Er wordt nooit automatisch aangevinkt — jij bevestigt.</p>
          <p className="sub">De uplift vergelijkt de omzet in de actieperiode met het gemiddelde van de periodes
            zónder actie. Bevestigde actieperiodes blijven buiten die basislijn.</p>
        </div>
      </div>
    </>
  );
}
