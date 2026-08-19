import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BRAND_COLORS, apiGet, fmtEur, fmtNum, merkKleur } from "../api";

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

/** Filterchips (merk/land/banner). Leeg = alles; klikken zet aan/uit. */
export function MultiChips({ all, sel, onChange }:
  { all: string[]; sel: string[]; onChange: (v: string[]) => void }) {
  return (
    <span className="chips" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
      {all.map((v) => (
        <button key={v} className={`chip ${sel.includes(v) ? "" : "off"}`}
          aria-pressed={sel.length === 0 || sel.includes(v)}
          onClick={() => onChange(sel.includes(v) ? sel.filter((x) => x !== v) : [...sel, v])}>{v}</button>
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

export function TrendChart({ series, years, isEuro, periodWord }:
  { series: Series; years: number[]; isEuro: boolean; periodWord: string }) {
  const W = 860, H = 260, PAD = 42;
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);

  const nums = Array.from(new Set(years.flatMap((y) => Object.keys(series[y] ?? {}).map(Number)))).sort((a, b) => a - b);
  if (!nums.length) return <p className="sub">Nog geen data.</p>;
  const maxX = Math.max(...nums), minX = Math.min(...nums);
  const maxY = Math.max(1, ...years.flatMap((y) => Object.values(series[y] ?? {})));
  const x = (p: number) => PAD + ((p - minX) / Math.max(1, maxX - minX)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - (v / maxY) * (H - 2 * PAD);
  const colors = ["#BAC3C8", "#7E8D92", "#0E323B"]; // oldest -> newest

  const onMove = (e: React.MouseEvent) => {
    const rect = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const nearest = nums.reduce((a, b) => (Math.abs(x(b) - px) < Math.abs(x(a) - px) ? b : a));
    setHover(nearest);
  };

  const fmt = (v: number) => (isEuro ? fmtEur(v) : fmtNum(Math.round(v)));
  const hoverPct = hover != null ? Math.min(86, Math.max(14, ((x(hover)) / W) * 100)) : 0;

  return (
    <div style={{ position: "relative" }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", cursor: "crosshair" }}
        role="img"
        aria-label={`${isEuro ? "Omzet" : "Volume"} per ${periodWord.toLowerCase()}, jaren ${years.join(", ")}`}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <title>{`${isEuro ? "Omzet" : "Volume"} per ${periodWord.toLowerCase()}, jaar op jaar (${years.join(", ")})`}</title>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={PAD} x2={W - PAD} y1={y(maxY * f)} y2={y(maxY * f)} stroke="#EAEFF1" />
        ))}
        <line x1={PAD} x2={W - PAD} y1={H - PAD} y2={H - PAD} stroke="#BAC3C8" />
        {nums.filter((_, i) => i % Math.ceil(nums.length / 12) === 0).map((p) => (
          <text key={p} x={x(p)} y={H - PAD + 16} textAnchor="middle" fontSize="10.5" fill="#7E8D92">{p}</text>
        ))}
        {[maxY, maxY / 2].map((v, i) => (
          <text key={i} x={PAD - 6} y={y(v) + 3} textAnchor="end" fontSize="10.5" fill="#7E8D92">
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
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD} y2={H - PAD} stroke="#7E8D92" strokeDasharray="3 3" />
            {years.map((yr, i) => series[yr]?.[hover] != null && (
              <circle key={yr} cx={x(hover)} cy={y(series[yr][hover])} r={3.5}
                fill={colors[colors.length - years.length + i]} />
            ))}
          </g>
        )}
      </svg>
      {hover != null && (
        <div className="tooltip" style={{ left: `${hoverPct}%`, top: 8 }}>
          <b>{periodWord} {hover}</b>
          {years.map((yr) => (
            <div key={yr}>{yr}: {series[yr]?.[hover] != null ? fmt(series[yr][hover]) : "—"}</div>
          ))}
        </div>
      )}
      <div className="sub" style={{ display: "flex", gap: 16, marginTop: 6 }}>
        {years.map((yr, i) => (
          <span key={yr}><span style={{ display: "inline-block", width: 14, height: 2, background: colors[colors.length - years.length + i], verticalAlign: "middle", marginRight: 5 }} />{yr}</span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Sparkline */

export function Sparkline({ ytd, lytd, isEuro, periodWord }:
  { ytd: Record<number, number>; lytd: Record<number, number>; isEuro: boolean; periodWord: string }) {
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
        <path d={path(lytd)} fill="none" stroke="#BAC3C8" strokeWidth="1.2" strokeDasharray="3 3" />
        <path d={path(ytd)} fill="none" stroke="#0E323B" strokeWidth="1.5" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke="#7E8D92" strokeDasharray="2 2" />}
      </svg>
      {hover != null && (
        <span className="tooltip" style={{ left: x(hover), top: -46 }}>
          <b>{periodWord} {hover}</b><br />
          2026: {fmt(ytd[hover])} · 2025: {fmt(lytd[hover])}
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

        <text x={PAD} y={12} fontSize="10.5" fill="#64777D" letterSpacing="0.12em">OMZET PER WINKEL</text>
        {[0.5, 1].map((f) => (
          <line key={f} x1={PAD} x2={W - 14} y1={yTop(maxTop * f)} y2={yTop(maxTop * f)} stroke="#EAEFF1" />
        ))}
        {[maxTop, maxTop / 2].map((v, i) => (
          <text key={i} x={PAD - 6} y={yTop(v) + 3} textAnchor="end" fontSize="10.5" fill="#7E8D92">
            {v >= 10000 ? "€" + Math.round(v / 1000) + "k" : fmtEur(v)}
          </text>
        ))}

        <text x={PAD} y={HB + GAP + 4} fontSize="10.5" fill="#64777D" letterSpacing="0.12em">AANTAL WINKELS</text>
        <line x1={PAD} x2={W - 14} y1={yBot(minBot)} y2={yBot(minBot)} stroke="#EAEFF1" />
        {[maxBot, minBot].map((v, i) => (
          <text key={i} x={PAD - 6} y={yBot(v) + 3} textAnchor="end" fontSize="10.5" fill="#7E8D92">
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
            stroke="#0E323B" strokeWidth={0.8} opacity={0.35} />
        )}
        {labelIdx.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="#7E8D92">
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
