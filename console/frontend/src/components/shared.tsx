import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { BRAND_COLORS, Datagat, Milestone, PromoMarker, apiGet, apiSend, fmtEur, fmtNum, merkKleur } from "../api";
import { ThemaModus, bepaalThema, bewaarModus, leesModus, pasToe, volgSysteem } from "../theme";

/** Uniform laden/fout-gedrag voor de leesschermen: elke API-fout wordt een
 * nette kaart met "Opnieuw proberen" in plaats van een eeuwig "Laden…". */
export function useApi<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let live = true;
    setData(null);
    setError(null);
    apiGet<T>(path)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(String(e?.message ?? e)); });
    return () => { live = false; };
  }, [path, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}

export function LoadState({ error, reload }: { error: string | null; reload?: () => void }) {
  if (!error) return <p className="sub">Laden…</p>;
  return (
    <div className="card empty-card">
      <div className="eyebrow">Er ging iets mis</div>
      <p className="sub" style={{ margin: "10px auto 16px", maxWidth: 480 }}>
        De gegevens konden niet geladen worden ({error}).
      </p>
      {reload && <button className="btn ghost" onClick={reload}>Opnieuw proberen</button>}
    </div>
  );
}

export function LevelStrip({ labels, uitleg, retailer }:
  { labels: string[]; uitleg?: string; retailer: string }) {
  if (!labels.length) return null;
  return (
    <div className="level-strip">
      <span className="eyebrow">Niveau</span>
      <span className="chips">
        {labels.map((l) => <span key={l} className="chip static">{l}</span>)}
      </span>
      {uitleg && <span className="sub">{uitleg}</span>}
      <Link to={`/${retailer}/parser`}>Profiel bekijken</Link>
    </div>
  );
}

/** Melding voor een retailer waarvoor nog geen parser bestaat. Parsers
 *  worden per retailer in het project gebouwd op basis van een echt
 *  voorbeeldbestand — niet in dit scherm samengeklikt. */
export function EmptyProfileCard({ retailer, go }:
  { retailer: string; go: (r: string, s: string) => void }) {
  return (
    <div className="card empty-card">
      <div className="eyebrow">Nog geen parser</div>
      <h2 style={{ marginTop: 10 }}>Deze retailer is nog niet aangesloten</h2>
      <p className="sub" style={{ maxWidth: 470, margin: "10px auto 6px" }}>
        Voor deze retailer is nog geen parser gebouwd. Parsers worden per
        retailer in het Claude&nbsp;Code-project gemaakt, op basis van een
        écht aanleverbestand — pas dan is zeker dat tabbladen, kolommen en
        totalen kloppen.
      </p>
      <p className="sub" style={{ maxWidth: 470, margin: "0 auto 22px" }}>
        <b>Wat jij doet:</b> deel een voorbeeldbestand van deze retailer.
        Zodra de parser klaar is, importeer je hier gewoon je bestanden en
        verschijnen alle analyses vanzelf.
      </p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
        <button className="btn" onClick={() => go(retailer, "import")}>Bestand uploaden</button>
      </div>
    </div>
  );
}

/** Filterchips (merk/land/formule). Leeg = alles; klikken zet aan/uit.
 *
 *  `waarschuwing` hangt een rode driehoek aan één chip, met de uitleg als
 *  hovertekst. Zo staat "van dit merk ontbreekt data" bij het merk zelf, in
 *  plaats van in een losse melding waarin je moet opzoeken wie het betreft. */
export function MultiChips({ all, sel, onChange, waarschuwing }:
  { all: string[]; sel: string[]; onChange: (v: string[]) => void;
    waarschuwing?: Record<string, string> }) {
  return (
    <span className="chips" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      {all.map((v) => (
        <button key={v} className={`chip ${sel.includes(v) ? "" : "off"}`}
          aria-pressed={sel.length === 0 || sel.includes(v)}
          onClick={() => onChange(sel.includes(v) ? sel.filter((x) => x !== v) : [...sel, v])}>
          {waarschuwing?.[v] && (
            <span title={waarschuwing[v]} aria-label={`Let op: ${waarschuwing[v]}`} role="img"
              style={{ color: "var(--neg)", display: "inline-flex", verticalAlign: "middle",
                       marginRight: 4 }}>
              <Driehoek kleur="currentColor" />
            </span>
          )}
          {v}
        </button>
      ))}
    </span>
  );
}

export function BrandDot({ merk }: { merk: string | null }) {
  return <span className="brand-dot" style={{ background: merkKleur(merk) }} />;
}

export function DeltaTag({ pct }: { pct: number | null }) {
  if (pct == null) return <span className="tag">—</span>;
  const cls = pct > 0 ? "pos" : pct < 0 ? "neg" : "";
  return <span className={`tag ${cls}`}>{pct > 0 ? "+" : ""}{pct.toLocaleString("nl-NL")}%</span>;
}

/* ------------------------------------------------------------ TrendChart */

type Series = Record<number, Record<number, number>>; // year -> periodNum -> value

