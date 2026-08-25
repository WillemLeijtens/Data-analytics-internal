import { CHANGELOG } from "../changelog";

const fmtDatum = (iso: string) =>
  new Date(iso).toLocaleDateString("nl-NL", { day: "numeric", month: "long", year: "numeric" });

/** Releasenotes: wat er is toegevoegd of veranderd, in mensentaal. Geen
 *  retailercontext nodig — dit staat los van welke tab open staat. */
export default function Changelog() {
  return (
    <>
      <h1>Changelog</h1>
      <p className="sub" style={{ maxWidth: 640 }}>
        Nieuwe functies en herstelde fouten, nieuwste bovenaan.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16, maxWidth: 720 }}>
        {CHANGELOG.map((e, i) => (
          <div key={i} className="card">
            <div className="eyebrow">{fmtDatum(e.datum)}</div>
            {/* Geen <h3>: "The Seasons" (het sierfont van koppen, in
                hoofdletters) rendert een koppelteken als "≠" — een
                titel als "On counter-moment" wordt dan onleesbaar. */}
            <div style={{ margin: "6px 0 8px", fontWeight: 700, fontSize: 14,
                         fontFamily: "Montserrat, sans-serif", color: "var(--t-fg)" }}>
              {e.titel}
            </div>
            <p className="sub" style={{ margin: 0 }}>{e.tekst}</p>
          </div>
        ))}
      </div>
    </>
  );
}
