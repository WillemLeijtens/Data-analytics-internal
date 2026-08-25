import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";
import { EmptyProfileCard, LoadState, Uitleg } from "../components/shared";

/** De vier onderdelen in leesvolgorde, met de kop die erboven komt. */
const ONDERDELEN: [string, string][] = [
  ["omzet", "Omzet"],
  ["assortiment", "Assortiment"],
  ["winkels", "Winkelontwikkeling"],
  ["promoties", "Promoties"],
];

const ERNST_KLEUR: Record<string, string> = {
  rood: "var(--neg)", oranje: "var(--warn)", info: "var(--t-fg3)",
};

function Stip({ ernst }: { ernst: string }) {
  return (
    <span aria-hidden="true" style={{
      display: "inline-block", width: 7, height: 7, borderRadius: "50%",
      background: ERNST_KLEUR[ernst] ?? ERNST_KLEUR.info,
      marginRight: 8, flex: "0 0 auto",
    }} />
  );
}

const tijd = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("nl-NL",
    { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "—";

export default function Conclusie({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const [schrijffout, setSchrijffout] = useState<string | null>(null);
  // Voorkomt dat het automatisch bijwerken twee keer tegelijk afgaat (React
  // rendert in ontwikkelmodus dubbel) of blijft herhalen als het mislukt.
  const geprobeerd = useRef<string | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/conclusie`).then((d) => {
    setData(d); setError(null);
  }).catch((e) => setError(String(e?.message ?? e)));

  useEffect(() => {
    setData(null); setSchrijffout(null); geprobeerd.current = null; load();
  }, [ctx.retailer]);

  const schrijf = async () => {
    setBezig(true); setSchrijffout(null);
    try {
      setData(await apiSend(`/${ctx.retailer}/conclusie`, "POST", {}));
    } catch (e: any) {
      setSchrijffout(String(e?.message ?? e));
    } finally {
      setBezig(false);
    }
  };

  // "Automatisch bij nieuwe data": zodra de opgeslagen tekst niet meer bij de
  // huidige cijfers hoort, of er nog helemaal geen tekst is, schrijft het
  // scherm zelf een nieuwe. Alleen als er een sleutel is — anders is de
  // 422 voorspelbaar en zou hij bij elk bezoek terugkomen.
  useEffect(() => {
    if (!data?.beschikbaar || !data.sleutel_ingesteld || bezig) return;
    if (data.conclusie && !data.verouderd) return;
    if (geprobeerd.current === ctx.retailer) return;
    geprobeerd.current = ctx.retailer;
    schrijf();
  }, [data, ctx.retailer]);

  if (!data) return <LoadState error={error} reload={load} />;
  if (!data.beschikbaar && data.reden === "PARSER PROFIEL ONTBREEKT")
    return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const c = data.conclusie;
  const bevindingen: any[] = data.bevindingen ?? [];

  return (
    <>
      <h1>Conclusie — {ctx.card?.naam}</h1>
      <p className="sub" style={{ maxWidth: 660 }}>
        Wat de cijfers van deze retailer zeggen over omzet, assortiment,
        winkelontwikkeling en promoties — en wat je eraan zou kunnen doen. De
        bevindingen onderaan zijn door de app zelf berekend; de samenvatting is
        daarop geschreven, zodat elke zin te herleiden is tot een cijfer.
      </p>

      {!data.beschikbaar && (
        <div className="card empty-card">
          <p className="sub">Er valt nog niets te concluderen — er is voor deze
            retailer nog geen data geïmporteerd.</p>
        </div>
      )}

      {data.beschikbaar && !data.sleutel_ingesteld && (
        <div className="level-strip" style={{ borderLeft: "3px solid var(--warn)" }}>
          <span className="sub">
            Geen Anthropic-sleutel ingesteld, dus de app schrijft geen samenvatting.
            De bevindingen hieronder zijn er gewoon.
          </span>
          <Link to={`/${ctx.retailer}/instellingen`} style={{ marginLeft: "auto" }}>
            Sleutel instellen
          </Link>
        </div>
      )}

      {data.beschikbaar && (
        <>
          {bezig && (
            <p className="sub">
              {c ? "De cijfers zijn veranderd — de conclusie wordt bijgewerkt…"
                 : "Bezig met schrijven…"}
            </p>
          )}
          {schrijffout && (
            <div className="level-strip" style={{ borderLeft: "3px solid var(--neg)" }}>
              <span className="sub">Conclusie schrijven is mislukt: {schrijffout}</span>
              <a style={{ cursor: "pointer", marginLeft: "auto" }} onClick={schrijf}>
                Opnieuw proberen
              </a>
            </div>
          )}
          {/* Een eerder geschreven conclusie blijft leesbaar, ook zonder
              sleutel: de tekst bestaat al. Alleen SCHRIJVEN heeft er een
              nodig — vandaar dat alleen de knop eronder eraan hangt. */}
          {c && (
            <div className="card" style={{ marginTop: 12 }}>
              {(c.waarschuwingen ?? []).map((w: string, i: number) => (
                <p key={i} className="sub" style={{ color: "var(--neg-text)", marginTop: 0 }}>
                  ⚠ {w}
                </p>
              ))}
              <p style={{ margin: "0 0 4px", lineHeight: 1.55 }}>{c.samenvatting}</p>
              {(c.advies ?? []).length > 0 && (
                <>
                  <div className="eyebrow" style={{ marginTop: 18 }}>Advies</div>
                  <ol style={{ margin: "8px 0 0", paddingLeft: 20 }}>
                    {c.advies.map((a: any, i: number) => (
                      <li key={i} style={{ marginBottom: 8, lineHeight: 1.5 }}>
                        {a.actie}
                        {a.waarom && <><br /><span className="sub">{a.waarom}</span></>}
                      </li>
                    ))}
                  </ol>
                </>
              )}
              <div style={{ display: "flex", alignItems: "center", marginTop: 18 }}>
                <span className="sub">
                  Geschreven op {tijd(c.gegenereerd_op)}
                  {c.gegenereerd_door && c.gegenereerd_door !== "onbekend"
                    ? ` door ${c.gegenereerd_door}` : ""}
                </span>
                <Uitleg tekst={
                  "Deze tekst wordt automatisch opnieuw geschreven zodra er nieuwe data "
                  + "voor déze retailer is geïmporteerd — je ziet dat de eerstvolgende "
                  + "keer dat je dit scherm opent. Zolang de cijfers hetzelfde blijven, "
                  + "blijft ook deze tekst staan en wordt er niets opnieuw geschreven. "
                  + "Een import voor een andere retailer verandert hier niets aan."} />
              </div>
            </div>
          )}
        </>
      )}

      {bevindingen.length > 0 && (
        <>
          <hr className="hairline" />
          <h2>Bevindingen</h2>
          <p className="sub" style={{ marginTop: -6, maxWidth: 660 }}>
            Door de app berekend uit het dashboard, de assortimentsanalyse, de
            winkelanalyse en de promotiedetectie — los van de tekst hierboven.
          </p>
          {ONDERDELEN.map(([sleutel, kop]) => {
            const items = bevindingen.filter((b) => b.onderdeel === sleutel);
            if (!items.length) return null;
            return (
              <div key={sleutel} style={{ marginTop: 18 }}>
                <div className="eyebrow">{kop}</div>
                <div className="card" style={{ marginTop: 8 }}>
                  {items.map((b, i) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "baseline",
                      padding: i ? "12px 0 0" : 0,
                      borderTop: i ? "1px solid var(--t-border)" : undefined,
                      marginTop: i ? 12 : 0,
                    }}>
                      <Stip ernst={b.ernst} />
                      <div>
                        <b style={{ fontSize: 12.5 }}>{b.kop}</b>
                        <br />
                        <span className="sub">{b.tekst}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}
    </>
  );
}