export function TrendChart({ series, years, isEuro, periodWord,
  mijlpalen, promoties, merken, onMijlpaal, onMijlpaalWeg }:
  { series: Series; years: number[]; isEuro: boolean; periodWord: string;
    mijlpalen?: Milestone[];
    /** Bevestigde acties. Eigen kleur en vorm, want een actie is iets anders
     *  dan een mijlpaal en mag daar niet mee te verwarren zijn. */
    promoties?: PromoMarker[];
    /** Merken waarvan deze retailer data heeft — de enige geldige keuzes. */
    merken?: string[];
    onMijlpaal?: (m: { jaar: number; periode_nummer: number; tekst: string;
                       merk: string }) => Promise<void>;
    onMijlpaalWeg?: (id: number) => Promise<void> }) {
  const W = 860, H = 260, PAD = 42;
  const [hover, setHover] = useState<number | null>(null);
  // Mijlpalen: standaard aan, want een onverklaarde piek in de lijn is
  // precies waarvoor ze bestaan. Uit kunnen zetten blijft nodig zodra het er
  // veel zijn en je puur naar het verloop wil kijken.
  const [toonMijlpalen, setToonMijlpalen] = useState(true);
  const [mijlpaalJaar, setMijlpaalJaar] = useState<number | null>(null);
  // Acties: eigen schuifje en eigen filter. Ze staan los van de mijlpalen —
  // het zijn twee soorten gebeurtenissen met een eigen vraag erachter.
  const [toonPromoties, setToonPromoties] = useState(true);
  const [promoMerk, setPromoMerk] = useState<string | null>(null);
  const [promoJaar, setPromoJaar] = useState<number | null>(null);
  const [nieuw, setNieuw] = useState<{ jaar: number; periode: number } | null>(null);
  const [tekst, setTekst] = useState("");
  const [merk, setMerk] = useState("");
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const ref = useRef<SVGSVGElement>(null);

  const nums = Array.from(new Set(years.flatMap((y) => Object.keys(series[y] ?? {}).map(Number)))).sort((a, b) => a - b);
  if (!nums.length) return <p className="sub">Nog geen data.</p>;
  const maxX = Math.max(...nums), minX = Math.min(...nums);
  const maxY = Math.max(1, ...years.flatMap((y) => Object.values(series[y] ?? {})));
  const x = (p: number) => PAD + ((p - minX) / Math.max(1, maxX - minX)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - (v / maxY) * (H - 2 * PAD);
  // oudste -> nieuwste; de jaartokens contrasteren in beide thema's.
  const colors = ["var(--c-y1)", "var(--c-y2)", "var(--c-y3)"];

  // Het jaar bepaalt de kleur van de lijn; een mijlpaal krijgt de kleur van
  // het jaar waar hij bij hoort, anders wijst hij naar de verkeerde lijn.
  const jaarKleur = (jr: number) => {
    const i = years.indexOf(jr);
    return i < 0 ? "var(--t-fg3)" : colors[colors.length - years.length + i];
  };

  /** De periode waar de muis het dichtst bij zit — de x-as is discreet, dus
   *  "waar je klikt" is altijd één week of maand. */
  const dichtstbij = (e: React.MouseEvent) => {
    const rect = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    return nums.reduce((a, b) => (Math.abs(x(b) - px) < Math.abs(x(a) - px) ? b : a));
  };
  const onMove = (e: React.MouseEvent) => setHover(dichtstbij(e));

  const kanMijlpalen = !!onMijlpaal;
  const alle = mijlpalen ?? [];
  const jarenMetMijlpaal = Array.from(new Set(alle.map((m) => m.jaar))).sort();
  const zichtbaar = toonMijlpalen
    ? alle.filter((m) => mijlpaalJaar == null || m.jaar === mijlpaalJaar)
    : [];
  // Buiten de getoonde periodes valt niets te tekenen — de x-as loopt maar
  // zo ver als de data reikt. In de lijst eronder staat hij wél, met
  // vermelding, zodat een mijlpaal niet spoorloos verdwijnt.
  const opDeAs = (m: { periode_nummer: number }) =>
    m.periode_nummer >= minX && m.periode_nummer <= maxX;

  const alleActies = promoties ?? [];
  const promoMerken = Array.from(new Set(alleActies.map((a) => a.merk ?? "ONBEKEND"))).sort();
  const promoJaren = Array.from(new Set(alleActies.map((a) => a.jaar))).sort();
  const acties = toonPromoties
    ? alleActies.filter((a) => (promoMerk == null || (a.merk ?? "ONBEKEND") === promoMerk)
                            && (promoJaar == null || a.jaar === promoJaar))
    : [];
  const actieTekst = (a: PromoMarker) =>
    `Actie ${periodWord.toLowerCase()} ${a.periode_nummer} ${a.jaar}`
    + (a.merk ? ` · ${a.merk}` : "")
    + (a.uplift_pct != null
        ? ` — ${a.uplift_pct > 0 ? "+" : ""}${a.uplift_pct.toLocaleString("nl-NL")}%`
          + ` (${fmtEur(a.omzet)} tegen een basislijn van ${fmtEur(a.basislijn)})`
        : ` — geen uplift: ${a.reden ?? "te weinig vergelijkbare periodes"}`);

  const merkKeuzes = merken ?? [];
  const plaats = async () => {
    if (!nieuw || !onMijlpaal || !tekst.trim() || !merk) return;
    setBezig(true);
    setFout(null);
    try {
      await onMijlpaal({ jaar: nieuw.jaar, periode_nummer: nieuw.periode,
                         tekst: tekst.trim(), merk });
      setNieuw(null);
      setTekst("");
    } catch (e: any) {
      setFout(String(e?.message ?? e));
    } finally {
      setBezig(false);
    }
  };

  const fmt = (v: number) => (isEuro ? fmtEur(v) : fmtNum(Math.round(v)));
  const hoverPct = hover != null ? Math.min(86, Math.max(14, ((x(hover)) / W) * 100)) : 0;

  return (
    <div style={{ position: "relative" }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", cursor: "crosshair" }}
        role="img"
        aria-label={`${isEuro ? "Omzet" : "Volume"} per ${periodWord.toLowerCase()}, jaren ${years.join(", ")}`}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}
        onClick={kanMijlpalen ? (e) => {
          const periode = dichtstbij(e);
          // Voorstel: het laatste jaar van de grafiek — dat is bijna altijd
          // het jaar waarover je iets vastlegt. Aanpasbaar in het formulier.
          setNieuw({ jaar: years[years.length - 1], periode });
          setTekst("");
          // Is er maar één merk in beeld (of gefilterd op één), dan is de
          // keuze al gemaakt; anders bewust leeg, zodat niemand per ongeluk
          // het verkeerde merk vastlegt.
          setMerk(merkKeuzes.length === 1 ? merkKeuzes[0] : "");
          setFout(null);
        } : undefined}>
        <title>{`${isEuro ? "Omzet" : "Volume"} per ${periodWord.toLowerCase()}, jaar op jaar (${years.join(", ")})`}</title>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={PAD} x2={W - PAD} y1={y(maxY * f)} y2={y(maxY * f)} stroke="var(--t-grid)" />
        ))}
        <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke="var(--t-border)" />
        {nums.filter((_, i) => i % Math.ceil(nums.length / 12) === 0).map((p) => (
          <text key={p} x={x(p)} y={H - PAD + 16} textAnchor="middle" fontSize="10.5" fill="var(--t-fg3)">{p}</text>
        ))}
        {[maxY, maxY / 2].map((v, i) => (
          <text key={i} x={PAD - 6} y={y(v) + 3} textAnchor="end" fontSize="10.5" fill="var(--t-fg3)">
            {/* Onder de €10k hele euro's: "€0k" op de per-winkel-as zei niets. */}
            {isEuro ? (v >= 10000 ? "€" + Math.round(v / 1000) + "k" : fmtEur(v))
                    : fmtNum(Math.round(v))}
          </text>
        ))}
        {years.map((yr, i) => {
          const pts = nums.filter((p) => series[yr]?.[p] != null);
          if (!pts.length) return null;
          const d = pts.map((p, j) => `${j ? "L" : "M"}${x(p)},${y(series[yr][p])}`).join(" ");
          return <path key={yr} d={d} fill="none" stroke={colors[colors.length - years.length + i]} strokeWidth={yr === years[years.length - 1] ? 2 : 1.4} />;
        })}
        {acties.filter(opDeAs).map((a) => (
          <g key={`${a.merk}-${a.periode}`} style={{ pointerEvents: "none" }}>
            <line x1={x(a.periode_nummer)} x2={x(a.periode_nummer)} y1={PAD} y2={H - PAD + 5}
              stroke="var(--promo)" strokeWidth={1} opacity={0.5} />
            {/* Driehoekje ONDER de as: andere kleur én andere vorm dan de
                mijlpaalruit, zodat de twee ook zonder kleur uit elkaar te
                houden zijn. */}
            <path d={`M${x(a.periode_nummer)},${H - PAD + 4} l5,7 l-10,0 z`}
              fill="var(--promo)" />
            <title>{actieTekst(a)}</title>
          </g>
        ))}
        {zichtbaar.filter(opDeAs).map((m) => (
          <g key={m.id} style={{ pointerEvents: "none" }}>
            <line x1={x(m.periode_nummer)} x2={x(m.periode_nummer)} y1={PAD - 6} y2={H - PAD}
              stroke={jaarKleur(m.jaar)} strokeWidth={1} strokeDasharray="2 4" opacity={0.75} />
            {/* Ruitje op de bovenrand: opvallend genoeg om te zien, klein
                genoeg om de lijnen niet te overstemmen. */}
            <path d={`M${x(m.periode_nummer)},${PAD - 11} l4,4 l-4,4 l-4,-4 z`}
              fill={jaarKleur(m.jaar)} />
            <title>{`${periodWord} ${m.periode_nummer} ${m.jaar}`
              + (m.merk ? ` · ${m.merk}` : "") + ` — ${m.tekst}`}</title>
          </g>
        ))}
        {nieuw && (
          <line x1={x(nieuw.periode)} x2={x(nieuw.periode)} y1={PAD - 11} y2={H - PAD}
            stroke={jaarKleur(nieuw.jaar)} strokeWidth={1.5} />
        )}
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD} y2={H - PAD} stroke="var(--t-fg3)" strokeDasharray="3 3" />
            {years.map((yr, i) => series[yr]?.[hover] != null && (
              <circle key={yr} cx={x(hover)} cy={y(series[yr][hover])} r={3.5}
                fill={colors[colors.length - years.length + i]} />
            ))}
          </g>
        )}
      </svg>
      {hover != null && !nieuw && (
        <div className="tooltip" style={{ left: `${hoverPct}%`, top: 8 }}>
          <b>{periodWord} {hover}</b>
          {years.map((yr) => (
            <div key={yr}>{yr}: {series[yr]?.[hover] != null ? fmt(series[yr][hover]) : "—"}</div>
          ))}
          {zichtbaar.filter((m) => m.periode_nummer === hover).map((m) => (
            <div key={m.id} style={{ marginTop: 4 }}>
              <span style={{ color: jaarKleur(m.jaar) }}>◆</span> {m.jaar}
              {m.merk ? ` · ${m.merk}` : ""}: {m.tekst}
            </div>
          ))}
          {acties.filter((a) => a.periode_nummer === hover).map((a) => (
            <div key={`${a.merk}-${a.periode}`} style={{ marginTop: 4 }}>
              <span style={{ color: "var(--promo)" }}>▲</span> {actieTekst(a).replace("Actie ", "")}
            </div>
          ))}
          {/* Zonder deze regel weet niemand dat de grafiek klikbaar is. */}
          {kanMijlpalen && <div className="sub" style={{ marginTop: 4 }}>klik om een mijlpaal te zetten</div>}
        </div>
      )}
      {nieuw && (
        <div className="chart-popover" role="dialog" aria-label="Mijlpaal plaatsen"
          style={{ left: `${Math.min(70, Math.max(4, (x(nieuw.periode) / W) * 100))}%`, top: 8 }}
          // Vangnet: mocht er ooit een klikhandler om de grafiek heen komen,
          // dan mag een klik in dit formulier daar niet ook op afgaan.
          onClick={(e) => e.stopPropagation()}>
          <b>Mijlpaal op {periodWord.toLowerCase()} {nieuw.periode}</b>
          <div style={{ display: "flex", gap: 6, margin: "8px 0" }}>
            <select value={nieuw.jaar} aria-label="Jaar"
              onChange={(e) => setNieuw({ ...nieuw, jaar: Number(e.target.value) })}>
              {years.map((yr) => <option key={yr} value={yr}>{yr}</option>)}
            </select>
            {merkKeuzes.length ? (
              <select value={merk} aria-label="Merk" style={{ flex: 1, minWidth: 0 }}
                onChange={(e) => setMerk(e.target.value)}>
                <option value="">merk kiezen…</option>
                {merkKeuzes.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              // Liever dit dan een lege dropdown met een knop die het altijd
              // weigert: dan zoek je naar wat je fout doet.
              <span className="sub" style={{ flex: 1 }}>
                deze retailer levert geen merken, dus er is niets om een
                mijlpaal aan te hangen
              </span>
            )}
          </div>
          <input autoFocus value={tekst} placeholder="wat gebeurde er?" aria-label="Wat gebeurde er?"
            style={{ width: "100%", boxSizing: "border-box", marginBottom: 8 }} maxLength={200}
            onChange={(e) => setTekst(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") plaats();
              if (e.key === "Escape") setNieuw(null);
            }} />
          {fout && <p className="sub sig-red">{fout}</p>}
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn" disabled={bezig || !tekst.trim() || !merk} onClick={plaats}>
              {bezig ? "Bezig…" : "Plaatsen"}
            </button>
            <button className="btn ghost" onClick={() => setNieuw(null)}>Annuleren</button>
          </div>
        </div>
      )}
      <div className="sub" style={{ display: "flex", gap: 16, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
        {years.map((yr, i) => (
          <span key={yr}><span style={{ display: "inline-block", width: 14, height: 2, background: colors[colors.length - years.length + i], verticalAlign: "middle", marginRight: 5 }} />{yr}</span>
        ))}
        {alleActies.length > 0 && (
          <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" checked={toonPromoties} role="switch"
                aria-label="Promoties tonen"
                onChange={(e) => setToonPromoties(e.target.checked)} />
              <span style={{ color: "var(--promo)" }}>▲</span> Promoties ({alleActies.length})
            </label>
            {toonPromoties && promoMerken.length > 1 && (
              <span className="chips" style={{ display: "inline-flex", gap: 6 }}>
                {promoMerken.map((m) => (
                  <button key={m} className={`chip ${promoMerk === m ? "" : "off"}`}
                    aria-pressed={promoMerk === m}
                    onClick={() => setPromoMerk(promoMerk === m ? null : m)}>{m}</button>
                ))}
              </span>
            )}
            {toonPromoties && promoJaren.length > 1 && (
              <span className="chips" style={{ display: "inline-flex", gap: 6 }}>
                {promoJaren.map((jr) => (
                  <button key={jr} className={`chip ${promoJaar === jr ? "" : "off"}`}
                    aria-pressed={promoJaar === jr}
                    onClick={() => setPromoJaar(promoJaar === jr ? null : jr)}>{jr}</button>
                ))}
              </span>
            )}
          </span>
        )}
        {kanMijlpalen && alle.length > 0 && (
          <span style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" checked={toonMijlpalen} role="switch"
                onChange={(e) => setToonMijlpalen(e.target.checked)} />
              Mijlpalen ({alle.length})
            </label>
            {toonMijlpalen && jarenMetMijlpaal.length > 1 && (
              <span className="chips" style={{ display: "inline-flex", gap: 6 }}>
                {jarenMetMijlpaal.map((jr) => (
                  <button key={jr} className={`chip ${mijlpaalJaar === jr ? "" : "off"}`}
                    aria-pressed={mijlpaalJaar === jr}
                    onClick={() => setMijlpaalJaar(mijlpaalJaar === jr ? null : jr)}>{jr}</button>
                ))}
              </span>
            )}
          </span>
        )}
      </div>
      {zichtbaar.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0" }}>
          {zichtbaar.map((m) => (
            <li key={m.id} className="sub" style={{ display: "flex", gap: 8, alignItems: "baseline", padding: "3px 0" }}>
              <span style={{ color: jaarKleur(m.jaar) }}>◆</span>
              <span className="mono" style={{ whiteSpace: "nowrap" }}>
                {periodWord.toLowerCase()} {m.periode_nummer} {m.jaar}
              </span>
              {m.merk && <BrandDot merk={m.merk} />}
              <span style={{ color: "var(--t-fg)" }}>
                {m.merk ? `${m.merk} — ${m.tekst}` : m.tekst}
              </span>
              {!opDeAs(m) && <span>· buiten de getoonde periodes</span>}
              {onMijlpaalWeg && (
                <button className="btn ghost" style={{ marginLeft: "auto", padding: "1px 8px" }}
                  aria-label={`Mijlpaal ${m.tekst} verwijderen`}
                  onClick={() => onMijlpaalWeg(m.id)}>Verwijderen</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ Datagaten */

/** Meerjarige gaten in de aanlevering: een jaar dat tussen twee leveringen
 *  helemaal ontbreekt. Of dat klopt (het merk lag er dat jaar niet) of niet
 *  (een bestand is nooit ingelezen) staat niet in de data — daarom vraagt
 *  het scherm het, in plaats van er zelf een conclusie aan te hangen. */
export function useDatagaten(retailer: string | null) {
  const { data, error, reload } = useApi<{ beschikbaar: boolean; gaten: Datagat[] }>(
    retailer && retailer !== "alle" ? `/${retailer}/datagaten` : null);
  const gaten = data?.gaten ?? [];
  return { gaten, onbeoordeeld: gaten.filter((g) => !g.oordeel), error, reload };
}

/** Melding op het dashboard: alleen zichtbaar zolang er iets te oordelen is.
 *  Een beoordeeld gat is geen melding meer — dan is het een aantekening. */
export function DatagatMelding({ retailer, go }:
  { retailer: string; go: (r: string, s: string) => void }) {
  const { onbeoordeeld } = useDatagaten(retailer);
  if (!onbeoordeeld.length) return null;
  const n = onbeoordeeld.length;
  return (
    <div className="card" style={{ marginTop: 14, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
      <span className="brand-dot dot-orange" style={{ margin: 0 }} />
      <span>
        <b>{n === 1 ? "1 datagat" : `${n} datagaten`} zonder oordeel.</b>{" "}
        <span className="sub">
          {onbeoordeeld[0].tekst}{n > 1 ? ` (en nog ${n - 1})` : ""} — zolang niemand
          zegt of dat klopt, weet je niet wat een vergelijking over dat jaar betekent.
        </span>
      </span>
      <button className="btn ghost" style={{ marginLeft: "auto" }}
        onClick={() => go(retailer, "import-status")}>Beoordelen</button>
    </div>
  );
}

function DatagatRij({ retailer, gat, na }:
  { retailer: string; gat: Datagat; na: () => void }) {
  const [open, setOpen] = useState(!gat.oordeel);
  const [toelichting, setToelichting] = useState(gat.toelichting ?? "");
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);

  const oordeel = async (waarde: "klopt" | "klopt_niet") => {
    setBezig(true);
    setFout(null);
    try {
      await apiSend(`/${retailer}/datagaten`, "PUT", {
        merk: gat.merk, land: gat.land, banner: gat.banner,
        van_jaar: gat.van_jaar, tot_jaar: gat.tot_jaar,
        oordeel: waarde, toelichting: toelichting.trim() || null,
      });
      setOpen(false);
      na();
    } catch (e: any) {
      setFout(String(e?.message ?? e));
    } finally {
      setBezig(false);
    }
  };

  return (
    <div style={{ padding: "10px 0", borderTop: "1px solid var(--t-card2)" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className={`brand-dot dot-${gat.oordeel ? "green" : "orange"}`} style={{ margin: 0 }} />
        <span>{gat.tekst}</span>
        <span className="sub">· wel data in {gat.jaren_met_data.join(", ")}</span>
        {gat.oordeel && !open && (
          <span style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "baseline" }}>
            <span className={`tag ${gat.oordeel === "klopt" ? "" : "accent"}`}>
              {gat.oordeel === "klopt" ? "Klopt" : "Klopt niet"}
            </span>
            <button className="btn ghost" style={{ padding: "1px 8px" }}
              onClick={() => setOpen(true)}>Wijzigen</button>
          </span>
        )}
      </div>
      {gat.oordeel && !open && (gat.toelichting || gat.beoordeeld_door) && (
        <p className="sub" style={{ margin: "4px 0 0 19px" }}>
          {gat.toelichting}
          {gat.beoordeeld_door ? ` — ${gat.beoordeeld_door}` : ""}
        </p>
      )}
      {open && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, marginLeft: 19, flexWrap: "wrap" }}>
          <input value={toelichting} placeholder="toelichting (optioneel)" maxLength={300}
            aria-label="Toelichting" style={{ flex: "1 1 260px", minWidth: 0 }}
            onChange={(e) => setToelichting(e.target.value)} />
          <button className="btn" disabled={bezig} onClick={() => oordeel("klopt")}>Klopt</button>
          <button className="btn ghost" disabled={bezig} onClick={() => oordeel("klopt_niet")}>Klopt niet</button>
          {gat.oordeel && (
            <button className="btn ghost" onClick={() => setOpen(false)}>Annuleren</button>
          )}
          {fout && <p className="sub sig-red" style={{ width: "100%" }}>{fout}</p>}
        </div>
      )}
    </div>
  );
}

/** De volledige lijst met te beoordelen gaten voor één retailer. */
export function DatagatenPaneel({ retailer }: { retailer: string }) {
  const { gaten, onbeoordeeld, reload } = useDatagaten(retailer);
  if (!gaten.length) return null;
  return (
    <div style={{ marginTop: 14 }}>
      <div className="eyebrow">
        Datagaten{onbeoordeeld.length ? ` · ${onbeoordeeld.length} zonder oordeel` : " · allemaal beoordeeld"}
      </div>
      <p className="sub" style={{ margin: "6px 0 0" }}>
        Een jaar dat tussen twee leveringen ontbreekt. Uit de data is niet af te
        leiden of het merk er dat jaar niet lag of dat een bestand nooit is
        ingelezen — vandaar de vraag.
      </p>
      {gaten.map((g) => (
        <DatagatRij key={`${g.merk}|${g.land}|${g.banner}|${g.van_jaar}|${g.tot_jaar}`}
          retailer={retailer} gat={g} na={reload} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ Sparkline */

export function Sparkline({ ytd, lytd, isEuro, periodWord, jaar }:
  { ytd: Record<number, number>; lytd: Record<number, number>; isEuro: boolean;
    periodWord: string; jaar: number }) {
  const W = 150, H = 34;
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const nums = Array.from(new Set([...Object.keys(ytd), ...Object.keys(lytd)].map(Number))).sort((a, b) => a - b);
  if (!nums.length) return null;
  const maxX = Math.max(...nums), minX = Math.min(...nums);
  const maxY = Math.max(1, ...Object.values(ytd), ...Object.values(lytd));
  const x = (p: number) => 2 + ((p - minX) / Math.max(1, maxX - minX)) * (W - 4);
  const y = (v: number) => H - 3 - (v / maxY) * (H - 6);
  const path = (s: Record<number, number>) =>
    nums.filter((p) => s[p] != null).map((p, i) => `${i ? "L" : "M"}${x(p)},${y(s[p])}`).join(" ");
  const fmt = (v?: number) => (v == null ? "—" : isEuro ? fmtEur(v) : fmtNum(Math.round(v)));
  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <svg ref={ref} width={W} height={H}
        role="img" aria-label={`Verloop per ${periodWord.toLowerCase()}, dit jaar tegen vorig jaar`}
        onMouseMove={(e) => {
          const rect = ref.current!.getBoundingClientRect();
          const px = e.clientX - rect.left;
          setHover(nums.reduce((a, b) => (Math.abs(x(b) - px) < Math.abs(x(a) - px) ? b : a)));
        }}
        onMouseLeave={() => setHover(null)}>
        <title>{`Verloop per ${periodWord.toLowerCase()}: doorgetrokken lijn dit jaar, stippellijn vorig jaar`}</title>
        <path d={path(lytd)} fill="none" stroke="var(--t-border)" strokeWidth="1.2" strokeDasharray="3 3" />
        <path d={path(ytd)} fill="none" stroke="var(--t-fg)" strokeWidth="1.5" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke="var(--t-fg3)" strokeDasharray="2 2" />}
      </svg>
      {hover != null && (
        <span className="tooltip" style={{ left: x(hover), top: -46 }}>
          <b>{periodWord} {hover}</b><br />
          {jaar}: {fmt(ytd[hover])} · {jaar - 1}: {fmt(lytd[hover])}
        </span>
      )}
    </span>
  );
}

/* -------------------------------------------------- TijdlijnPanelen */

type TijdlijnReeks = {
  merk: string;
  omzet: number[];
  winkels: (number | null)[];
  per_winkel: (number | null)[];
  bron: string[];
};

/** Twee panelen op één doorlopende tijdas: boven de omzet per winkel, eronder
 *  het winkelbestand. Bewust geen tweede y-as in één grafiek — dan bepaalt de
 *  schaalkeuze hoe sterk het verband lijkt. Zo lees je direct of een stijgend
 *  gemiddelde van beter verkopen komt of van minder winkels. */
export function TijdlijnPanelen({ periodes, reeksen, isMaand }:
  { periodes: string[]; reeksen: TijdlijnReeks[]; isMaand: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  const W = 860, HB = 190, HO = 110, PAD = 52, GAP = 26;
  const H = HB + GAP + HO + 26;
  if (!periodes.length) return <p className="sub">Nog geen data.</p>;

  const x = (i: number) => PAD + (i / Math.max(1, periodes.length - 1)) * (W - PAD - 14);
  const maxTop = Math.max(1, ...reeksen.flatMap((r) => r.per_winkel.filter((v): v is number => v != null)));
  const winkelWaarden = reeksen.flatMap((r) => r.winkels.filter((v): v is number => v != null));
  const maxBot = Math.max(1, ...winkelWaarden);
  // Ondergrens van het winkelpaneel niet op nul: een daling van 530 naar 470
  // is anders een onzichtbaar streepje bovenin.
  const minBot = Math.max(0, Math.min(...winkelWaarden) * 0.9);
  const yTop = (v: number) => 20 + (1 - v / maxTop) * (HB - 34);
  const yBot = (v: number) => HB + GAP + 14 + (1 - (v - minBot) / Math.max(1, maxBot - minBot)) * (HO - 30);

  const pad = (vals: (number | null)[], yf: (v: number) => number, alleenGemeten?: boolean,
               bron?: string[]) => {
    const stukken: string[] = [];
    let huidig = "";
    vals.forEach((v, i) => {
      const past = v != null && (!bron || (alleenGemeten ? bron[i] !== "aangenomen" : bron[i] === "aangenomen"));
      if (!past) { if (huidig) { stukken.push(huidig); huidig = ""; } return; }
      huidig += `${huidig ? "L" : "M"}${x(i)},${yf(v as number)}`;
    });
    if (huidig) stukken.push(huidig);
    return stukken;
  };

  const labelIdx = periodes.map((_, i) => i)
    .filter((i) => i % Math.ceil(periodes.length / 8) === 0);

  const onMove = (e: React.MouseEvent) => {
    const rect = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let dichtst = 0;
    periodes.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(dichtst) - px)) dichtst = i; });
    setHover(dichtst);
  };

  return (
    <div style={{ position: "relative" }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", cursor: "crosshair" }}
        role="img"
        aria-label={`Omzet per winkel en aantal winkels per ${isMaand ? "maand" : "week"}, ${periodes[0]} tot ${periodes[periodes.length - 1]}`}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <title>Boven: omzet per winkel. Onder: aantal winkels. Zelfde tijdas, zelfde kleur per merk.</title>

        <text x={PAD} y={12} fontSize="10.5" fill="var(--t-fg2)" letterSpacing="0.12em">OMZET PER WINKEL</text>
        {[0.5, 1].map((f) => (
          <line key={f} x1={PAD} x2={W - 14} y1={yTop(maxTop * f)} y2={yTop(maxTop * f)} stroke="var(--t-grid)" />
        ))}
        {[maxTop, maxTop / 2].map((v, i) => (
          <text key={i} x={PAD - 6} y={yTop(v) + 3} textAnchor="end" fontSize="10.5" fill="var(--t-fg3)">
            {v >= 10000 ? "€" + Math.round(v / 1000) + "k" : fmtEur(v)}
          </text>
        ))}

        <text x={PAD} y={HB + GAP + 4} fontSize="10.5" fill="var(--t-fg2)" letterSpacing="0.12em">AANTAL WINKELS</text>
        <line x1={PAD} x2={W - 14} y1={yBot(minBot)} y2={yBot(minBot)} stroke="var(--t-grid)" />
        {[maxBot, minBot].map((v, i) => (
          <text key={i} x={PAD - 6} y={yBot(v) + 3} textAnchor="end" fontSize="10.5" fill="var(--t-fg3)">
            {Math.round(v)}
          </text>
        ))}

        {reeksen.map((r) => {
          const kleur = merkKleur(r.merk);
          return (
            <g key={r.merk}>
              {pad(r.per_winkel, yTop, true, r.bron).map((d, i) => (
                <path key={`t${i}`} d={d} fill="none" stroke={kleur} strokeWidth={1.8} />
              ))}
              {pad(r.per_winkel, yTop, false, r.bron).map((d, i) => (
                // Gestippeld waar het winkelaantal een aanname is.
                <path key={`ta${i}`} d={d} fill="none" stroke={kleur} strokeWidth={1.4}
                  strokeDasharray="3 3" opacity={0.7} />
              ))}
              {pad(r.winkels, yBot, true, r.bron).map((d, i) => (
                <path key={`b${i}`} d={d} fill="none" stroke={kleur} strokeWidth={1.8} />
              ))}
              {pad(r.winkels, yBot, false, r.bron).map((d, i) => (
                <path key={`ba${i}`} d={d} fill="none" stroke={kleur} strokeWidth={1.4}
                  strokeDasharray="3 3" opacity={0.7} />
              ))}
            </g>
          );
        })}

        {hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={14} y2={HB + GAP + HO - 12}
            stroke="var(--t-fg)" strokeWidth={0.8} opacity={0.35} />
        )}
        {labelIdx.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--t-fg3)">
            {periodes[i]}
          </text>
        ))}
      </svg>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 6 }}>
        {reeksen.map((r) => (
          <span key={r.merk} className="sub" style={{ fontSize: 11 }}>
            <span style={{ color: merkKleur(r.merk) }}>—</span> {r.merk}
          </span>
        ))}
      </div>

      {hover != null && (
        <div className="tooltip" style={{
          left: `${Math.min(78, Math.max(12, (x(hover) / W) * 100))}%`, top: 0,
        }}>
          <b>{periodes[hover]}</b>
          {reeksen.map((r) => (
            <div key={r.merk} style={{ whiteSpace: "nowrap" }}>
              <span style={{ color: merkKleur(r.merk) }}>■</span>{" "}
              {r.merk}: {r.per_winkel[hover] != null ? fmtEur(r.per_winkel[hover] as number) : "—"}
              {" "}· {r.winkels[hover] ?? "—"} winkels
              {r.bron[hover] === "aangenomen" && " (aangenomen)"}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}



/** De driehoek zelf. Kleur bepaalt de betekenis: rood = er ontbreekt data,
    amber = aandachtspunt in de cijfers die er wél zijn. */
function Driehoek({ kleur }: { kleur: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={kleur}
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      style={{ display: "block" }}>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

/** Waarschuwing dat de aanlevering gaten heeft. Meerdere meldingen worden
    regels binnen één tooltip: één icoon per artikel, niet een rij driehoeken. */
export function DekkingWaarschuwing({ dekking }: { dekking?: { tekst: string }[] }) {
  if (!dekking?.length) return null;
  const regels = dekking.map((d) => d.tekst);
  const melding = regels.length === 1 ? regels[0] : regels.map((t) => `• ${t}`).join("\n");
  return (
    <span title={melding} aria-label={`Let op: ${regels.join("; ")}`} role="img"
      style={{ color: "var(--neg)", display: "inline-flex", alignItems: "center" }}>
      <Driehoek kleur="currentColor" />
    </span>
  );
}

/** De marge haalt de bedrijfsdrempel niet. Rood: net als een ontbrekende
    feed is dit iets waarop je een beslissing bijstelt, niet een detail. */
export function MargeWaarschuwing({ tekst }: { tekst: string }) {
  return (
    <span title={tekst} aria-label={`Let op: ${tekst}`} role="img"
      style={{ color: "var(--neg)", display: "inline-flex", alignItems: "center",
               verticalAlign: "middle" }}>
      <Driehoek kleur="currentColor" />
    </span>
  );
}

/** Aandachtspunt in de cijfers zelf (rotatie onder target). Amber, zodat rood
    op hetzelfde scherm maar één ding blijft betekenen: er ontbreekt data. */
export function AandachtMarkering({ tekst }: { tekst?: string | null }) {
  return (
    <span title={tekst ?? undefined} aria-label={`Aandachtspunt${tekst ? `: ${tekst}` : ""}`} role="img"
      style={{ color: "var(--warn)", display: "inline-flex", alignItems: "center" }}>
      <Driehoek kleur="currentColor" />
    </span>
  );
}

/** Statusmarkering per artikel: nieuw in het schap, eruit, of twijfel. */
export function StatusBadge({ status, reden }: { status?: string | null; reden?: string | null }) {
  if (!status) return null;
  const stijl: Record<string, { tekst: string; kleur: string }> = {
    nieuw: { tekst: "NIEUW", kleur: "var(--pos)" },
    delisted: { tekst: "DELISTED", kleur: "var(--neg)" },
    "delisted?": { tekst: "DELISTED?", kleur: "var(--warn)" },
  };
  const s = stijl[status];
  if (!s) return null;
  return (
    <span title={reden ?? undefined}
      style={{
        display: "inline-block", fontSize: 9.5, fontWeight: 700, letterSpacing: "0.1em",
        padding: "1px 6px", borderRadius: 3, whiteSpace: "nowrap",
        color: s.kleur, border: `1px solid ${s.kleur}`,
      }}>{s.tekst}</span>
  );
}

/** Alle signalen van één artikel op een eigen regel boven de naam.
    Ze sluiten elkaar niet uit: een nieuw artikel waarvan een land niet meer
    aanlevert hoort beide markeringen te tonen, elk met een eigen uitleg.
    De dekkingsdriehoek staat vooraan — die zegt iets over de betrouwbaarheid
    van alles wat erachter staat. */
export function ArtikelSignalen({ status, reden, dekking }:
  { status?: string | null; reden?: string | null; dekking?: { tekst: string }[] }) {
  if (!status && !dekking?.length) return null;
  return (
    <span style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, marginBottom: 3 }}>
      <DekkingWaarschuwing dekking={dekking} />
      <StatusBadge status={status} reden={reden} />
    </span>
  );
}

/** ?-icoontje met uitleg bij een veldlabel.
 *
 *  Geen native `title`-tooltip: die reageert niet op tikken/tappen (geen
 *  touch-apparaat vuurt een title-tooltip af) en vereist minutieus
 *  stilhouden van de muis — een klik die niets laat zien voelt dan als
 *  "leeg". In plaats daarvan een echte knop met een popover die naar
 *  `document.body` portaalt: dat omzeilt zowel `overflow:hidden` op de
 *  tabellen waar de meeste Uitleg-icoontjes in staan als de uppercase/
 *  letter-spacing die tabelkoppen op hun inhoud zetten (portaal-content
 *  erft niet van zijn React-ouder, maar van waar hij in de DOM landt).
 *  Hover toont hem op desktop; klik/tap zet hem "vast" (blijft staan ook
 *  als de muis weggaat), dus werkt ook gegarandeerd op touch. Hover en
 *  vastzetten zijn bewust APARTE state: bij een klik is de muis al over
 *  het icoontje (dat vuurt eerst een hover), en één gecombineerde
 *  aan/uit-vlag zou een klik-na-hover meteen weer dichttoggelen — precies
 *  het geflikker dat een simpele toggle hier zou veroorzaken. Sluit bij
 *  klik ernaast, Escape of scrollen. */
export function Uitleg({ tekst }: { tekst: string }) {
  const [hover, setHover] = useState(false);
  const [vast, setVast] = useState(false);
  const open = hover || vast;
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const knopRef = useRef<HTMLButtonElement>(null);
  const bolRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !knopRef.current) return;
    const icoon = knopRef.current.getBoundingClientRect();
    const bol = bolRef.current;
    const breedte = bol?.offsetWidth ?? 240;
    const hoogte = bol?.offsetHeight ?? 40;
    const marge = 10;
    let left = icoon.left + icoon.width / 2 - breedte / 2;
    left = Math.max(marge, Math.min(left, window.innerWidth - breedte - marge));
    // Onder het icoon, tenzij dat niet meer past — dan erboven.
    const onder = icoon.bottom + 8;
    const boven = icoon.top - hoogte - 8;
    const top = onder + hoogte > window.innerHeight - marge && boven > marge ? boven : onder;
    setPos({ left, top });
  }, [open, tekst]);

  useEffect(() => {
    if (!open) return;
    const sluit = (e: MouseEvent) => {
      const doel = e.target as Node;
      if (knopRef.current?.contains(doel) || bolRef.current?.contains(doel)) return;
      setHover(false); setVast(false);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setHover(false); setVast(false); }
    };
    const scroll = () => { setHover(false); setVast(false); };
    document.addEventListener("mousedown", sluit);
    document.addEventListener("keydown", escape);
    window.addEventListener("scroll", scroll, true);
    return () => {
      document.removeEventListener("mousedown", sluit);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [open]);

  useEffect(() => { if (!open) setPos(null); }, [open]);

  return (
    <>
      <button type="button" ref={knopRef} aria-label={`Uitleg: ${tekst}`}
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setVast((v) => !v); }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 14, height: 14, marginLeft: 5, borderRadius: "50%", padding: 0,
          border: "1px solid var(--t-fg3)", color: "var(--t-fg3)", background: "transparent",
          fontSize: 9.5, fontWeight: 700, lineHeight: 1, cursor: "help",
          verticalAlign: "-2px",
        }}>?</button>
      {open && createPortal(
        <div ref={bolRef} role="tooltip" className="uitleg-bol" style={{
          left: pos?.left ?? -9999, top: pos?.top ?? -9999,
          visibility: pos ? "visible" : "hidden",
        }}>{tekst}</div>,
        document.body,
      )}
    </>
  );
}

/* ---------------------------------------------------------------- thema */

const THEMA_OPTIES: { modus: ThemaModus; label: string; titel: string; icoon: JSX.Element }[] = [
  {
    modus: "system", label: "Systeem", titel: "Volg de instelling van je computer",
    icoon: (<><rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" /></>),
  },
  {
    modus: "light", label: "Licht", titel: "Altijd het lichte thema",
    icoon: (<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" /></>),
  },
  {
    modus: "dark", label: "Donker", titel: "Altijd het donkere thema",
    icoon: (<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />),
  },
];

/** Licht/donker kiezen. De keuze staat in localStorage, dus hij geldt voor
 *  dit apparaat en overleeft uitloggen en de browser sluiten. */
export function ThemaKeuze() {
  const [modus, setModus] = useState<ThemaModus>(leesModus);
  const [thema, setThema] = useState(() => bepaalThema(leesModus()));

  useEffect(() => {
    setThema(pasToe(modus));
    bewaarModus(modus);
    // Alleen in 'systeem' hoeft er meegeluisterd te worden: wisselt de
    // computer van licht naar donker, dan wisselt de app mee.
    if (modus !== "system") return;
    return volgSysteem(() => setThema(pasToe("system")));
  }, [modus]);

  return (
    <div className="card">
      <div className="kpi-label" style={{ marginBottom: 12 }}>Thema</div>
      <div className="seg" role="group" aria-label="Thema">
        {THEMA_OPTIES.map((o) => (
          <button key={o.modus} title={o.titel} onClick={() => setModus(o.modus)}
            className={modus === o.modus ? "on" : ""} aria-pressed={modus === o.modus}
            style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {o.icoon}
            </svg>
            {o.label}
          </button>
        ))}
      </div>
      <p className="sub" style={{ marginTop: 10 }}>
        {modus === "system"
          ? `Volgt je computer — nu ${thema === "dark" ? "donker" : "licht"}.`
          : "Vaste keuze, ongeacht wat je computer doet."}
        {" "}Geldt voor deze browser en blijft staan na uitloggen.
      </p>
    </div>
  );
}
