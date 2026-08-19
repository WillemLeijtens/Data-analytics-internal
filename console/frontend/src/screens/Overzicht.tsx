import { RetailerCard, Signaal } from "../api";
import { ShellCtx } from "../App";
import { LoadState, useApi } from "../components/shared";

const SIG_BORDER: Record<Signaal, string> = {
  green: "var(--pos)", orange: "var(--warn)", red: "var(--neg)", grey: "var(--t-fg3)",
};
const SIG_TEXT: Record<Signaal, string> = {
  green: "sig-green", orange: "sig-orange", red: "sig-red", grey: "sig-grey",
};
// Tegels op een cirkel in het 680x680-vlak. Vier retailers landen op de
// kompaspunten uit het ontwerp (boven, rechts, onder, links); bij meer of
// minder retailers verdeelt de cirkel zich vanzelf mee.
const RADAR = { size: 680, tile: 132, radius: 262 };
function tilePos(i: number, n: number) {
  const angle = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, n);
  const c = RADAR.size / 2 - RADAR.tile / 2;
  return {
    left: Math.round(c + RADAR.radius * Math.cos(angle)),
    top: Math.round(c + RADAR.radius * Math.sin(angle)),
  };
}

function CapChip({ on, label }: { on: boolean; label: string }) {
  return <span className={`chip static ${on ? "" : "off"}`}>{label}</span>;
}

