import { useEffect, useState } from "react";
import { apiGet, fmtEur, fmtNum, BRAND_COLORS } from "../api";
import { ShellCtx } from "../App";
import { DeltaTag, EmptyProfileCard, LevelStrip, TrendChart } from "../components/shared";

function KpiCard({ label, tag, tagAccent, value, sub, breakdown, isEuro }: {
  label: string; tag: string; tagAccent?: boolean; value: string; sub?: string;
  breakdown?: { merk: string; waarde: number }[]; isEuro?: boolean;
}) {
  const max = Math.max(1, ...(breakdown ?? []).map((b) => b.waarde));
  return (
    <div className="card">
      <div className="kpi-label">{label}<span className={`tag ${tagAccent ? "accent" : ""}`}>{tag}</span></div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
      {breakdown?.map((b) => (
        <div key={b.merk} style={{ marginTop: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
            <span>{b.merk}</span><span>{isEuro ? fmtEur(b.waarde) : fmtNum(b.waarde)}</span>
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(b.waarde / max) * 100}%`, background: BRAND_COLORS[b.merk] ?? "var(--main)" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function MultiChips({ all, sel, onChange }: { all: string[]; sel: string[]; onChange: (v: string[]) => void }) {
  return (
    <span className="chips" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      {all.map((v) => (
        <button key={v} className={`chip ${sel.includes(v) ? "" : "off"}`}
          onClick={() => onChange(sel.includes(v) ? sel.filter((x) => x !== v) : [...sel, v])}>{v}</button>
      ))}
    </span>
  );
}

export default function Dashboard({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [merk, setMerk] = useState<string[]>([]);
  const [land, setLand] = useState<string[]>([]);
  const [banner, setBanner] = useState<string[]>([]);
  const [metric, setMetric] = useState<"omzet" | "volume" | "per_winkel">("omzet");

  useEffect(() => {
    const q = new URLSearchParams();
    if (merk.length) q.set("merk", merk.join(","));
    if (land.length) q.set("land", land.join(","));
    if (banner.length) q.set("banner", banner.join(","));
    apiGet(`/${ctx.retailer}/dashboard?${q}`).then(setData);
  }, [ctx.retailer, merk, land, banner]);

  if (!data) return <p className="sub">Laden…</p>;
  if (!data.available) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const pWord = data.periode_type === "maand" ? "Maand" : "Week";
  if (data.empty) {
    return (<>
      <h1>Dashboard — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer} />
      <div className="card empty-card"><p className="sub">Nog geen data geïmporteerd voor deze retailer.</p></div>
    </>);
  }

  const k = data.kpi, y = data.ytd;
  const filters = data.filters;
  return (
    <>
      <h1>Dashboard — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer}
        uitleg={data.labels.includes("OP MAANDNIVEAU") ? "Deze retailer levert per maand; alle analyses rekenen met maanden." : undefined} />

      <div style={{ display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap", margin: "16px 0 4px" }}>
        {filters.merk.length > 0 && (<span><span className="eyebrow">Merk </span><MultiChips all={filters.merk} sel={merk} onChange={setMerk} /></span>)}
        {filters.land.length > 0 && (<span><span className="eyebrow">Land </span><MultiChips all={filters.land} sel={land} onChange={setLand} /></span>)}
        {filters.banner.length > 0 && (<span><span className="eyebrow">Banner </span><MultiChips all={filters.banner} sel={banner} onChange={setBanner} /></span>)}
        <span className="sub" style={{ marginLeft: "auto" }}>
          {(merk.length || filters.merk.length)} van {filters.merk.length} merken
        </span>
      </div>

      <h2>Meest recente {pWord.toLowerCase()} {data.laatste_periode}</h2>
      <div className="grid kpi">
        <KpiCard label="Omzet" tag={pWord.toUpperCase()} isEuro
          value={fmtEur(k.omzet.waarde)} breakdown={k.omzet.breakdown} />
        <KpiCard label="Volume" tag={pWord.toUpperCase()}
          value={fmtNum(k.volume.waarde)} breakdown={k.volume.breakdown} />
        <KpiCard label="Omzet per winkel" tag={k.omzet_per_winkel.schatting ? "SCHATTING" : "WINKEL"}
          tagAccent={k.omzet_per_winkel.schatting}
          value={fmtEur(k.omzet_per_winkel.waarde)}
          sub={k.omzet_per_winkel.winkels ? `${k.omzet_per_winkel.winkels} winkels` : "Geen winkelaantal ingesteld"} />
      </div>

      <hr className="hairline" />
      <h2>YTD {y.jaar} t/m {pWord.toLowerCase()} {y.tot_periode} vs {y.jaar - 1}</h2>
      <div className="grid kpi">
        <div className="card">
          <div className="kpi-label">Omzet YTD<DeltaTag pct={y.omzet.delta_pct} /></div>
          <div className="kpi-value">{fmtEur(y.omzet.nu)}</div>
          <div className="kpi-sub">{y.jaar - 1}: {fmtEur(y.omzet.vorig)}</div>
        </div>
        <div className="card">
          <div className="kpi-label">Volume YTD<DeltaTag pct={y.volume.delta_pct} /></div>
          <div className="kpi-value">{fmtNum(y.volume.nu)}</div>
          <div className="kpi-sub">{y.jaar - 1}: {fmtNum(y.volume.vorig)}</div>
        </div>
        <div className="card">
          <div className="kpi-label">Omzet / winkel YTD
            <span style={{ display: "inline-flex", gap: 6 }}>
              {y.omzet_per_winkel.schatting && <span className="tag accent">SCHATTING</span>}
              <DeltaTag pct={y.omzet_per_winkel.delta_pct} />
            </span>
          </div>
          <div className="kpi-value">{fmtEur(y.omzet_per_winkel.nu)}</div>
          <div className="kpi-sub">{y.jaar - 1}: {fmtEur(y.omzet_per_winkel.vorig)}</div>
        </div>
      </div>

      <h2>
        {metric === "per_winkel" ? "Omzet per winkel" : metric} per {pWord.toLowerCase()}, jaar op jaar
      </h2>
      <div className="seg" style={{ marginBottom: 14 }}>
        <button className={metric === "omzet" ? "on" : ""} onClick={() => setMetric("omzet")}>Omzet</button>
        <button className={metric === "volume" ? "on" : ""} onClick={() => setMetric("volume")}>Volume</button>
        <button className={metric === "per_winkel" ? "on" : ""} disabled={!data.trend.series.per_winkel}
          onClick={() => setMetric("per_winkel")}>Per winkel</button>
      </div>
      <div className="card">
        <TrendChart series={data.trend.series[metric] ?? {}} years={data.trend.jaren}
          isEuro={metric !== "volume"} periodWord={pWord} />
      </div>
    </>
  );
}
