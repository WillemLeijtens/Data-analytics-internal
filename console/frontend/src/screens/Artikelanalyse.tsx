import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, fmtEur, fmtNum } from "../api";
import { ShellCtx } from "../App";
import { BrandDot, DeltaTag, EmptyProfileCard, LevelStrip, Sparkline, TrendChart } from "../components/shared";

export default function Artikelanalyse({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [metric, setMetric] = useState<"volume" | "omzet">("omzet");
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { apiGet(`/${ctx.retailer}/artikelen`).then(setData); }, [ctx.retailer]);

  if (!data) return <p className="sub">Laden…</p>;
  if (!data.available && data.reason === "PARSER PROFIEL ONTBREEKT")
    return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;
  if (!data.available)
    return (
      <div className="card empty-card">
        <div className="eyebrow">Gegevens niet beschikbaar</div>
        <h2 style={{ marginTop: 10 }}>Geen artikelniveau voor deze retailer</h2>
        <p className="sub">Analyses staan op merkniveau ({data.labels?.join(", ")}).
          {" "}<Link to={`/${ctx.retailer}/parser`}>Bekijk het profiel</Link>.</p>
      </div>
    );

  const isEuro = metric === "omzet";
  const pWord = data.periode_type === "maand" ? "Maand" : "Week";
  const chosen = data.artikelen.find((a: any) => a.ean === sel);
  const fmt = (v: number) => (isEuro ? fmtEur(v) : fmtNum(v));
  const toSeries = (spark: any, key: string) =>
    Object.fromEntries(Object.entries(spark).map(([p, v]: any) => [p, v[key]]));

  return (
    <>
      <h1>Artikelanalyse — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Sellout per artikel</h2>
        <div className="seg">
          <button className={metric === "volume" ? "on" : ""} onClick={() => setMetric("volume")}>Volume</button>
          <button className={metric === "omzet" ? "on" : ""} onClick={() => setMetric("omzet")}>Omzet</button>
        </div>
      </div>
      <table className="data">
        <thead><tr>
          <th>Artikel</th><th>Merk</th><th>YTD vs LYTD</th><th></th>
          <th>Laatste {pWord.toLowerCase()}</th><th>Totaal YTD</th>
        </tr></thead>
        <tbody>
          {data.artikelen.map((a: any) => (
            <tr key={a.ean} className={`click ${sel === a.ean ? "selected" : ""}`} onClick={() => setSel(a.ean)}>
              <td>{a.naam}<br /><span className="mono sub">{a.ean}</span></td>
              <td><BrandDot merk={a.merk} />{a.merk}</td>
              <td>
                <Sparkline ytd={toSeries(a.sparkline.ytd, metric)} lytd={toSeries(a.sparkline.lytd, metric)}
                  isEuro={isEuro} periodWord={pWord} />
              </td>
              <td><DeltaTag pct={a.ytd_delta_pct} /></td>
              <td>{fmt(a.laatste_periode[metric])}</td>
              <td>{fmt(a.totaal_ytd[metric])}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {chosen && (
        <div className="card" style={{ marginTop: 20 }}>
          <div className="eyebrow">Detail</div>
          <h3 style={{ margin: "6px 0 14px" }}>{chosen.naam} <span className="mono sub">{chosen.ean}</span></h3>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            {(["volume", "omzet"] as const).map((m) => (
              <div key={m}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>{m} per {pWord.toLowerCase()}, jaar op jaar</div>
                <TrendChart
                  series={{ 2025: toSeries(chosen.sparkline.lytd, m), 2026: toSeries(chosen.sparkline.ytd, m) } as any}
                  years={[2025, 2026]} isEuro={m === "omzet"} periodWord={pWord} />
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
