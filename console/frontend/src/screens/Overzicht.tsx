import { useEffect, useState } from "react";
import { RetailerCard, Signaal, apiGet } from "../api";
import { ShellCtx } from "../App";

const SIG_BORDER: Record<Signaal, string> = {
  green: "var(--pos)", orange: "#E08A2E", red: "oklch(0.55 0.18 27)", grey: "#BAC3C8",
};
const SIG_TEXT: Record<Signaal, string> = {
  green: "sig-green", orange: "sig-orange", red: "sig-red", grey: "sig-grey",
};
// Compass positions inside the 680x680 radar: kruidvat top, etos right,
// ici bottom, douglas left (README §Signalenradar).
const POS = [
  { left: 274, top: 46 }, { left: 500, top: 274 },
  { left: 274, top: 500 }, { left: 48, top: 274 },
];

function CapChip({ on, label }: { on: boolean; label: string }) {
  return <span className={`chip static ${on ? "" : "off"}`}>{label}</span>;
}

export default function Overzicht({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<{ retailers: RetailerCard[]; aandacht: number } | null>(null);
  useEffect(() => { apiGet("/overview").then(setData); }, []);
  if (!data) return <p className="sub">Laden…</p>;

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
              <span className="mono" style={{ color: "#7E8D92" }}>{String(i + 1).padStart(2, "0")}</span>
              <span className={`tag ${c.profiel?.status === "live" ? "" : "accent"}`}>
                {c.profiel ? (c.profiel.status === "live" ? "Live" : "Concept") : "Nieuw"}
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
              <CapChip on={!!c.capabilities?.banner} label="banner" />
            </div>
            <a style={{ cursor: "pointer", fontSize: 12 }} onClick={() => openRetailer(c)}>
              {c.profiel ? "Open dashboard" : "Parser instellen"}
            </a>
          </div>
        ))}
      </div>

      <h2>Signalenradar</h2>
      <div className="radar-wrap">
        <div className="radar">
          <svg width="680" height="680" viewBox="0 0 680 680" style={{ position: "absolute", inset: 0 }}>
            <circle cx="340" cy="340" r="180" fill="none" stroke="#EAEFF1" strokeWidth="1.5" />
            <circle cx="340" cy="340" r="270" fill="none" stroke="#EAEFF1" strokeWidth="1.5" />
            <circle cx="340" cy="340" r="330" fill="none" stroke="#BAC3C8" strokeDasharray="3 6" />
            {[45, 135, 225, 315].map((a) => (
              <line key={a} x1="340" y1="340"
                x2={340 + 330 * Math.cos((a * Math.PI) / 180)}
                y2={340 + 330 * Math.sin((a * Math.PI) / 180)} stroke="#EAEFF1" />
            ))}
          </svg>
          <div className="radar-sweep" />
          {data.retailers.slice(0, 4).map((c, i) => {
            const s = c.signalen;
            return (
              <div key={c.id} className={`radar-tile ${s.composiet === "red" ? "pulse" : ""}`}
                style={{ ...POS[i], borderTopColor: SIG_BORDER[s.composiet] }}
                onClick={() => openRetailer(c)}>
                <h4>{c.naam}</h4>
                <div className="meta">
                  {c.capabilities ? c.capabilities.periode.toUpperCase() : "—"} / {c.profiel ? `V${c.profiel.versie}` : "—"}
                </div>
                <div className={`context ${SIG_TEXT[s.composiet]}`}>{s.context}</div>
                <div className="dots">
                  <i title={`Assortiment: ${s.assortiment.tekst}`} className={`dot-${s.assortiment.signaal}`} />
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

      <h2>Capability matrix</h2>
      <table className="data">
        <thead><tr>
          <th>Retailer</th><th>Periodiciteit</th><th>Merk</th><th>Artikel/EAN</th>
          <th>Winkel</th><th>Banner</th><th>Promo-uplift</th><th>Profiel</th>
        </tr></thead>
        <tbody>
          {data.retailers.map((c) => {
            const cell = (on?: boolean) =>
              on ? <td>ja</td> : <td style={{ color: "#BAC3C8" }}>nee</td>;
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
