import { Link } from "react-router-dom";
import { ShellCtx } from "../App";
import { BrandDot, EmptyProfileCard, LevelStrip, LoadState, useApi } from "../components/shared";

function Warn() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="oklch(0.45 0.14 27)"
      strokeWidth="2" style={{ verticalAlign: "-2px", marginRight: 5 }}>
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <path d="M12 9v4" /><path d="M12 17h.01" />
    </svg>
  );
}

export default function Assortiment({ ctx }: { ctx: ShellCtx }) {
  const { data, error, reload } = useApi(`/${ctx.retailer}/assortiment`);

  if (!data) return <LoadState error={error} reload={reload} />;
  if (!data.available && data.reason === "PARSER PROFIEL ONTBREEKT")
    return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;
  if (!data.available)
    return (
      <div className="card empty-card">
        <div className="eyebrow">Gegevens niet beschikbaar</div>
        <h2 style={{ marginTop: 10 }}>Geen artikelniveau voor deze retailer</h2>
        <p className="sub">Rotatie per artikel vraagt artikeldata.
          {" "}<Link to={`/${ctx.retailer}/parser`}>Bekijk het profiel</Link>.</p>
      </div>
    );

  const s = data.stats;
  const pWord = data.periode_type === "maand" ? "maand" : "week";
  return (
    <>
      <h1>Assortimentsanalyse — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer}
        uitleg={data.labels.includes("SCHATTING") ? "Rotatie rekent met het handmatige winkelaantal uit Instellingen." : undefined} />
      <div className="grid kpi" style={{ marginBottom: 22 }}>
        <div className="card"><div className="kpi-label">Op / boven target</div><div className="kpi-value">{s.op_target}</div></div>
        <div className="card"><div className="kpi-label">Onder target</div>
          <div className="kpi-value" style={{ color: s.onder_target ? "oklch(0.45 0.14 27)" : undefined }}>{s.onder_target}</div></div>
        <div className="card"><div className="kpi-label">Mogelijke delist</div>
          <div className="kpi-value" style={{ color: s.delist ? "oklch(0.45 0.14 27)" : undefined }}>{s.delist}</div></div>
      </div>
      <table className="data">
        <thead><tr><th>Artikel</th><th>Merk</th><th>Rotatie</th><th>Target</th><th>Score</th><th>Advies</th></tr></thead>
        <tbody>
          {data.artikelen.map((a: any) => (
            <tr key={a.ean}>
              <td>{a.naam}<br /><span className="mono sub">{a.ean}</span></td>
              <td><BrandDot merk={a.merk} />{a.merk}</td>
              <td>
                {a.rotatie ?? "—"} st/winkel/week
                {/* Waar de rotatie op rust: het aantal periodes sinds de
                    eerste verkoop en de winkels die dit artikel voerden. */}
                {a.actieve_periodes != null && (
                  <div className="sub" style={{ fontSize: 10.5 }}>
                    {a.actieve_periodes} {pWord}{a.actieve_periodes === 1 ? "" : "en"}
                    {a.winkels ? ` · ${a.winkels} winkels` : ""}
                  </div>
                )}
              </td>
              <td>{a.target ?? "—"}</td>
              <td>{a.score != null
                ? <span className={`tag ${a.score >= 100 ? "pos" : "neg"}`}>{a.score}%</span>
                : <span className="tag">—</span>}</td>
              <td>{a.score != null && a.score < 100 && <Warn />}{a.advies}</td>
            </tr>
          ))}
          {!data.artikelen.length && <tr><td colSpan={6} className="sub">Nog geen artikeldata.</td></tr>}
        </tbody>
      </table>
    </>
  );
}
