import { useEffect, useState } from "react";
import { Milestone, apiSend, fmtEur, fmtNum, merkKleur } from "../api";
import { ShellCtx } from "../App";
import { BrandDot, DatagatMelding, DeltaTag, EmptyProfileCard, LevelStrip, LoadState, MultiChips, OmzeteffectKaart, Sparkline, TijdlijnPanelen, TrendChart, Uitleg, useApi } from "../components/shared";

export type Verdeling = {
  label: string; merk?: string; waarde: number;
  winkels?: number | null; target?: number | null;
};

function KpiCard({ label, tag, tagAccent, value, sub, breakdown, isEuro, deltaPct, vorigePeriode, pWord }: {
  label: string; tag: string; tagAccent?: boolean; value: string; sub?: string;
  breakdown?: Verdeling[]; isEuro?: boolean;
  /** Vergelijking met de kalenderperiode direct ervoor — géén cijfer bij een
   *  gat vóór de laatste periode, dan zou het als "vorige week" uitlezen
   *  terwijl het een oudere periode is (zie engine/analytics.dashboard). */
  deltaPct?: number | null; vorigePeriode?: string | null; pWord?: string;
}) {
  const max = Math.max(1, ...(breakdown ?? []).map((b) => b.waarde));
  return (
    <div className="card">
      <div className="kpi-label">{label}
        <span style={{ display: "inline-flex", gap: 6 }}>
          {deltaPct !== undefined && (
            <DeltaTag pct={deltaPct}
              titel={vorigePeriode ? `Vs. ${pWord?.toLowerCase()} ${vorigePeriode}` : undefined} />
          )}
          <span className={`tag ${tagAccent ? "accent" : ""}`}>{tag}</span>
        </span>
      </div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
      {breakdown?.map((b) => (
        <div key={b.label} style={{ marginTop: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
            <span>{b.label}{b.winkels ? ` · ${b.winkels} winkels` : ""}</span>
            <span>
              {isEuro ? fmtEur(b.waarde) : fmtNum(b.waarde)}
              {b.target != null && (
                // Het ingestelde target uit Instellingen, met kleur boven/onder.
                <span className={b.waarde >= b.target ? "sig-green" : "sig-red"}
                  title={`Target ${fmtEur(b.target)} per winkel`}>
                  {" "}/ {fmtEur(b.target)}
                </span>
              )}
            </span>
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(b.waarde / max) * 100}%`, background: merkKleur(b.label) }} />
          </div>
        </div>
      ))}
    </div>
  );
}


/** Een YTD-kaart waarop élk percentage naast zijn eigen twee bedragen staat.
 *
 *  Gemeld vanaf het scherm: "€ 4.419.442 tegen € 1.841.919, +29,2%" — die
 *  drie getallen rijmen niet. Het percentage stond op de VERGELIJKBARE basis
 *  (per merk alleen het venster dat beide jaren leveren) terwijl de bedragen
 *  de volledige totalen waren. Beide kloppen, maar samen op één kaart leest
 *  het als een rekenfout — en een cijfer dat je niet kunt narekenen vertrouw
 *  je terecht niet.
 *
 *  Nu: het totaalpercentage staat bij de totalen, en zodra de vergelijkbare
 *  basis daarvan afwijkt komt die er als eigen regel onder, mét bedragen.
 *  Zijn ze gelijk (feed dekt beide jaren even ver), dan is er niets uit te
 *  leggen en blijft de kaart zoals hij was. */
function YtdKaart({ titel, blok, y, fmt, pWord, extraTag }: {
  titel: string; blok: any; y: any; fmt: (v: any) => string;
  pWord: string; extraTag?: React.ReactNode;
}) {
  const v = blok.vergelijkbaar;
  // Afronden vóór vergelijken: 29,15 en 29,24 tonen allebei "29,2%", en dan
  // twee regels tonen die hetzelfde zeggen is ruis.
  const zelfde = blok.delta_pct == null || blok.totaal_delta_pct == null
    ? blok.delta_pct === blok.totaal_delta_pct
    : Math.round(blok.delta_pct * 10) === Math.round(blok.totaal_delta_pct * 10);
  return (
    <div className="card">
      <div className="kpi-label">{titel}
        <span style={{ display: "inline-flex", gap: 6 }}>
          {extraTag}
          <DeltaTag pct={blok.totaal_delta_pct} />
        </span>
      </div>
      <div className="kpi-value">{fmt(blok.nu)}</div>
      <VorigJaar y={y} veld={titel.toLowerCase().startsWith("volume") ? "volume" : "omzet"}
        fmt={fmt} pWord={pWord} />
      {!zelfde && v && (
        <div className="kpi-sub" style={{ marginTop: 6 }}>
          Op vergelijkbare basis <b>{blok.delta_pct == null ? "—"
            : `${blok.delta_pct > 0 ? "+" : ""}${blok.delta_pct.toLocaleString("nl-NL")}%`}</b>:{" "}
          {fmt(v.nu)} tegen {fmt(v.vorig)}
          <Uitleg tekst={`Per merk telt alleen het venster waarin BEIDE jaren data hebben. Een merk dat vorig jaar nog niet in de feed zat, of een ${pWord.toLowerCase()} die maar in één van beide jaren geleverd is, valt daarbuiten — anders leest "een merk erbij" als groei en "een vergeten kwartaal" als daling. Het percentage bovenaan is de kale verhouding tussen de twee totalen hierboven.`} />
        </div>
      )}
    </div>
  );
}

/** Heeft dit jaar geen enkele periode gemeen met vorig jaar? Dan is elk
 *  "vorig jaar"-getal in het YTD-venster nul, en zou "€ 0" lezen als "niets
 *  verkocht" terwijl de data er wel is, alleen in andere weken. */
function geenOverlap(y: any) {
  return y.basis && !y.basis.vergelijkbaar.length && y.per_merk?.length > 0;
}

/** [17,18,19,25] -> "17 t/m 19 en 25" — compact, zoals je het zou zeggen. */
function reeks(nummers: number[]) {
  const delen: string[] = [];
  for (let i = 0; i < nummers.length; i++) {
    let j = i;
    while (j + 1 < nummers.length && nummers[j + 1] === nummers[j] + 1) j++;
    delen.push(j > i ? `${nummers[i]} t/m ${nummers[j]}` : `${nummers[i]}`);
    i = j;
  }
  return delen.length > 1
    ? `${delen.slice(0, -1).join(", ")} en ${delen[delen.length - 1]}`
    : delen[0] ?? "";
}

/** "week 26 t/m 31" of "t/m week 31" als het bij het begin aansluit; mist er
 *  binnen het venster iets (een niet-geladen kwartaal), dan staat dat erbij —
 *  die periodes tellen in geen van beide jaren mee. */
function venster(v: any, pWord: string) {
  const p = pWord.toLowerCase();
  const basis = v.van_periode > 1
    ? `${p} ${v.van_periode} t/m ${v.tot_periode}`
    : `t/m ${p} ${v.tot_periode}`;
  return v.ontbrekend?.length
    ? `${basis}, zonder ${p} ${reeks(v.ontbrekend)}`
    : basis;
}

/** De "vorig jaar"-regel onder een YTD-kaart. Zonder overlap staat er geen
 *  nul maar wat vorig jaar wél dekt — de vraag die een lege kolom oproept. */
function VorigJaar({ y, veld, fmt, pWord }:
  { y: any; veld: "omzet" | "volume"; fmt: (v: any) => string; pWord: string }) {
  const vorig = y.jaar - 1;
  if (!geenOverlap(y)) {
    return <div className="kpi-sub">{vorig}: {fmt(y[veld].vorig)}</div>;
  }
  const d = y.dekking?.[vorig];
  return (
    <div className="kpi-sub">
      {vorig}: —
      {d && <> · dekt {pWord.toLowerCase()} {d.van} t/m {d.tot}, buiten dit venster</>}
    </div>
  );
}

const MAANDEN = ["", "jan", "feb", "mrt", "apr", "mei", "jun",
  "jul", "aug", "sep", "okt", "nov", "dec"];


/** Omzet per winkel over tijd, met het winkelbestand eronder. Een stijgend
 *  gemiddelde kan van beter verkopen komen of van minder winkels; de
 *  decompositie eronder splitst dat exact. */
function TijdlijnBlok({ t, pWord }: { t: any; pWord: string }) {
  const [alles, setAlles] = useState(false);
  const reeksen = alles ? [{ ...t.totaal, merk: "TOTAAL" }] : t.per_merk;
  const d = t.decompositie;
  const aangenomen = t.per_merk.some((r: any) => r.bron.includes("aangenomen"));
  const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toLocaleString("nl-NL")}%`;
  return (
    <>
      <hr className="hairline" />
      <h2>Omzet per winkel over tijd</h2>
      <p className="sub" style={{ marginTop: -6 }}>
        Boven de gemiddelde omzet per winkel, eronder het aantal winkels — zelfde
        tijdas, zelfde kleur per merk. Loopt de bovenste lijn op terwijl de onderste
        zakt, dan komt de stijging van een kleiner winkelbestand en niet van betere verkoop.
        {t.venster > 1 && ` Het winkelaantal is een voortschrijdend gemiddelde over ${t.venster} ${pWord.toLowerCase()}en, omdat een losse ${pWord.toLowerCase()} bij langzame merken te veel ruis geeft.`}
      </p>
      <div className="seg" style={{ margin: "10px 0 14px" }}>
        <button className={!alles ? "on" : ""} onClick={() => setAlles(false)}>Per merk</button>
        <button className={alles ? "on" : ""} onClick={() => setAlles(true)}>Totaal</button>
      </div>
      <div className="card">
        <TijdlijnPanelen periodes={t.periodes} reeksen={reeksen} isMaand={pWord === "Maand"} />
      </div>

      {d?.per_merk?.length > 0 && t.vergelijking?.vorig && (
        <div style={{ marginTop: 14 }}>
          <div className="eyebrow">Waar komt het verschil vandaan? {t.vergelijking.nu} vs {t.vergelijking.vorig}</div>
          <table className="data" style={{ marginTop: 8 }}>
            <thead><tr>
              <th>Merk</th>
              <th style={{ textAlign: "right" }}>Omzet</th>
              <th style={{ textAlign: "right" }}>= winkels</th>
              <th style={{ textAlign: "right" }}>× per winkel</th>
              <th>Winkels toen → nu</th>
            </tr></thead>
            <tbody>
              {d.per_merk.map((r: any) => (
                <tr key={r.merk}>
                  <td><BrandDot merk={r.merk} />{r.merk}</td>
                  <td style={{ textAlign: "right" }}><DeltaTag pct={r.omzet_pct} /></td>
                  <td style={{ textAlign: "right" }}><DeltaTag pct={r.winkels_pct} /></td>
                  <td style={{ textAlign: "right" }}><DeltaTag pct={r.per_winkel_pct} /></td>
                  <td className="sub">{r.winkels_toen} → {r.winkels_nu}</td>
                </tr>
              ))}
              {d.totaal && (
                <tr>
                  <td><b>Totaal</b></td>
                  <td style={{ textAlign: "right" }}><DeltaTag pct={d.totaal.omzet_pct} /></td>
                  <td style={{ textAlign: "right" }}><DeltaTag pct={d.totaal.winkels_pct} /></td>
                  <td style={{ textAlign: "right" }}><DeltaTag pct={d.totaal.per_winkel_pct} /></td>
                  <td className="sub">{d.totaal.winkels_toen} → {d.totaal.winkels_nu}</td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="sub" style={{ marginTop: 8 }}>
            De drie kolommen sluiten exact op elkaar aan: omzet = winkels × omzet per winkel
            {d.per_merk[0] && ` (${d.per_merk[0].merk}: ${pct(d.per_merk[0].omzet_pct)} = ${pct(d.per_merk[0].winkels_pct)} × ${pct(d.per_merk[0].per_winkel_pct)})`}.
          </p>
        </div>
      )}

      {aangenomen && (
        <p className="sub" style={{ marginTop: 10 }}>
          Gestippeld deel: daar is nog geen gemeten winkelaantal, dus er wordt met het
          oudst bekende getal gerekend. Voeg metingen met datum toe bij Instellingen om
          dat deel hard te maken.
        </p>
      )}
    </>
  );
}

/** Winkels zonder omzet in de laatste periode(n) — gestopt of nog signaal.
 *
 *  De sparkline per rij laat zien of het verval abrupt was (gestaag verkopen,
 *  dan ineens stil — echt signaal) of dat de winkel altijd al hakkelde. Ze
 *  staat hier en niet in elke tabel: pas op een kórte lijst is hij leesbaar,
 *  en de ritmefilter houdt de lijst kort. */
function StilTabel({ rijen, w, pWord, naam, leeg }: {
  rijen: any[]; w: any; pWord: string; naam: (n: number | null) => string; leeg: string;
}) {
  const [alles, setAlles] = useState(false);
  const TOON = 25;
  const zicht = alles ? rijen : rijen.slice(0, TOON);
  const reeks = (g: any) => {
    const uit: Record<number, number> = {};
    for (const [k, v] of Object.entries(g.reeks ?? {})) uit[Number(k)] = v as number;
    return uit;
  };
  return (
    <>
    <table className="data">
      <thead><tr>
        <th>Winkel</th><th>Merk</th><th>Verloop {w.jaar}</th>
        <th>Laatste omzet</th>
        <th>Zonder omzet<Uitleg tekst={`Gemeten tegen het eigen ritme van de winkel: de drempel uit Instellingen is de ondergrens, en daarbovenop moet de stilte minstens 3x zo lang zijn als de normale tussenpoos tussen twee ${pWord.toLowerCase()}en met verkoop (2x voor "Let op"). Een winkel die om de drie ${pWord.toLowerCase()}en iets verkoopt is na zes stille ${pWord.toLowerCase()}en dus niet gestopt — dat is zijn patroon.`} /></th>
        <th style={{ textAlign: "right" }}>Omzet {w.jaar}</th>
        <th style={{ textAlign: "right" }} title={`Wat deze winkel in dezelfde ${pWord.toLowerCase()}en van ${w.jaar - 1} verkocht; zonder ${w.jaar - 1} een schatting op het eigen verkoopritme (±)`}>
          Gemist
        </th>
      </tr></thead>
      <tbody>
        {zicht.map((g) => (
          <tr key={`${g.winkel_id}-${g.merk}`}>
            <td>{g.winkel_naam ?? g.winkel_id}</td>
            <td>{g.merk}</td>
            <td>{g.reeks ? (
              <Sparkline ytd={reeks(g)} lytd={{}} isEuro
                periodWord={pWord} jaar={w.jaar} />
            ) : <span className="sub">—</span>}</td>
            <td>{g.laatste_maand == null ? `niets in ${w.jaar}` : naam(g.laatste_maand)}</td>
            <td>
              {g.maanden_zonder_omzet} {pWord.toLowerCase()}{g.maanden_zonder_omzet === 1 ? "" : "en"}
              {g.ritme > 1 && (
                <span className="sub"> · ritme {g.ritme}
                  <Uitleg tekst={
                    `"Ritme" is hoe vaak deze winkel normaal verkoopt: elke ${g.ritme} `
                    + `${pWord.toLowerCase()}en. Dat is de mediane tussenpoos tussen `
                    + `${pWord.toLowerCase()}en mét omzet dit jaar. De stilte-drempel `
                    + `schaalt hiermee mee (zie kolomkop) — pas na ${3 * g.ritme} stille `
                    + `${pWord.toLowerCase()}en (2× ${2 * g.ritme} voor "Let op") is dit `
                    + `voor déze winkel afwijkend, niet bij haar eigen normale patroon.`
                  } />
                </span>
              )}
            </td>
            <td style={{ textAlign: "right" }}>{fmtEur(g.omzet_dit_jaar)}</td>
            <td style={{ textAlign: "right" }}>
              {g.gemist_bron === "geschat" ? "± " : ""}{fmtEur(g.gemist_zelfde_venster)}
            </td>
          </tr>
        ))}
        {!rijen.length && <tr><td colSpan={7} className="sub">{leeg}</td></tr>}
      </tbody>
    </table>
    {rijen.length > TOON && (
      <button className="chip off" style={{ marginTop: 8 }}
        onClick={() => setAlles(!alles)}>
        {alles ? `toon de eerste ${TOON}` : `toon alle ${rijen.length}`}
      </button>
    )}
    </>
  );
}

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
        “Gemist” is wat de winkel in dezelfde {pWord.toLowerCase()}en van {w.jaar - 1} verkocht;
        is {w.jaar - 1} niet geladen, dan een schatting (±) op het eigen verkoopritme.
      </p>

      {w.historie_ontbreekt?.length > 0 && (
        // Zonder vorig jaar zou élke winkel als 'nieuw' gelden; dat is een
        // gat in de data, geen waarneming.
        <div className="level-strip" style={{ marginTop: 14 }}>
          <span className="sub">
            Van {w.historie_ontbreekt.join(" en ")} is {w.jaar - 1} niet geladen —
            nieuwe winkels zijn voor {w.historie_ontbreekt.length > 1 ? "die merken" : "dat merk"} niet
            te bepalen. Importeer het bestand van {w.jaar - 1} om de vergelijking compleet te maken.
          </span>
        </div>
      )}

      <div className="level-strip" style={{ borderLeft: "3px solid var(--neg)", marginTop: 14 }}>
        <span><b>Actiepunt.</b> {w.actiepunt}</span>
      </div>

      {/* Geen haakjes in koppen: het displayfont vervangt ze door een ornament. */}
      <h3 style={{ marginTop: 18 }}>
        Gestopte winkels · {w.gestopt.length} — gemiste omzet {fmtEur(w.gemiste_omzet)}
      </h3>
      <p className="sub" style={{ marginTop: -6 }}>
        Stilte van minstens {w.gestopt_vanaf} {pWord.toLowerCase()}en
        (Instellingen → Stille winkels) én minstens 3× het eigen
        verkoopritme van die winkel.
      </p>
      <StilTabel rijen={w.gestopt} w={w} pWord={pWord} naam={naam}
        leeg="Geen winkels stilgevallen — elke winkel draait nog omzet." />

      <h3 style={{ marginTop: 22 }}>Let op · {w.signalen.length}</h3>
      <p className="sub" style={{ marginTop: -6 }}>
        Stilte van minstens {w.letop_vanaf} {pWord.toLowerCase()}en én 2× het
        eigen ritme — nog geen actie, wel in de gaten houden.
      </p>
      <StilTabel rijen={w.signalen} w={w} pWord={pWord} naam={naam}
        leeg={`Geen winkels met één lege ${pWord.toLowerCase()}.`} />

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

export default function Dashboard({ ctx }: { ctx: ShellCtx }) {
  const [merk, setMerk] = useState<string[]>([]);
  const [land, setLand] = useState<string[]>([]);
  const [banner, setBanner] = useState<string[]>([]);
  const [metric, setMetric] = useState<"omzet" | "volume" | "per_winkel">("omzet");
  // Uitsplitsing van de tegels: totaal (per merk, zoals altijd), per formule
  // of per land. Zie DIM_LABEL hieronder voor de naamgeving.
  const [dim, setDim] = useState<"merk" | "banner" | "land">("merk");

  // Filters horen bij één retailer: bij het wisselen van tab zou een merk
  // dat de nieuwe retailer niet voert anders een leeg dashboard opleveren.
  useEffect(() => { setMerk([]); setLand([]); setBanner([]); setDim("merk"); }, [ctx.retailer]);

  const q = new URLSearchParams();
  if (merk.length) q.set("merk", merk.join(","));
  if (land.length) q.set("land", land.join(","));
  if (banner.length) q.set("banner", banner.join(","));
  const { data, error, reload } = useApi(`/${ctx.retailer}/dashboard?${q}`);
  // Mijlpalen volgen het merkfilter: staat er een merk aan, dan hoor je
  // alleen de mijlpalen van dat merk te zien — anders verklaart een markering
  // een piek die in deze selectie niet bestaat. Zonder filter komt alles mee.
  const { data: mijlpalen, reload: herlaadMijlpalen } = useApi<Milestone[]>(
    `/${ctx.retailer}/milestones${merk.length ? `?merk=${merk.join(",")}` : ""}`);

  if (!data) return <LoadState error={error} reload={reload} />;
  if (!data.available) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const pWord = data.periode_type === "maand" ? "Maand" : "Week";
  if (data.empty) {
    // gefilterd: er is wél data, alleen niet voor deze filterkeuze — dan
    // moeten de chips bedienbaar blijven, anders zit de gebruiker vast.
    const f = data.filters;
    return (<>
      <h1>Dashboard — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer} />
      {data.gefilterd && f ? (<>
        <div style={{ display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap", margin: "16px 0 4px" }}>
          {f.merk.length > 0 && (<span><span className="eyebrow">Merk </span><MultiChips all={f.merk} sel={merk} onChange={setMerk} /></span>)}
          {f.land.length > 0 && (<span><span className="eyebrow">Land </span><MultiChips all={f.land} sel={land} onChange={setLand} /></span>)}
          {f.banner.length > 0 && (<span><span className="eyebrow">Formule </span><MultiChips all={f.banner} sel={banner} onChange={setBanner} /></span>)}
        </div>
        <div className="card empty-card">
          <p className="sub">Geen data voor deze filterkeuze — deze combinatie van merk, land en formule komt niet voor.</p>
          <button className="btn ghost" onClick={() => { setMerk([]); setLand([]); setBanner([]); }}>Filters wissen</button>
        </div>
      </>) : (
        <div className="card empty-card"><p className="sub">Nog geen data geïmporteerd voor deze retailer.</p></div>
      )}
    </>);
  }

  const k = data.kpi, y = data.ytd;
  // De backend vertelt welke uitsplitsingen deze retailer echt kan leveren;
  // een knop voor een lege dimensie zou alleen "ONBEKEND" tonen.
  const dims: string[] = data.dimensies ?? ["merk"];
  const effDim = dims.includes(dim) ? dim : "merk";
  const verdeling = (kpi: any): Verdeling[] =>
    kpi.breakdowns?.[effDim] ?? kpi.breakdown;
  const filters = data.filters;
  // Gaten in de aanlevering horen bij het merk waar ze over gaan: één rode
  // driehoek op de filterchip, met de uitleg bij hover. Meldingen zonder merk
  // (een land dat helemaal stilviel) horen bij geen enkele chip en zouden
  // hier verdwijnen — die blijven onder de grafiek staan als feed-melding.
  const merkWaarschuwing: Record<string, string> = {};
  for (const g of (data.dekkingsgaten ?? []) as any[]) {
    if (!g.merk) continue;
    merkWaarschuwing[g.merk] = merkWaarschuwing[g.merk]
      ? `${merkWaarschuwing[g.merk]}\n${g.tekst}` : g.tekst;
  }
  const hasVolume = data.capabilities?.volume !== false;
  const effMetric = !hasVolume && metric === "volume" ? "omzet" : metric;
  return (
    <>
      <h1>Dashboard — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer} />
      <DatagatMelding retailer={ctx.retailer} go={ctx.go} />

      <div style={{ display: "flex", gap: 22, alignItems: "center", flexWrap: "wrap", margin: "16px 0 4px" }}>
        {filters.merk.length > 0 && (<span><span className="eyebrow">Merk </span>
          <MultiChips all={filters.merk} sel={merk} onChange={setMerk}
            waarschuwing={merkWaarschuwing} /></span>)}
        {filters.land.length > 0 && (<span><span className="eyebrow">Land </span><MultiChips all={filters.land} sel={land} onChange={setLand} /></span>)}
        {filters.banner.length > 0 && (<span><span className="eyebrow">Formule </span><MultiChips all={filters.banner} sel={banner} onChange={setBanner} /></span>)}
        <span className="sub" style={{ marginLeft: "auto" }}>
          {(merk.length || filters.merk.length)} van {filters.merk.length} merken
        </span>
      </div>

      <h2>Meest recente {pWord.toLowerCase()} <span className="kop-data">{data.laatste_periode}</span></h2>
      {data.laatste_periode_compleet === false && (
        // Een halve periode als volledige tonen laat de omzet kelderen en
        // maakt de YoY-vergelijking oneerlijk.
        <p className="sub" style={{ marginTop: -8 }}>
          Let op: {pWord.toLowerCase()} {data.laatste_periode} loopt nog. De cijfers
          hieronder zijn een tussenstand; de YTD-vergelijking rekent daarom t/m
          {" " + pWord.toLowerCase()} {data.ytd.tot_periode}.
        </p>
      )}
      {dims.length > 1 && (
        <div className="seg" style={{ margin: "10px 0 14px" }}>
          <button className={effDim === "merk" ? "on" : ""} onClick={() => setDim("merk")}>Totaal</button>
          {dims.includes("banner") && (
            <button className={effDim === "banner" ? "on" : ""} onClick={() => setDim("banner")}>Per formule</button>
          )}
          {dims.includes("land") && (
            <button className={effDim === "land" ? "on" : ""} onClick={() => setDim("land")}>Per land</button>
          )}
        </div>
      )}
      <div className="grid kpi">
        <KpiCard label="Omzet" tag={data.laatste_periode_compleet === false ? "LOPEND" : pWord.toUpperCase()}
          tagAccent={data.laatste_periode_compleet === false} isEuro
          value={fmtEur(k.omzet.waarde)} breakdown={verdeling(k.omzet)}
          deltaPct={k.omzet.delta_pct} vorigePeriode={k.omzet.vorige_periode} pWord={pWord} />
        {hasVolume && <KpiCard label="Volume"
          tag={data.laatste_periode_compleet === false ? "LOPEND" : pWord.toUpperCase()}
          tagAccent={data.laatste_periode_compleet === false}
          value={fmtNum(k.volume.waarde)} breakdown={verdeling(k.volume)}
          deltaPct={k.volume.delta_pct} vorigePeriode={k.volume.vorige_periode} pWord={pWord} />}
        <KpiCard label="Omzet per winkel" tag={k.omzet_per_winkel.schatting ? "SCHATTING" : "WINKEL"}
          tagAccent={k.omzet_per_winkel.schatting}
          value={fmtEur(k.omzet_per_winkel.waarde)} isEuro
          breakdown={verdeling(k.omzet_per_winkel)}
          deltaPct={k.omzet_per_winkel.delta_pct} vorigePeriode={k.omzet_per_winkel.vorige_periode} pWord={pWord}
          sub={k.omzet_per_winkel.winkels
            // Bij een SCHATTING komt het aantal uit Instellingen; "met omzet"
            // zou dan een telling suggereren die er niet is.
            ? k.omzet_per_winkel.schatting
              ? `${k.omzet_per_winkel.winkels} winkels (handmatig ingesteld)`
              : `${k.omzet_per_winkel.winkels} winkels met omzet in ${y.jaar}`
            : "Geen winkelaantal ingesteld"} />
      </div>

      <hr className="hairline" />
      <h2>YTD {y.jaar} <span className="kop-data">t/m</span> {pWord.toLowerCase()} {y.tot_periode} vs {y.jaar - 1}</h2>
      <div className="grid kpi">
        <YtdKaart titel="Omzet YTD" blok={y.omzet} y={y} fmt={fmtEur} pWord={pWord} />
        {hasVolume && (
          <YtdKaart titel="Volume YTD" blok={y.volume} y={y}
            fmt={(v: any) => fmtNum(v)} pWord={pWord} />
        )}
        <div className="card">
          <div className="kpi-label">Omzet / winkel YTD
            <span style={{ display: "inline-flex", gap: 6 }}>
              {y.omzet_per_winkel.schatting && <span className="tag accent">SCHATTING</span>}
              <DeltaTag pct={y.omzet_per_winkel.delta_pct} />
            </span>
          </div>
          <div className="kpi-value">{fmtEur(y.omzet_per_winkel.nu)}</div>
          <div className="kpi-sub">{y.jaar - 1}: {geenOverlap(y) ? "—" : fmtEur(y.omzet_per_winkel.vorig)}</div>
        </div>
      </div>
      {y.per_merk?.length > 0 && (
        // Per merk op regelniveau: elk merk vergeleken binnen zijn EIGEN
        // venster, zodat een kortere feed geen schijnbare daling wordt.
        <div className="tablewrap" style={{ overflowX: "auto" }}>
          <table className="data" style={{ marginTop: 6 }}>
            <thead><tr>
              <th>Merk</th>
              <th style={{ textAlign: "right" }}>Omzet {y.jaar}</th>
              <th style={{ textAlign: "right" }}>Omzet {y.jaar - 1}</th>
              <th>Δ</th>
              {hasVolume && <>
                <th style={{ textAlign: "right" }}>Volume {y.jaar}</th>
                <th style={{ textAlign: "right" }}>Volume {y.jaar - 1}</th>
                <th>Δ</th>
              </>}
            </tr></thead>
            <tbody>
              {y.per_merk.map((m: any) => (
                <tr key={m.merk ?? "ONBEKEND"}>
                  <td>
                    <BrandDot merk={m.merk} />{m.merk ?? "ONBEKEND"}
                    {m.vergelijkbaar && (m.van_periode > 1 || m.tot_periode !== y.tot_periode
                      || m.ontbrekend?.length > 0) && (
                      <span className="sub"> · {venster(m, pWord)}</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>{fmtEur(m.omzet.nu)}</td>
                  <td style={{ textAlign: "right" }}>
                    {m.vergelijkbaar || m.omzet.vorig ? fmtEur(m.omzet.vorig) : "—"}</td>
                  <td>{m.vergelijkbaar
                    ? <DeltaTag pct={m.omzet.delta_pct} />
                    : <span className="tag" title={`Niet te vergelijken: ${m.reden}`}>{m.reden}</span>}</td>
                  {hasVolume && <>
                    <td style={{ textAlign: "right" }}>{fmtNum(m.volume.nu)}</td>
                    <td style={{ textAlign: "right" }}>
                      {m.vergelijkbaar || m.volume.vorig ? fmtNum(m.volume.vorig) : "—"}</td>
                    <td>{m.vergelijkbaar
                      ? <DeltaTag pct={m.volume.delta_pct} />
                      : <span className="tag">—</span>}</td>
                  </>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {y.basis && !y.basis.volledig && (
        // Merk-feeds met ongelijke historie of actualiteit. De bedragen van de
        // vergelijkbare basis staan op de kaarten zelf (YtdKaart); hier staat
        // waaruit die basis bestaat — welk merk over welk venster meetelt.
        <p className="sub" style={{ marginTop: 8 }}>
          {y.basis.vergelijkbaar.length
            ? <>De vergelijkbare basis bestaat uit: {y.basis.vergelijkbaar.map((v: any) =>
                v.van_periode === 1 && v.tot_periode === y.tot_periode && !v.ontbrekend?.length
                  ? (v.merk ?? "ONBEKEND")
                  : `${v.merk ?? "ONBEKEND"} ${venster(v, pWord)}`
              ).join(", ")}.</>
            : <>Geen vergelijkbare basis: er is geen {pWord.toLowerCase()} die {y.jaar} en {y.jaar - 1} allebei hebben
                {y.dekking?.[y.jaar - 1] && y.dekking?.[y.jaar] &&
                  ` — ${y.jaar - 1} loopt van ${pWord.toLowerCase()} ${y.dekking[y.jaar - 1].van} t/m ${y.dekking[y.jaar - 1].tot}, ${y.jaar} van ${pWord.toLowerCase()} ${y.dekking[y.jaar].van} t/m ${y.dekking[y.jaar].tot}`}.
              </>}
          {(() => {
            // Onderscheid maken tussen "dit merk is er vorig jaar niet" en
            // "het is er wel, maar in andere weken". Die tweede groep is al
            // uitgelegd in de zin hierboven; er nog eens "ontbreekt in 2025"
            // achteraan plakken is simpelweg onwaar.
            const ontbreekt = y.basis.niet_vergelijkbaar.filter((m: string) =>
              (y.per_merk ?? []).some((r: any) => r.merk === m && /^geen \d{4}$/.test(r.reden ?? "")));
            if (!ontbreekt.length) return null;
            const n = ontbreekt.map((m: string) => m ?? "ONBEKEND");
            const namen = n.length === 1 ? n[0]
              : `${n.slice(0, -1).join(", ")} en ${n[n.length - 1]}`;
            return <> {namen} {n.length === 1 ? "ontbreekt" : "ontbreken"} in {y.jaar - 1} en
              {n.length === 1 ? " telt" : " tellen"} daarom niet mee in het percentage — de
              absolute totalen tellen wél alles.</>;
          })()}
        </p>
      )}

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
          isEuro={effMetric !== "volume"} periodWord={pWord}
          mijlpalen={mijlpalen ?? []}
          promoties={data.promoties ?? []}
          // Filtert de gebruiker op merk, dan zijn dát de merken die in beeld
          // zijn; anders alles waar deze retailer data van heeft.
          merken={merk.length ? merk : filters.merk}
          onMijlpaal={async (m) => {
            await apiSend(`/${ctx.retailer}/milestones`, "POST", m);
            herlaadMijlpalen();
          }}
          onMijlpaalWeg={async (id) => {
            await apiSend(`/${ctx.retailer}/milestones/${id}`, "DELETE");
            herlaadMijlpalen();
          }} />
        {(() => {
          // De som zakt vanaf het punt waar een merk-feed stopt; zonder deze
          // melding leest een achterlopende levering als omzetdaling. Maar
          // wat de kaart bovenaan al noemt, hoeft hier niet nóg eens: twee
          // formuleringen van hetzelfde feit op één scherm leest als twee
          // problemen. Eén periode achterlopen meldt de kaart bewust niet
          // (normale levercadans) — die blijft hier dus wél staan, want de
          // lijn zakt er wel degelijk van.
          const gemeld = new Set((data.dekkingsgaten ?? [])
            .filter((g: any) => g.soort === "stopt").map((g: any) => g.merk));
          const rest = (data.trend.feeds_achter ?? []).filter((f: any) => !gemeld.has(f.merk));
          if (!rest.length) return null;
          return (
            <p className="sub" style={{ marginTop: 10 }}>
              Let op: {rest.map((f: any) =>
                `${f.merk ?? "ONBEKEND"} loopt t/m ${f.laatste_periode}`).join("; ")} —
              daarná telt de lijn zonder {rest.length === 1 ? "dat merk" : "die merken"}.
            </p>
          );
        })()}
      </div>

      {data.promoties?.length > 0 && (
        <>
          <h2 style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            Omzeteffect per promotie
            <a className="sub" style={{ cursor: "pointer", textTransform: "none",
                                        letterSpacing: 0, fontFamily: "Montserrat, sans-serif" }}
              onClick={() => ctx.go(ctx.retailer, "promoties")}>
              acties beheren →
            </a>
          </h2>
          {/* Volgt het merkfilter: de markers hierboven zijn al op de
              zichtbare scopes gefilterd, dus de kaart vanzelf ook. */}
          <OmzeteffectKaart rijen={data.promoties} periodWord={pWord} />
        </>
      )}

      {data.tijdlijn?.periodes?.length > 1 && (
        <TijdlijnBlok t={data.tijdlijn} pWord={pWord} />
      )}

      {data.winkelanalyse?.beschikbaar && <Winkelanalyse w={data.winkelanalyse} pWord={pWord} />}
    </>
  );
}
