import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmtEur, fmtNum } from "../api";
import { ShellCtx } from "../App";
import { BrandDot, DeltaTag, EmptyProfileCard, LevelStrip, LoadState, MultiChips, Sparkline, TrendChart, useApi } from "../components/shared";

/** Statusmarkering per artikel: nieuw in het schap, eruit, of twijfel. */
function StatusBadge({ status, reden }: { status: string | null; reden: string | null }) {
  if (!status) return null;
  const stijl: Record<string, { tekst: string; kleur: string; rand: string }> = {
    nieuw: { tekst: "NIEUW", kleur: "var(--pos)", rand: "var(--pos)" },
    delisted: { tekst: "DELISTED", kleur: "var(--neg)", rand: "var(--neg)" },
    "delisted?": { tekst: "DELISTED?", kleur: "#B4690E", rand: "#B4690E" },
  };
  const s = stijl[status];
  if (!s) return null;
  return (
    <span title={reden ?? undefined}
      style={{
        display: "inline-block", fontSize: 9.5, fontWeight: 700, letterSpacing: "0.1em",
        padding: "1px 6px", marginBottom: 3, borderRadius: 3,
        color: s.kleur, border: `1px solid ${s.rand}`,
      }}>{s.tekst}</span>
  );
}

export default function Artikelanalyse({ ctx }: { ctx: ShellCtx }) {
  const [metric, setMetric] = useState<"volume" | "omzet">("omzet");
  const [sel, setSel] = useState<string | null>(null);
  const [merk, setMerk] = useState<string[]>([]);
  const [alleenStatus, setAlleenStatus] = useState(false);

  // Filter hoort bij één retailer: bij tabwissel opnieuw beginnen, anders
  // levert een merk dat de nieuwe retailer niet voert een leeg scherm.
  useEffect(() => { setMerk([]); setSel(null); }, [ctx.retailer]);

  const q = merk.length ? `?merk=${encodeURIComponent(merk.join(","))}` : "";
  const { data, error, reload } = useApi(`/${ctx.retailer}/artikelen${q}`);

  if (!data) return <LoadState error={error} reload={reload} />;
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
  const gemarkeerd = data.artikelen.filter((a: any) => a.status);
  const zichtbaar = alleenStatus ? gemarkeerd : data.artikelen;
  const chosen = zichtbaar.find((a: any) => a.ean === sel);
  const fmt = (v: number) => (isEuro ? fmtEur(v) : fmtNum(v));
  const toSeries = (spark: any, key: string) =>
    Object.fromEntries(Object.entries(spark).map(([p, v]: any) => [p, v[key]]));

  return (
    <>
      <h1>Artikelanalyse — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer} />
      {data.filters?.merk?.length > 0 && (
        <div style={{ display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap", margin: "16px 0 4px" }}>
          <span><span className="eyebrow">Merk </span>
            <MultiChips all={data.filters.merk} sel={merk} onChange={setMerk} /></span>
          {gemarkeerd.length > 0 && (
            <button className={`chip ${alleenStatus ? "" : "off"}`}
              aria-pressed={alleenStatus}
              title="Toon alleen nieuwe, gestopte en twijfelgevallen"
              onClick={() => setAlleenStatus((v) => !v)}>
              ⚑ {gemarkeerd.length} gemarkeerd
            </button>
          )}
          <span className="sub" style={{ marginLeft: "auto" }}>
            {zichtbaar.length} artikel{zichtbaar.length === 1 ? "" : "en"}
            {(merk.length > 0 || alleenStatus) && <> · <a style={{ cursor: "pointer" }}
              onClick={() => { setMerk([]); setAlleenStatus(false); }}>filter wissen</a></>}
          </span>
        </div>
      )}
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
          {zichtbaar.map((a: any) => (
            <tr key={a.ean} className={`click ${sel === a.ean ? "selected" : ""}`} onClick={() => setSel(a.ean)}>
              <td>
                {a.status && <><StatusBadge status={a.status} reden={a.status_reden} /><br /></>}
                {a.naam}<br /><span className="mono sub">{a.ean}</span>
              </td>
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
                  series={{ [data.jaar - 1]: toSeries(chosen.sparkline.lytd, m),
                            [data.jaar]: toSeries(chosen.sparkline.ytd, m) } as any}
                  years={[data.jaar - 1, data.jaar]} isEuro={m === "omzet"} periodWord={pWord} />
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
