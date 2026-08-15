import { useEffect, useState } from "react";
import { fmtEur, fmtNum, BRAND_COLORS } from "../api";
import { ShellCtx } from "../App";
import { DeltaTag, EmptyProfileCard, LevelStrip, LoadState, TrendChart, useApi } from "../components/shared";

function KpiCard({ label, tag, tagAccent, value, sub, breakdown, isEuro }: {
  label: string; tag: string; tagAccent?: boolean; value: string; sub?: string;
  breakdown?: { merk: string; waarde: number; winkels?: number }[]; isEuro?: boolean;
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
            <span>{b.merk}{b.winkels ? ` · ${b.winkels} winkels` : ""}</span>
            <span>{isEuro ? fmtEur(b.waarde) : fmtNum(b.waarde)}</span>
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(b.waarde / max) * 100}%`, background: BRAND_COLORS[b.merk] ?? "var(--main)" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

const MAANDEN = ["", "jan", "feb", "mrt", "apr", "mei", "jun",
  "jul", "aug", "sep", "okt", "nov", "dec"];

/** Winkels die dit jaar stilgevallen zijn, en winkels die erbij kwamen. */
function Winkelanalyse({ w, pWord }: { w: any; pWord: string }) {
  const naam = (n: number | null) =>
    n == null ? "—" : pWord === "Maand" ? MAANDEN[n] ?? String(n) : `wk ${n}`;
  return (
    <>
      <hr className="hairline" />
      <h2>Winkelanalyse {w.jaar}</h2>
      <p className="sub" style={{ marginTop: -6 }}>
        Vergeleken met {w.jaar - 1}, t/m {pWord.toLowerCase()} {naam(w.laatste_maand)}.
        Een winkel telt per merk: een filiaal kan het ene merk laten vallen en het andere houden.
      </p>

      <div className="level-strip" style={{ borderLeft: "3px solid var(--neg)", marginTop: 14 }}>
        <span><b>Actiepunt.</b> {w.actiepunt}</span>
      </div>

      {/* Geen haakjes in koppen: het displayfont vervangt ze door een ornament. */}
      <h3 style={{ marginTop: 18 }}>
        Gestopte winkels · {w.gestopt.length} — gemiste omzet {fmtEur(w.gemiste_omzet)}
      </h3>
      <table className="data">
        <thead><tr>
          <th>Winkel</th><th>Merk</th><th>Laatste omzet</th><th>Zonder omzet</th>
          <th style={{ textAlign: "right" }}>Omzet {w.jaar}</th>
          <th style={{ textAlign: "right" }}>Omzet {w.jaar - 1}</th>
        </tr></thead>
        <tbody>
          {w.gestopt.map((g: any) => (
            <tr key={`${g.winkel_id}-${g.merk}`}>
              <td>{g.winkel_naam ?? g.winkel_id}</td>
              <td>{g.merk}</td>
              <td>{g.laatste_maand == null ? `niets in ${w.jaar}` : naam(g.laatste_maand)}</td>
              <td>{g.maanden_zonder_omzet} {pWord.toLowerCase()}{g.maanden_zonder_omzet === 1 ? "" : "en"}</td>
              <td style={{ textAlign: "right" }}>{fmtEur(g.omzet_dit_jaar)}</td>
              <td style={{ textAlign: "right" }}>{fmtEur(g.omzet_vorig_jaar)}</td>
            </tr>
          ))}
          {!w.gestopt.length && (
            <tr><td colSpan={6} className="sub">Geen winkels stilgevallen — elke winkel draait nog omzet.</td></tr>
          )}
        </tbody>
      </table>

      <h3 style={{ marginTop: 22 }}>Nieuwe winkels · {w.toegevoegd.length}</h3>
      <table className="data">
        <thead><tr>
          <th>Winkel</th><th>Merk</th><th>Eerste omzet</th>
          <th style={{ textAlign: "right" }}>Omzet {w.jaar}</th>
        </tr></thead>
        <tbody>
          {w.toegevoegd.map((a: any) => (
            <tr key={`${a.winkel_id}-${a.merk}`}>
              <td>{a.winkel_naam ?? a.winkel_id}</td>
              <td>{a.merk}</td>
              <td>{naam(a.eerste_maand)}</td>
              <td style={{ textAlign: "right" }}>{fmtEur(a.omzet_dit_jaar)}</td>
            </tr>
          ))}
          {!w.toegevoegd.length && (
            <tr><td colSpan={4} className="sub">Geen winkels erbij dit jaar.</td></tr>
          )}
        </tbody>
      </table>
    </>
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
  const [merk, setMerk] = useState<string[]>([]);
  const [land, setLand] = useState<string[]>([]);
  const [banner, setBanner] = useState<string[]>([]);
  const [metric, setMetric] = useState<"omzet" | "volume" | "per_winkel">("omzet");

  // Filters horen bij één retailer: bij het wisselen van tab zou een merk
  // dat de nieuwe retailer niet voert anders een leeg dashboard opleveren.
  useEffect(() => { setMerk([]); setLand([]); setBanner([]); }, [ctx.retailer]);

  const q = new URLSearchParams();
  if (merk.length) q.set("merk", merk.join(","));
  if (land.length) q.set("land", land.join(","));
  if (banner.length) q.set("banner", banner.join(","));
  const { data, error, reload } = useApi(`/${ctx.retailer}/dashboard?${q}`);

  if (!data) return <LoadState error={error} reload={reload} />;
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
  const hasVolume = data.capabilities?.volume !== false;
  const effMetric = !hasVolume && metric === "volume" ? "omzet" : metric;
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
        {hasVolume && <KpiCard label="Volume" tag={pWord.toUpperCase()}
          value={fmtNum(k.volume.waarde)} breakdown={k.volume.breakdown} />}
        <KpiCard label="Omzet per winkel" tag={k.omzet_per_winkel.schatting ? "SCHATTING" : "WINKEL"}
          tagAccent={k.omzet_per_winkel.schatting}
          value={fmtEur(k.omzet_per_winkel.waarde)} isEuro
          breakdown={k.omzet_per_winkel.breakdown}
          sub={k.omzet_per_winkel.winkels
            ? `${k.omzet_per_winkel.winkels} winkels met omzet in ${y.jaar}`
            : "Geen winkelaantal ingesteld"} />
      </div>

      <hr className="hairline" />
      <h2>YTD {y.jaar} t/m {pWord.toLowerCase()} {y.tot_periode} vs {y.jaar - 1}</h2>
      <div className="grid kpi">
        <div className="card">
          <div className="kpi-label">Omzet YTD<DeltaTag pct={y.omzet.delta_pct} /></div>
          <div className="kpi-value">{fmtEur(y.omzet.nu)}</div>
          <div className="kpi-sub">{y.jaar - 1}: {fmtEur(y.omzet.vorig)}</div>
        </div>
        {hasVolume && <div className="card">
          <div className="kpi-label">Volume YTD<DeltaTag pct={y.volume.delta_pct} /></div>
          <div className="kpi-value">{fmtNum(y.volume.nu)}</div>
          <div className="kpi-sub">{y.jaar - 1}: {fmtNum(y.volume.vorig)}</div>
        </div>}
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
        {effMetric === "per_winkel" ? "Omzet per winkel" : effMetric} per {pWord.toLowerCase()}, jaar op jaar
      </h2>
      <div className="seg" style={{ marginBottom: 14 }}>
        <button className={effMetric === "omzet" ? "on" : ""} onClick={() => setMetric("omzet")}>Omzet</button>
        <button className={effMetric === "volume" ? "on" : ""} disabled={!hasVolume}
          title={hasVolume ? undefined : "Deze retailer levert geen volumedata"}
          onClick={() => setMetric("volume")}>Volume</button>
        <button className={effMetric === "per_winkel" ? "on" : ""} disabled={!data.trend.series.per_winkel}
          onClick={() => setMetric("per_winkel")}>Per winkel</button>
      </div>
      <div className="card">
        <TrendChart series={data.trend.series[effMetric] ?? {}} years={data.trend.jaren}
          isEuro={effMetric !== "volume"} periodWord={pWord} />
      </div>

      {data.winkelanalyse?.beschikbaar && <Winkelanalyse w={data.winkelanalyse} pWord={pWord} />}
    </>
  );
}
