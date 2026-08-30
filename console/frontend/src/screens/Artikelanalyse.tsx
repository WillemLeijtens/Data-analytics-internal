import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmtEur, fmtNum, fmtPeriode } from "../api";
import { ShellCtx } from "../App";
import { ArtikelSignalen, BrandDot, DeltaTag, EmptyProfileCard, LevelStrip, LoadState, MultiChips, Sparkline, TrendChart, Uitleg, useApi } from "../components/shared";

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
  // Beide soorten signalen tellen mee. Stond hier alleen `a.status`, dan viel
  // een artikel met enkel een datagat buiten het aantal én uit de lijst zodra
  // de chip aan stond — precies de melding die dan verdween.
  const gemarkeerd = data.artikelen.filter((a: any) => a.status || a.dekking?.length);
  const zichtbaar = alleenStatus ? gemarkeerd : data.artikelen;
  const chosen = zichtbaar.find((a: any) => a.ean === sel);
  const fmt = (v: number) => (isEuro ? fmtEur(v) : fmtNum(v));
  const toSeries = (spark: any, key: string) =>
    Object.fromEntries(Object.entries(spark).map(([p, v]: any) => [p, v[key]]));
  // Distributie = het aantal winkels dat het artikel die periode verkocht
  // heeft. Alleen te tellen als de feed winkelniveau levert; anders blijven
  // de kolommen wég in plaats van leeg (vandaag: wel Etos, niet Kruidvat/ICI).
  const dist = !!data.distributie_beschikbaar;
  const pw = pWord.toLowerCase();
  const uitlegDistributie =
    `Het aantal winkels dat dit artikel die ${pw} daadwerkelijk verkocht heeft, `
    + "geteld uit de data.\n\n"
    + `Doorgetrokken lijn dit jaar, stippellijn ${data.jaar - 1}.\n\n`
    + "Let op: een winkel die het artikel wél op het schap heeft maar die "
    + `${pw} niets verkocht telt niet mee. De echte schapdistributie ligt bij `
    + "langzame lopers dus hoger. De vergelijking door de tijd blijft wel "
    + "zuiver — beide kanten meten hetzelfde.";
  const uitlegYtd =
    `Gemiddeld aantal verkopende winkels per ${pw} dit jaar tegen `
    + `${data.jaar - 1}, alleen over de ${pw}en die beide jaren geleverd zijn `
    + "voor dit merk. Een feed die vorig jaar later begon is geen "
    + "distributiesprong.";
  const uitlegTweeMaanden =
    `Gemiddeld aantal verkopende winkels per ${pw} over de laatste twee `
    + "maanden, tegen de twee maanden daarvoor. Dichter op de actualiteit dan "
    + "de jaarvergelijking, en lang genoeg om weekruis te dempen. Een lopende "
    + "maand mag meedoen: dit is een gemiddelde per "
    + `${pw}, geen som, dus een halve maand drukt het cijfer niet.`;
  // Een winkelaantal is een gemiddelde over periodes en dus zelden rond. De
  // decimaal blijft staan: het percentage ernaast moet met deze twee getallen
  // na te rekenen zijn, en 140 tegen 163 geeft -14,1% in plaats van -14,5%.
  const winkels = (v: number | null | undefined) =>
    v == null ? "—" : String(Math.round(v * 10) / 10).replace(".", ",");

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
              title="Toon alleen nieuwe, gestopte en twijfelgevallen, en artikelen met ontbrekende data"
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
      {/* Met de distributiekolommen erbij past de tabel niet meer op elk
          scherm. Liever horizontaal schuiven dan de artikelnaam over zes
          regels breken. */}
      <div style={{ overflowX: "auto" }}>
      <table className="data" style={{ minWidth: dist ? 1180 : undefined }}>
        <thead><tr>
          <th style={{ minWidth: 210 }}>Artikel</th><th>Merk</th>
          <th>On counter<Uitleg tekst={`De eerste ${pWord.toLowerCase()} waarin voor dit artikel omzet gemeten is, over alle geladen jaren. Een ${pWord.toLowerCase()} waarin het artikel wél gemeten is maar niets verkocht telt niet mee. Staat er "≤" bij, dan valt die eerste meting samen met de start van de aanlevering van dit merk: het artikel lag er mogelijk al eerder, maar zo ver terug is er geen data.`} /></th>
          <th>YTD vs LYTD</th><th></th>
          {dist && <>
            <th>Distributie<Uitleg tekst={uitlegDistributie} /></th>
            <th>Distributie<br />YTD vs LYTD<Uitleg tekst={uitlegYtd} /></th>
            <th>Distributie<br />2 mnd<Uitleg tekst={uitlegTweeMaanden} /></th>
          </>}
          <th>Laatste {pWord.toLowerCase()}</th><th>Totaal YTD</th>
        </tr></thead>
        <tbody>
          {zichtbaar.map((a: any) => (
            <tr key={a.ean} className={`click ${sel === a.ean ? "selected" : ""}`} onClick={() => setSel(a.ean)}>
              <td>
                <ArtikelSignalen status={a.status} reden={a.status_reden} dekking={a.dekking} />
                {a.naam}<br />
                <span className="mono sub">{a.ean}</span>
              </td>
              <td><BrandDot merk={a.merk} />{a.merk}</td>
              {/* Begrensd = de eerste meting valt samen met de start van de
                  feed van dit merk. Dan is dit een ondergrens en geen
                  introductiemoment; zonder dat teken leest een datagrens als
                  een datum waarop het artikel in het schap kwam. */}
              <td style={{ whiteSpace: "nowrap" }}
                title={a.on_counter_begrensd
                  ? "Valt samen met de start van de aanlevering van dit merk — "
                    + "mogelijk lag het artikel er al eerder"
                  : undefined}>
                {a.on_counter_begrensd && <span className="sub">≤ </span>}
                {fmtPeriode(a.on_counter)}
              </td>
              <td>
                <Sparkline ytd={toSeries(a.sparkline.ytd, metric)} lytd={toSeries(a.sparkline.lytd, metric)}
                  isEuro={isEuro} periodWord={pWord} jaar={data.jaar} />
              </td>
              {/* Het percentage is op het vergelijkbare venster van het merk
                  gerekend, niet op de totalen in de laatste kolom. Zonder de
                  twee bedragen erbij is het niet na te rekenen — en dan lijkt
                  het fout terwijl het juist zorgvuldiger is. */}
              <td title={a.ytd_vergelijkbaar
                ? `Op vergelijkbare basis: ${fmtEur(a.ytd_vergelijkbaar.nu)} tegen `
                  + `${fmtEur(a.ytd_vergelijkbaar.vorig)} — alleen de periodes die `
                  + "dit jaar én vorig jaar geleverd zijn voor dit merk."
                : "Geen vergelijkbare periodes met vorig jaar."}>
                <DeltaTag pct={a.ytd_delta_pct} />
              </td>
              {dist && <>
                <td>
                  {a.distributie ? <>
                    <Sparkline ytd={a.distributie.reeks.ytd} lytd={a.distributie.reeks.lytd}
                      isEuro={false} periodWord={pWord} jaar={data.jaar} />
                    <div className="sub" style={{ fontSize: 10.5 }}>
                      {winkels(a.distributie.laatste)} winkels
                    </div>
                  </> : "—"}
                </td>
                {/* De twee bedragen in de title: een percentage zonder de
                    getallen eronder is niet na te rekenen. */}
                <td title={a.distributie?.ytd?.vorig
                  ? `${winkels(a.distributie.ytd.nu)} tegen `
                    + `${winkels(a.distributie.ytd.vorig)} winkels, gemiddeld over `
                    + `${a.distributie.ytd.periodes} ${pw}en die beide jaren geleverd zijn`
                  : "Geen vergelijkbare periodes met vorig jaar."}>
                  <DeltaTag pct={a.distributie?.ytd?.delta_pct ?? null} />
                </td>
                <td title={a.distributie?.twee_maanden?.vorig
                  ? `${winkels(a.distributie.twee_maanden.nu)} winkels in `
                    + `${a.distributie.twee_maanden.label} tegen `
                    + `${winkels(a.distributie.twee_maanden.vorig)} in `
                    + `${a.distributie.twee_maanden.vorig_label}`
                  : "Nog geen twee eerdere maanden om mee te vergelijken."}>
                  <DeltaTag pct={a.distributie?.twee_maanden?.delta_pct ?? null} />
                </td>
              </>}
              <td style={{ whiteSpace: "nowrap" }}>{fmt(a.laatste_periode[metric])}</td>
              <td style={{ whiteSpace: "nowrap" }}>{fmt(a.totaal_ytd[metric])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

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