export default function Overzicht({ ctx }: { ctx: ShellCtx }) {
  const { data, error, reload } = useApi<{ retailers: RetailerCard[]; aandacht: number }>("/overview");
  if (!data) return <LoadState error={error} reload={reload} />;

  const openRetailer = (c: RetailerCard) =>
    ctx.go(c.id, c.profiel ? "dashboard" : "parser");

  return (
    <>
      <h1>Overzicht</h1>
      <p className="sub">Alle retailers — status, signalen en wat elk profiel levert.</p>

      <div className="grid cards" style={{ marginTop: 22 }}>
        {data.retailers.map((c, i) => (
          <div key={c.id} className="card">
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span className="mono" style={{ color: "var(--t-fg3)" }}>{String(i + 1).padStart(2, "0")}</span>
              <span className={`tag ${c.profiel?.status === "live" ? "" : "accent"}`}>
                {c.profiel ? (c.profiel.status === "live" ? "Live" : c.profiel.status === "test" ? "Test" : "Concept") : "Nieuw"}
              </span>
            </div>
            <h3 style={{ fontSize: 21, margin: "10px 0 8px" }}>{c.naam}</h3>
            <div className="sub" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3 }}>
              <span>Periode</span><span>{c.capabilities?.periode ?? "—"}</span>
              <span>Profiel</span><span>{c.profiel ? `v${c.profiel.versie} (${c.profiel.status})` : "—"}</span>
            </div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", margin: "12px 0" }}>
              <CapChip on={!!c.capabilities?.merk} label="merk" />
              <CapChip on={!!c.capabilities?.artikel} label="artikel" />
              <CapChip on={!!c.capabilities?.winkel} label="winkel" />
              <CapChip on={!!c.capabilities?.banner} label="formule" />
            </div>
            <a style={{ cursor: "pointer", fontSize: 12 }} onClick={() => openRetailer(c)}>
              {c.profiel ? "Open dashboard" : "Parser bekijken"}
            </a>
          </div>
        ))}
      </div>

      <h2>Signalenradar</h2>
      <div className="radar-wrap">
        <div className="radar">
          <svg width="680" height="680" viewBox="0 0 680 680" style={{ position: "absolute", inset: 0 }}>
            <circle cx="340" cy="340" r="180" fill="none" stroke="var(--t-grid)" strokeWidth="1.5" />
            <circle cx="340" cy="340" r="270" fill="none" stroke="var(--t-grid)" strokeWidth="1.5" />
            <circle cx="340" cy="340" r="330" fill="none" stroke="var(--t-border)" strokeDasharray="3 6" />
            {[45, 135, 225, 315].map((a) => (
              <line key={a} x1="340" y1="340"
                x2={340 + 330 * Math.cos((a * Math.PI) / 180)}
                y2={340 + 330 * Math.sin((a * Math.PI) / 180)} stroke="var(--t-grid)" />
            ))}
          </svg>
          <div className="radar-sweep" />
          {data.retailers.map((c, i) => {
            const s = c.signalen;
            return (
              <div key={c.id} className={`radar-tile ${s.composiet === "red" ? "pulse" : ""}`}
                style={{ ...tilePos(i, data.retailers.length), borderTopColor: SIG_BORDER[s.composiet] }}
                onClick={() => openRetailer(c)}>
                <h4>{c.naam}</h4>
                <div className="meta">
                  {c.capabilities ? c.capabilities.periode.toUpperCase() : "—"} / {c.profiel ? `V${c.profiel.versie}` : "—"}
                </div>
                <div className={`context ${SIG_TEXT[s.composiet]}`}>{s.context}</div>
                <div className="dots">
                  <i title={`Assortiment: ${s.assortiment.tekst}`} className={`dot-${s.assortiment.signaal}`} />
                  <i title={`Distributie: ${s.distributie?.tekst ?? "n.v.t."}`}
                    className={`dot-${s.distributie?.signaal ?? "grey"}`} />
                  <i title={`Contract: ${s.contract.tekst}`} className={`dot-${s.contract.signaal}`} />
                  <i title={`Data: ${s.data.tekst}`} className={`dot-${s.data.signaal}`} />
                </div>
              </div>
            );
          })}
          <div className="radar-hub">
            <b>{data.aandacht}</b>
            <span>vraagt aandacht</span>
          </div>
        </div>
      </div>

      <h2>Distributie</h2>
      <p className="sub" style={{ marginTop: -6 }}>
        Ligt ons merk in evenveel winkels als eerder? Retailers die winkelniveau
        leveren (ICI) rekenen dit uit de feiten; bij de andere komt het uit de
        winkelaantallen die je bij Instellingen bijhoudt — elke wijziging wordt
        bewaard.
      </p>
      <table className="data">
        <thead><tr><th>Retailer</th><th>Signaal</th><th>Bron</th></tr></thead>
        <tbody>
          {data.retailers.filter((c) => c.profiel).map((c) => (
            <tr key={c.id} className="click" onClick={() => ctx.go(c.id, c.capabilities?.winkel ? "dashboard" : "instellingen")}>
              <td>{c.naam}</td>
              <td>
                <span className={`brand-dot dot-${c.signalen.distributie?.signaal ?? "grey"}`}
                  style={{ width: 9, height: 9 }} />
                {c.signalen.distributie?.tekst ?? "n.v.t."}
              </td>
              <td className="sub">{c.capabilities?.winkel ? "uit de aanlevering" : "handmatig winkelaantal"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Capability matrix</h2>
      <table className="data">
        <thead><tr>
          <th>Retailer</th><th>Periodiciteit</th><th>Merk</th><th>Artikel/EAN</th>
          <th>Winkel</th><th>Formule</th><th>Promo-uplift</th><th>Profiel</th>
        </tr></thead>
        <tbody>
          {data.retailers.map((c) => {
            const cell = (on?: boolean) =>
              on ? <td>ja</td> : <td style={{ color: "var(--t-fg3)" }}>nee</td>;
            return (
              <tr key={c.id}>
                <td>{c.naam}</td>
                <td>{c.capabilities?.periode ?? "—"}</td>
                {cell(c.capabilities?.merk)}{cell(c.capabilities?.artikel)}
                {cell(c.capabilities?.winkel)}{cell(c.capabilities?.banner)}
                {cell(!!c.capabilities)}
                <td>{c.profiel ? `v${c.profiel.versie} · ${c.profiel.status}` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>Terugvalregels</h2>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
        {[
          ["REGEL 01", "Geen artikelniveau", "Analyses tonen op merkniveau, met het label OP MERKNIVEAU."],
          ["REGEL 02", "Geen weekdata", "Tijdreeksen rekenen per maand, met het label OP MAANDNIVEAU."],
          ["REGEL 03", "Geen winkelnummers", "Omzet per winkel deelt door het handmatige winkelaantal uit Instellingen — label SCHATTING."],
        ].map(([eyebrow, kop, tekst]) => (
          <div key={eyebrow} className="rule-block">
            <div className="eyebrow">{eyebrow}</div>
            <b style={{ display: "block", margin: "6px 0" }}>{kop}</b>
            <span className="sub">{tekst}</span>
          </div>
        ))}
      </div>
    </>
  );
}
