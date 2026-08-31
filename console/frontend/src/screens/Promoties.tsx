import { Fragment, useEffect, useRef, useState } from "react";
import { apiGet, apiSend, fmtEur } from "../api";
import { ShellCtx } from "../App";
import { BrandDot, EmptyProfileCard, LevelStrip, LoadState, Uitleg } from "../components/shared";

/** Waarom een periode niet meetelt, in gewone taal. */
const REDEN: Record<string, string> = {
  actie: "bevestigde actie",
  voorstel: "voorgestelde actie",
  loopt_nog: "periode loopt nog",
  niet_geleverd: "niet geleverd",
};

export default function Promoties({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<string | null>(null);
  // Ketent de automatische saves, zodat ze elkaar nooit inhalen.
  const wachtrij = useRef(Promise.resolve());
  // Hoeveel kliks er nog niet opgeslagen zijn. Zolang dat er meer dan nul
  // zijn, mag een herlaad de vinkjes NIET overschrijven: de server kent die
  // kliks nog niet, en zijn stand overnemen liet vinkjes vanzelf omklappen —
  // waarna de volgende klik die verkeerde stand als waarheid terugstuurde.
  const openstaand = useRef(0);
  // Welke suggestieregel is uitgeklapt naar zijn artikelen.
  const [open, setOpen] = useState<string | null>(null);
  const [uitlegOpen, setUitlegOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/promoties`).then((d) => {
    setData(d);
    setError(null);
    // Alleen de vinkjes overnemen als er niets meer onderweg is. Anders
    // wint een oudere serverstand van een klik die nog moet worden
    // opgeslagen. De laatste save in de keten doet altijd nog een herlaad,
    // dus de stand komt hoe dan ook goed.
    if (openstaand.current > 0) return;
    const init: Record<string, boolean> = {};
    for (const s of d.suggesties ?? []) init[key(s)] = s.bevestigd;
    setChecked(init);
  }).catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { setData(null); load(); }, [ctx.retailer]);

  // De sleutel komt van de server (analytics.promo_sleutel). Hier hem zelf
  // in elkaar zetten ging mis zodra een veld leeg kon zijn: een ontbrekende
  // formule en een lege formule leverden dezelfde sleutel, en dan delen twee
  // rijen één vinkje.
  const key = (s: any) => s.sleutel as string;

  if (!data) return <LoadState error={error} reload={load} />;
  if (!data.available) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const pw = data.periode_type === "maand" ? "Maand" : "Week";
  const nConfirmed = Object.values(checked).filter(Boolean).length;

  /** Een vinkje slaat zichzelf op — en alléén zichzelf.
   *
   *  Het scherm stuurde eerst de HELE lijst bevestigingen terug, afgeleid uit
   *  zijn eigen vinkjes. Daardoor kon één klik regels raken die de gebruiker
   *  niet had aangeraakt: na elke save volgt een verse load, die zette de
   *  vinkjes terug naar de serverstand van dát moment (zonder de kliks die
   *  nog in de wachtrij stonden), en de klik daarna stuurde die achterhaalde
   *  stand als waarheid terug. Vinkjes gingen zo vanzelf aan en uit.
   *
   *  Nu gaat er per klik één wijziging naar de server. Ook met een scherm dat
   *  achterloopt kan een klik geen andere regel meer omzetten. De keten
   *  houdt de volgorde aan, en de load erna houdt de uplift, de basisregel en
   *  de markers op het dashboard actueel. Mislukt een save, dan telt hij af
   *  en herstelt de laatste load de vinkjes naar wat de server echt heeft. */
  const zetVinkje = (s: any, aan: boolean) => {
    setChecked((vorig) => ({ ...vorig, [key(s)]: aan }));
    const wijziging = { merk: s.merk, land: s.land, banner: s.banner,
                        periode: s.periode, bevestigd: aan };
    openstaand.current += 1;
    wachtrij.current = wachtrij.current
      .then(() => apiSend(`/${ctx.retailer}/promoties`, "PUT", { wijzigingen: [wijziging] }))
      .then((r: any) => { setSaved(`${r?.aantal ?? "?"} ${pw.toLowerCase()}(en) bevestigd`); })
      .catch((e: any) => { setSaved(`Opslaan mislukt: ${e?.message ?? e}`); })
      .then(() => { openstaand.current -= 1; })
      .then(load);
  };

  return (
    <>
      <h1>Promoties — {ctx.card?.naam}</h1>
      <LevelStrip labels={data.labels} retailer={ctx.retailer}
        uitleg={data.periode_type === "maand" ? `Drempel ${Math.round(data.drempel * 100)}% op maandniveau.` : undefined} />

      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <b>Hoe herkent de app een actie?</b>
          <button className="chip off" style={{ fontSize: 10, marginLeft: "auto" }}
            onClick={() => setUitlegOpen(!uitlegOpen)}>
            {uitlegOpen ? "verbergen" : "uitleg"}
          </button>
        </div>
        {uitlegOpen && (
          <div className="sub" style={{ marginTop: 10, maxWidth: 760, lineHeight: 1.55 }}>
            <p style={{ marginTop: 0 }}>
              Een actie is een {pw.toLowerCase()} waarin de gemiddelde verkoopprijs
              onder het normale niveau lag. De app volgt <b>per artikel de eigen
              stukprijs</b> en vergelijkt die met de normale prijs van dátzelfde
              artikel; die verhoudingen worden met vaste gewichten (het jaarvolume)
              opgeteld tot één index. Zo telt een verschuiving in de verkoopmix niet
              als prijsdaling — en een duur artikel dat een {pw.toLowerCase()} toevallig
              niets verkoopt evenmin.
            </p>
            <p>
              Het <b>normale niveau</b> is de mediaan van de {pw.toLowerCase()}en
              van hetzelfde jaar die niet als actie gelden en die volledig geleverd
              zijn. Dat gaat in twee stappen: eerst worden actieweken gevlagd, daarna
              worden de definitieve cijfers berekend met die weken buiten de
              referentie — anders verklaart een actierijk jaar zijn eigen acties weg.
            </p>
            <p>
              Er zijn <b>twee ingangen</b>. Zakt de hele lijn onder de drempel van{" "}
              {Math.round(data.drempel * 100)}%, dan heet het assortimentsbreed.
              Is één artikel met noemenswaardig volume afgeprijsd terwijl de rest
              op prijs blijft, dan verschijnt dat apart — die gevallen werden
              eerder gemist, omdat tien artikelen één afprijzing wegwegen.
            </p>
            <p style={{ marginBottom: 0 }}>
              De <b>zekerheid</b> (1–5) is een optelsom van vier waarneembare
              signalen: hoe ver de prijsdaling boven de normale schommeling van dít
              merk uitkomt (max 2), of het volume meebewoog, of het bereik
              bevestigd is, en of de {pw.toLowerCase()} compleet geleverd is.
              Onvolledige data zet de score vast op maximaal 2. Het is een
              vuistregel, geen kans — beweeg over een score om te zien welke
              signalen meetelden.
            </p>
          </div>
        )}
      </div>

      {data.basis_per_merk?.length > 0 && (
        <>
          <h2>Gemiddelde {pw.toLowerCase()}omzet zonder acties</h2>
          <p className="sub" style={{ marginTop: -6, maxWidth: 700 }}>
            Het niveau waar een actie tegen afgezet hoort te worden. Actie{pw === "Week" ? "weken" : "maanden"} en
            voorgestelde acties tellen niet mee, en {pw.toLowerCase()}en die niet
            (volledig) geleverd zijn ook niet — die zijn geen lage omzet maar geen
            waarneming.
          </p>
          <table className="data" style={{ maxWidth: 760 }}>
            <thead><tr>
              <th>Merk</th><th>Land</th>
              {data.capabilities.banner && <th>Formule</th>}
              <th>Jaar</th>
              <th style={{ textAlign: "right" }}>Gemiddeld per {pw.toLowerCase()}</th>
              <th style={{ textAlign: "right" }}>Mediaan</th>
              <th>Gebruikt</th>
            </tr></thead>
            <tbody>
              {data.basis.map((b: any) => (
                <tr key={`${b.merk}${b.land}${b.banner}${b.jaar}`}>
                  <td><BrandDot merk={b.merk} />{b.merk}</td>
                  <td>{b.land}</td>
                  {data.capabilities.banner && <td>{b.banner ?? "—"}</td>}
                  <td>{b.jaar}</td>
                  <td style={{ textAlign: "right" }}><b>{fmtEur(b.gemiddelde)}</b></td>
                  <td style={{ textAlign: "right" }} className="sub">{fmtEur(b.mediaan)}</td>
                  <td className="sub">
                    {b.periodes} {pw.toLowerCase()}en
                    {b.uitgesloten.length > 0 && (
                      <span title={b.uitgesloten.map((u: any) =>
                        `${u.periode}: ${REDEN[u.reden] ?? u.reden}`).join("\n")}>
                        {" "}· {b.uitgesloten.length} niet meegeteld
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {data.onvolledige_periodes?.length > 0 && (
        <p className="sub" style={{ marginTop: 10, color: "var(--warn)" }}>
          Let op: {data.onvolledige_periodes.length} {pw.toLowerCase()}
          {data.onvolledige_periodes.length === 1 ? "" : "en"} zijn niet compleet —{" "}
          {data.onvolledige_periodes.slice(0, 4).map((o: any) =>
            `${o.merk ?? "ONBEKEND"} ${o.periode} (${REDEN[o.reden] ?? o.reden})`).join(", ")}
          {data.onvolledige_periodes.length > 4 && ` en ${data.onvolledige_periodes.length - 4} meer`}.
          Die tellen niet mee in het gemiddelde en verlagen de zekerheid van een
          actiesuggestie.
        </p>
      )}

      <h2>Actiesuggesties</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 20, alignItems: "start" }}>
        <div>
          <table className="data">
            <thead><tr>
              <th>Merk</th><th>Land</th>
              {data.capabilities.banner && <th>Formule</th>}
              <th>{pw}</th><th>Suggestie</th>
              <th>Bereik<Uitleg tekst="Assortiment: het grootste deel van de verkochte artikelen lag onder de eigen normale prijs. Artikel: één of enkele artikelen waren afgeprijsd terwijl de rest op prijs bleef — die gevallen bewegen de gewogen prijsindex nauwelijks en werden eerder gemist." /></th>
              <th>Zekerheid<Uitleg tekst="Een optelsom van vier waarneembare signalen (prijsdaling t.o.v. de normale schommeling, volumereactie, bereik, volledigheid van de data). Een vuistregel, geen kans. Beweeg over een score om te zien welke signalen meetelden." /></th>
              <th>Promotie</th>
            </tr></thead>
            <tbody>
              {data.suggesties.map((s: any) => (
                <Fragment key={key(s)}>
                <tr>
                  <td><BrandDot merk={s.merk} />{s.merk}</td>
                  <td>{s.land}</td>
                  {data.capabilities.banner && <td>{s.banner ?? "—"}</td>}
                  <td>{s.periode}</td>
                  <td style={{ fontWeight: 500 }}>{s.suggestie ?? "—"}</td>
                  <td>
                    {s.bereik ? (
                      <button className="chip off" style={{ fontSize: 10 }}
                        onClick={() => setOpen(open === key(s) ? null : key(s))}>
                        {s.bereik === "assortiment"
                          ? `assortiment (${s.artikelen.length}/${s.artikelen_verkocht})`
                          : `${s.artikelen.length} artikel${s.artikelen.length === 1 ? "" : "en"}`}
                      </button>
                    ) : <span className="sub">—</span>}
                  </td>
                  <td>
                    {s.zekerheid ? (
                      <b title={(s.zekerheid_delen ?? []).map((d: any) =>
                        `${d.punten > 0 ? "+" + d.punten : "0"} ${d.naam}: ${d.tekst}`).join("\n")}
                        className={s.zekerheid >= 4 ? "sig-green" : s.zekerheid <= 2 ? "sub" : ""}>
                        {s.zekerheid}/5
                      </b>
                    ) : <span className="sub">—</span>}
                  </td>
                  <td>
                    <input type="checkbox" className="checkbox" checked={!!checked[key(s)]}
                      aria-label={`Markeer ${s.merk} ${s.periode} als promotie`}
                      onChange={(e) => zetVinkje(s, e.target.checked)} />
                  </td>
                </tr>
                {open === key(s) && !!s.artikelen?.length && (
                  <tr key={`${key(s)}-detail`}>
                    <td colSpan={8} className="sub" style={{ paddingLeft: 26 }}>
                      {s.artikelen.map((a: any) => (
                        <div key={a.artikel_ean} style={{ padding: "2px 0" }}>
                          <span className="mono">{a.artikel_ean}</span>{" "}
                          {fmtEur(a.normale_prijs)} → {fmtEur(a.actieprijs)}{" "}
                          <b className="sig-red">−{a.daling_pct.toLocaleString("nl-NL")}%</b>{" "}
                          · {a.volumeaandeel_pct.toLocaleString("nl-NL")}% van het volume
                        </div>
                      ))}
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
              {!data.suggesties.length && (
                <tr><td colSpan={8} className="sub">Geen prijsafwijkingen onder de mediaan gevonden.</td></tr>
              )}
            </tbody>
          </table>
          <p className="sub" style={{ marginTop: 12 }}>
            {saved ?? `${nConfirmed} ${pw.toLowerCase()}(en) aangevinkt`} · wijzigingen
            worden direct opgeslagen
          </p>

          <p className="sub" style={{ marginTop: 14 }}>
            Het omzeteffect van de bevestigde acties staat op het{" "}
            <a style={{ cursor: "pointer" }}
              onClick={() => ctx.go(ctx.retailer, "dashboard")}>dashboard</a>,
            bij de trendgrafiek met de actiemarkers.
          </p>
        </div>

        <div className="card">
          <div className="eyebrow">Hoe de suggestie werkt</div>
          {data.methode === "handmatig" ? (
            <>
              <p className="sub">Deze retailer levert {data.capabilities.volume === false
                ? <>geen <b>volumedata</b></> : <>geen <b>artikelniveau</b></>}, dus een betrouwbare
                prijsvergelijking is niet mogelijk — zonder artikelniveau meet je de verkoopmix
                in plaats van de prijs.</p>
              <p className="sub">Handmatig actieperiodes aanvinken werkt wél: de tabel toont elke
                {" "}{pw.toLowerCase()} per merk, en jij markeert de actieperiodes.</p>
            </>
          ) : (
            <>
              <p className="sub">De prijs wordt <b>per artikel</b> gevolgd en met een vaste mix opgeteld
                tot één prijsindex per {pw.toLowerCase()}, per merk
                {data.capabilities.banner ? " per formule" : " per land"}.</p>
              <p className="sub">Dat is bewust niet de gemiddelde stukprijs van het hele merk: verkoopt
                een goedkoop artikel een {pw.toLowerCase()} wat meer, dan daalt dat gemiddelde zonder dat
                er iets is afgeprijsd.</p>
              <p className="sub">Ligt de index {Math.round(data.drempel * 100)}% of meer onder de mediaan
                van <b>hetzelfde jaar</b>, dan verschijnt een suggestie ("afgeprijsd, -x%"). Er wordt nooit
                automatisch aangevinkt — jij bevestigt.</p>
            </>
          )}
          <p className="sub">De uplift vergelijkt de omzet in de actieperiode met de <b>mediaan</b> van de
            periodes zónder actie uit hetzelfde jaar. Bevestigde actieperiodes blijven buiten die
            basislijn, en onder drie basisperiodes tonen we geen percentage.</p>
        </div>
      </div>
    </>
  );
}
