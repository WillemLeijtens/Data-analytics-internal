import { Fragment, useEffect, useMemo, useState } from "react";
import { apiGet, apiSend, fmtEur, YEAR_COLORS } from "../api";
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
  const [jaar, setJaar] = useState<string>("ALLE");
  const [saved, setSaved] = useState<string | null>(null);
  // Welke suggestieregel is uitgeklapt naar zijn artikelen.
  const [open, setOpen] = useState<string | null>(null);
  const [uitlegOpen, setUitlegOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/promoties`).then((d) => {
    setData(d);
    setError(null);
    const init: Record<string, boolean> = {};
    for (const s of d.suggesties ?? []) init[key(s)] = s.bevestigd;
    setChecked(init);
  }).catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { setData(null); load(); }, [ctx.retailer]);

  const key = (s: any) => `${s.merk}|${s.land}|${s.banner ?? ""}|${s.periode}`;

  const uplift = useMemo(() => {
    if (!data) return [];
    return (data.uplift as any[]).filter((u) => jaar === "ALLE" || String(u.jaar) === jaar);
  }, [data, jaar]);

  if (!data) return <LoadState error={error} reload={load} />;
  if (!data.available) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const pw = data.periode_type === "maand" ? "Maand" : "Week";
  const nConfirmed = Object.values(checked).filter(Boolean).length;
  // Promoties zonder genoeg basisperiodes hebben géén percentage; die mogen
  // het gemiddelde en de uitersten niet als nul omlaag trekken.
  const metPct = uplift.filter((u) => u.uplift_pct != null);
  // Jaarkleuren ankeren op het nieuwste jaar in de dáta, niet op een
  // hardgecodeerd kalenderjaar dat elk jaar zou verschuiven.
  const maxJaar = Math.max(...(data.uplift as any[]).map((u) => u.jaar), 0);
  const maxAbs = Math.max(1, ...metPct.map((u) => Math.abs(u.uplift_pct)));
  const avg = metPct.length ? metPct.reduce((a, u) => a + u.uplift_pct, 0) / metPct.length : null;

  const save = async () => {
    const bevestigd = (data.suggesties as any[])
      .filter((s) => checked[key(s)])
      .map((s) => ({ merk: s.merk, land: s.land, banner: s.banner, periode: s.periode }));
    try {
      await apiSend(`/${ctx.retailer}/promoties`, "PUT", { bevestigd });
      setSaved(`${bevestigd.length} ${pw.toLowerCase()}(en) bevestigd`);
      load();
    } catch (e: any) {
      setSaved(`Opslaan mislukt: ${e?.message ?? e}`);
    }
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
                      onChange={(e) => setChecked({ ...checked, [key(s)]: e.target.checked })} />
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
          <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 12 }}>
            <button className="btn" onClick={save}>Opslaan</button>
            <span className="sub">{saved ?? `${nConfirmed} ${pw.toLowerCase()}(en) aangevinkt`}</span>
          </div>

          <h2>Omzeteffect per promotie</h2>
          <div className="card">
            <div className="seg" style={{ marginBottom: 12 }}>
              {["ALLE", ...Array.from(new Set((data.uplift as any[]).map((u) => String(u.jaar)))).sort()].map((j) => (
                <button key={j} className={jaar === j ? "on" : ""} onClick={() => setJaar(j)}>{j}</button>
              ))}
            </div>
            {uplift.length ? (
              <>
                <div className="sub" style={{ marginBottom: 10 }}>
                  {metPct.length} promoties gemeten · gem.{" "}
                  <b className={avg != null && avg >= 0 ? "sig-green" : "sig-red"}>
                    {avg != null ? `${avg >= 0 ? "+" : ""}${avg.toFixed(1)}%` : "—"}
                  </b>
                  {metPct.length > 0 && <>
                    {" "}· beste <b className="sig-green">+{Math.max(...metPct.map((u) => u.uplift_pct)).toFixed(1)}%</b>{" "}
                    · zwakste <b className="sig-red">{Math.min(...metPct.map((u) => u.uplift_pct)).toFixed(1)}%</b>
                  </>}
                  {uplift.length > metPct.length &&
                    ` · ${uplift.length - metPct.length} zonder genoeg basisperiodes`}
                </div>
                {uplift.map((u) => (
                  <div key={`${u.merk}${u.periode}`} style={{ display: "grid", gridTemplateColumns: "170px 1fr 70px", gap: 10, alignItems: "center", margin: "5px 0" }}>
                    <span style={{ fontSize: 11.5 }}>{u.merk} · {u.periode}</span>
                    <div className="bar-track" style={{ height: 8 }}>
                      {u.uplift_pct != null && <div className="bar-fill" style={{
                        height: 8,
                        width: `${(Math.abs(u.uplift_pct) / maxAbs) * 100}%`,
                        background: u.uplift_pct < 0 ? "var(--neg)"
                          : YEAR_COLORS[maxJaar - u.jaar] ?? "var(--t-fg3)",
                      }} />}
                    </div>
                    {u.uplift_pct != null ? (
                      // De twee bedragen erbij: zonder de actie-omzet en de
                      // basislijn is het percentage niet na te rekenen, en een
                      // cijfer dat je niet kunt controleren vertrouw je
                      // terecht niet.
                      <b style={{ fontSize: 12 }} className={u.uplift_pct >= 0 ? "" : "sig-red"}
                        title={`${fmtEur(u.omzet)} in de actie tegen een basislijn van `
                          + `${fmtEur(u.basislijn)} — de mediaan van ${u.basisperiodes} `
                          + `${pw.toLowerCase()}(en) zonder actie in ${u.jaar}.`}>
                        {u.uplift_pct >= 0 ? "+" : ""}{u.uplift_pct}%
                      </b>
                    ) : (
                      <span className="sub" style={{ fontSize: 10.5 }}
                        title={u.reden === "periode loopt nog" ? undefined
                          : `Maar ${u.basisperiodes} ${pw.toLowerCase()}(en) zonder actie in ${u.jaar}`}>
                        {u.reden ?? "te weinig basis"}
                      </span>
                    )}
                  </div>
                ))}
              </>
            ) : <p className="sub">Nog geen bevestigde promoties{jaar !== "ALLE" ? ` in ${jaar}` : ""}.</p>}
          </div>
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
