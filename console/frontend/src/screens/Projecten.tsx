import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend, fmtEur } from "../api";
import { ShellCtx } from "../App";
import { LoadState, Uitleg } from "../components/shared";

/* De formules staan hier nog een keer, alleen voor directe feedback tijdens
   het typen; de backend (engine/projecten.py) is de geteste bron en levert
   de cijfers voor de lijst en na het opslaan. */
const n = (v: any) => (v == null || v === "" ? 0 : +v || 0);

/** Weken tussen start en einde, einddag inbegrepen, op één decimaal —
 *  dezelfde formule als engine/projecten.looptijd_weken. */
function looptijdWeken(start?: string | null, eind?: string | null): number | null {
  if (!start || !eind) return null;
  const dagen = (new Date(eind).getTime() - new Date(start).getTime()) / 86400000 + 1;
  if (dagen <= 0 || isNaN(dagen)) return null;
  return Math.round((dagen / 7) * 10) / 10;
}

const wk = (weken: number) => weken.toLocaleString("nl-NL", { maximumFractionDigits: 1 });

function bereken(proj: any, producten: any[], kosten: any[]) {
  const rijen = producten.map((p) => {
    const margeStuk = n(p.verkoopprijs) - n(p.kostprijs);
    const stuksEenmalig = n(p.aantal_winkels) * n(p.stuks_per_winkel);
    const stuksWeek = n(p.aantal_winkels) * n(p.rotatie_per_winkel_per_week);
    return {
      eenmalig_omzet: stuksEenmalig * n(p.verkoopprijs),
      eenmalig_marge: stuksEenmalig * margeStuk,
      week_omzet: stuksWeek * n(p.verkoopprijs),
      week_marge: stuksWeek * margeStuk,
    };
  });
  const weken = looptijdWeken(proj.start_datum, proj.eind_datum);
  const bij = (k: any) => k.soort === "bijdrage_leverancier";
  const somK = (terug: boolean, bijdrage: boolean) => kosten
    .filter((k) => !!k.terugkerend === terug && bij(k) === bijdrage)
    .reduce((a, k) => a + n(k.bedrag), 0);
  const kostenEenmalig = somK(false, false), bijdrageEenmalig = somK(false, true);
  const kostenLooptijd = somK(true, false), bijdrageLooptijd = somK(true, true);
  const som = (veld: string) => rijen.reduce((a, r: any) => a + r[veld], 0);
  const eenOmzet = som("eenmalig_omzet"), eenProductmarge = som("eenmalig_marge");
  const weekOmzet = som("week_omzet"), weekMarge = som("week_marge");
  const eenMarge = eenProductmarge - kostenEenmalig + bijdrageEenmalig;
  const terugOmzet = weken ? weekOmzet * weken : null;
  const terugMarge = weken ? weekMarge * weken - kostenLooptijd + bijdrageLooptijd : null;
  const kostenBuitenBeeld = !weken && (kostenLooptijd || bijdrageLooptijd)
    ? kostenLooptijd - bijdrageLooptijd : 0;
  const pct = (m: number, o: number) => (o ? (m / o) * 100 : null);
  return {
    rijen, weken, kostenBuitenBeeld,
    eenmalig: { omzet: eenOmzet, productmarge: eenProductmarge, kosten: kostenEenmalig,
                bijdrage: bijdrageEenmalig, marge: eenMarge, pct: pct(eenMarge, eenOmzet) },
    terugkerend: { weekOmzet, weekMarge, omzet: terugOmzet, kosten: kostenLooptijd,
                   bijdrage: bijdrageLooptijd, marge: terugMarge,
                   pct: terugMarge != null && terugOmzet ? pct(terugMarge, terugOmzet) : null },
    totaal: { omzet: eenOmzet + (terugOmzet ?? 0), marge: eenMarge + (terugMarge ?? 0) },
  };
}

const tijd = (ts?: string | null) => ts
  ? new Date(ts.replace(" ", "T") + (ts.includes("Z") ? "" : "Z")).toLocaleString("nl-NL",
      { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
  : "—";

/** Looptijd in gewone taal: "4 wk · nog 2 wk" / "afgelopen" / "start over 3 wk". */
function looptijdTekst(start?: string | null, eind?: string | null): string {
  const weken = looptijdWeken(start, eind);
  if (weken == null) return "geen looptijd ingevuld";
  const nu = Date.now();
  const s = new Date(start!).getTime(), e = new Date(eind!).getTime() + 86400000;
  const basis = `${wk(weken)} ${weken === 1 ? "week" : "weken"}`;
  if (nu < s) return `${basis} · start over ${Math.max(1, Math.ceil((s - nu) / 604800000))} wk`;
  if (nu > e) return `${basis} · afgelopen`;
  return `${basis} · nog ${Math.max(1, Math.ceil((e - nu) / 604800000))} wk`;
}

function Cel({ children }: { children: React.ReactNode }) {
  return <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{children}</td>;
}

/** Het percentage prominent naast het bedrag: nettomarge leest in twee
 *  maten tegelijk. */
function PctTag({ v }: { v: number | null }) {
  if (v == null) return null;
  return <span className={`tag ${v >= 0 ? "pos" : "neg"}`} style={{ marginLeft: 8, verticalAlign: "6px" }}>
    {v.toLocaleString("nl-NL", { maximumFractionDigits: 1 })}%</span>;
}

function Geld({ v, accent }: { v: number | null; accent?: boolean }) {
  if (v == null) return <span className="sub">—</span>;
  return <span className={accent ? (v >= 0 ? "sig-green" : "sig-red") : undefined}>{fmtEur(v)}</span>;
}

const LEEG_PRODUCT = { naam: "", kostprijs: null, verkoopprijs: null, aantal_winkels: null,
                       stuks_per_winkel: null, rotatie_per_winkel_per_week: null };

export default function Projecten({ ctx }: { ctx: ShellCtx }) {
  const [lijst, setLijst] = useState<any[] | null>(null);
  const [gekozen, setGekozen] = useState<number | null>(null);
  const [d, setD] = useState<any | null>(null);          // het open project
  const [error, setError] = useState<string | null>(null);
  // Naam voor het logboek: per browser bewaard, één keer invullen — tenzij
  // het portaal zelf al een identiteit meestuurt (gateway-header), dan is
  // er niets om in te vullen en toont het scherm die naam alleen-lezen.
  const [naam, setNaam] = useState(() => localStorage.getItem("bl-naam") ?? "");
  useEffect(() => { localStorage.setItem("bl-naam", naam); }, [naam]);
  const [portaalNaam, setPortaalNaam] = useState<string | null>(null);
  useEffect(() => {
    apiGet<{ naam: string | null; bron: string }>("/wie-ben-ik")
      .then((r) => setPortaalNaam(r.bron === "portaal" ? r.naam : null))
      .catch(() => setPortaalNaam(null));
  }, []);

  const laadLijst = () => apiGet("/projecten")
    .then((r) => { setLijst(r); setError(null); })
    .catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { laadLijst(); }, []);

  // ------------------------------------------------------- automatisch opslaan
  // Geen "Opslaan"-knop: elke wijziging aan naam, producten, kosten, status
  // etc. wordt gedebounced (700 ms na de laatste toets) automatisch
  // opgeslagen. `laatOpgeslagen` bewaart de laatst BEVESTIGDE staat, zodat
  // het effect hieronder niet blijft opslaan zolang er niets nieuws is en
  // een net geladen/aangemaakt project niet meteen zichzelf terugstuurt.
  const laatOpgeslagen = useRef<string | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "bezig" | "opgeslagen" | "fout">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const snapshotVan = (data: any) => JSON.stringify({
    naam: data.naam, retailer_id: data.retailer_id, omschrijving: data.omschrijving,
    start_datum: data.start_datum, eind_datum: data.eind_datum, status: data.status,
    producten: data.producten, kosten: data.kosten,
  });

  const opslaanNu = async (data: any) => {
    setSaveStatus("bezig");
    try {
      const r = await apiSend<any>(`/projecten/${data.id}`, "PUT", { ...data, door: naam || null });
      laatOpgeslagen.current = snapshotVan(data);
      // Alleen de servermetadata (logboek, gewijzigd-op/door) overnemen, niet
      // de hele respons: is er tijdens de aanvraag alweer verder getypt, dan
      // mag dat niet overschreven worden door het oudere antwoord.
      setD((huidig: any) => (huidig && huidig.id === r.id)
        ? { ...huidig, log: r.log, gewijzigd_op: r.gewijzigd_op, gewijzigd_door: r.gewijzigd_door }
        : huidig);
      setSaveStatus("opgeslagen"); setSaveError(null);
    } catch (e: any) {
      setSaveStatus("fout"); setSaveError(String(e?.message ?? e));
    }
  };

  useEffect(() => {
    if (!d) return;
    const snap = snapshotVan(d);
    if (snap === laatOpgeslagen.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => opslaanNu(d), 700);
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d]);

  const open = (id: number) => {
    setGekozen(id); setD(null); setSaveStatus("idle"); setSaveError(null);
    apiGet<any>(`/projecten/${id}`).then((r) => {
      laatOpgeslagen.current = snapshotVan(r);
      setD(r);
    }).catch((e) => setError(String(e?.message ?? e)));
  };
  const sluit = async () => {
    // Staat er nog een gedebouncede wijziging klaar, dan meteen wegschrijven
    // — anders raakt de laatste toetsaanslag kwijt bij het navigeren weg.
    if (d && snapshotVan(d) !== laatOpgeslagen.current) {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      await opslaanNu(d);
    }
    setGekozen(null); setD(null); setSaveStatus("idle"); setSaveError(null); laadLijst();
  };

  const nieuw = async () => {
    try {
      const p = await apiSend<any>("/projecten", "POST", {
        naam: "Nieuw project",
        retailer_id: ctx.retailer !== "alle" ? ctx.retailer : null,
        door: naam || null,
      });
      laatOpgeslagen.current = snapshotVan(p);
      setLijst(null); setGekozen(p.id); setSaveStatus("idle"); setD(p);
    } catch (e: any) { setError(String(e?.message ?? e)); }
  };

  const verwijder = async () => {
    if (!window.confirm(`Project "${d.naam}" definitief verwijderen?`)) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    await apiSend(`/projecten/${d.id}`, "DELETE");
    setGekozen(null); setD(null); setSaveStatus("idle"); setSaveError(null); laadLijst();
  };

  const zetVeld = (k: string, v: any) => setD({ ...d, [k]: v });
  const zetRij = (lijstNaam: "producten" | "kosten", i: number, k: string, v: any) => {
    const kopie = [...d[lijstNaam]];
    kopie[i] = { ...kopie[i], [k]: v };
    setD({ ...d, [lijstNaam]: kopie });
  };
  const wegRij = (lijstNaam: "producten" | "kosten", i: number) =>
    setD({ ...d, [lijstNaam]: d[lijstNaam].filter((_: any, j: number) => j !== i) });

  const num = (v: any) => (v == null ? "" : v);
  const invoer = (lijstNaam: "producten" | "kosten", i: number, veld: string,
                  breed = 74, stap?: string, geld = false) => {
    const input = (
      <input type="number" min={0} step={stap ?? "0.01"}
        style={{ width: breed, paddingLeft: geld ? 16 : undefined }}
        value={num(d[lijstNaam][i][veld])} aria-label={veld}
        onChange={(e) => zetRij(lijstNaam, i, veld, e.target.value === "" ? null : +e.target.value)} />
    );
    // Geldvelden krijgen een €-prefix in het vak zelf; aantallen (winkels,
    // stuks, rotatie) blijven kale getallen — dat zijn geen prijzen.
    if (!geld) return input;
    return (
      <span style={{ position: "relative", display: "inline-block" }}>
        <span aria-hidden="true" style={{
          position: "absolute", left: 6, top: "50%", transform: "translateY(-50%)",
          fontSize: 11, color: "var(--t-fg3)", pointerEvents: "none",
        }}>€</span>
        {input}
      </span>
    );
  };

  /* ------------------------------------------------------------- lijst */
  if (gekozen == null) {
    if (!lijst) return <LoadState error={error} reload={laadLijst} />;
    return (
      <>
        <h1>Projectcalculator</h1>
        <p className="sub" style={{ maxWidth: 640 }}>
          Reken een listing of actie vooraf door: producten met vulling en verwachte
          rotatie, plus de kosten. Elk project geeft twee uitkomsten — de <b>eenmalige</b>{" "}
          omzet en marge (de eerste vulling) en de <b>terugkerende</b> (de doorverkoop
          per week en over de looptijd).
        </p>
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", margin: "16px 0" }}>
          <button className="btn" onClick={nieuw}>+ Nieuw project</button>
          <span className="sub" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center" }}>
            {portaalNaam ? (
              // Het portaal stuurt zelf een identiteit mee: niets om in te
              // vullen, en niets wat afwijkend ingevuld zou kunnen worden.
              <>Ingelogd als <b style={{ marginLeft: 4 }}>{portaalNaam}</b></>
            ) : (
              <>Jouw naam voor het logboek
                <Uitleg tekst="Wordt vastgelegd bij aanmaken en wijzigen, zodat het logboek laat zien wie wat deed. Eén keer invullen; blijft in deze browser bewaard." />
                <input type="text" placeholder="bijv. Willem" size={12} style={{ marginLeft: 8 }}
                  value={naam} onChange={(e) => setNaam(e.target.value)} /></>
            )}
          </span>
        </div>
        <table className="data">
          <thead><tr>
            <th>Project</th><th>Status</th><th>Retailer</th><th>Looptijd</th>
            <th style={{ textAlign: "right" }}>Eenmalige marge</th>
            <th style={{ textAlign: "right" }}>Terugkerende marge</th>
            <th>Laatst gewijzigd</th>
          </tr></thead>
          <tbody>
            {lijst.map((p) => (
              <tr key={p.id} className="click" onClick={() => open(p.id)}>
                <td>{p.naam}<br /><span className="sub">{p.aantal_producten} product{p.aantal_producten === 1 ? "" : "en"}</span></td>
                <td><span className={`tag ${p.status === "definitief" ? "pos" : ""}`}>
                  {p.status === "definitief" ? "Definitief" : "Concept"}</span></td>
                <td>{p.retailer_naam ?? "—"}</td>
                <td className="sub">{looptijdTekst(p.start_datum, p.eind_datum)}</td>
                <Cel><Geld v={p.eenmalig.marge} accent />
                  {p.eenmalig.marge_pct != null && <><br />
                    <span className="sub">{p.eenmalig.marge_pct.toLocaleString("nl-NL")}%</span></>}</Cel>
                <Cel><Geld v={p.terugkerend.marge} accent />
                  {p.terugkerend.marge_pct != null && <><br />
                    <span className="sub">{p.terugkerend.marge_pct.toLocaleString("nl-NL")}%</span></>}</Cel>
                <td className="sub">{tijd(p.gewijzigd_op ?? p.aangemaakt_op)} · {p.gewijzigd_door ?? p.aangemaakt_door ?? "onbekend"}</td>
              </tr>
            ))}
            {!lijst.length && <tr><td colSpan={7} className="sub">
              Nog geen projecten — maak het eerste aan met de knop hierboven.</td></tr>}
          </tbody>
        </table>
      </>
    );
  }

  /* ------------------------------------------------------------- editor */
  if (!d) return <LoadState error={error} reload={() => open(gekozen)} />;
  const b = bereken(d, d.producten, d.kosten);

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
        <a style={{ cursor: "pointer", fontSize: 12 }} onClick={sluit}>← Alle projecten</a>
        <h1 style={{ margin: 0 }}>Projectcalculator</h1>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="sub">Projectnaam<br />
            <input type="text" size={26} value={d.naam}
              onChange={(e) => zetVeld("naam", e.target.value)} /></label>
          <span className="sub">Status
            <Uitleg tekst="Een label, geen slot: 'definitief' blijft gewoon bewerkbaar. Handig om in de lijst te zien welke doorrekening nog rijpt en welke rond is." /><br />
            <div className="seg">
              <button className={d.status !== "definitief" ? "on" : ""}
                onClick={() => zetVeld("status", "concept")}>Concept</button>
              <button className={d.status === "definitief" ? "on" : ""}
                onClick={() => zetVeld("status", "definitief")}>Definitief</button>
            </div>
          </span>
          <label className="sub">Retailer
            <Uitleg tekst="Alleen ter herkenning in de lijst; de berekening verandert er niet door." /><br />
            <select value={d.retailer_id ?? ""}
              onChange={(e) => zetVeld("retailer_id", e.target.value || null)}>
              <option value="">geen</option>
              {ctx.cards.map((c) => <option key={c.id} value={c.id}>{c.naam}</option>)}
            </select></label>
          <label className="sub">Start
            <Uitleg tekst="Eerste dag van het project. Samen met de einddatum bepaalt dit de looptijd in weken, waarmee de terugkerende omzet en marge worden doorgerekend." /><br />
            <input type="date" value={d.start_datum ?? ""}
              onChange={(e) => zetVeld("start_datum", e.target.value || null)} /></label>
          <label className="sub">Einde<br />
            <input type="date" value={d.eind_datum ?? ""}
              onChange={(e) => zetVeld("eind_datum", e.target.value || null)} /></label>
          <span className="sub" style={{ paddingBottom: 4 }}>
            Looptijd: <b>{looptijdTekst(d.start_datum, d.eind_datum)}</b>
          </span>
          <label className="sub" style={{ flex: "1 1 220px" }}>Omschrijving<br />
            <input type="text" style={{ width: "100%" }} value={d.omschrijving ?? ""}
              onChange={(e) => zetVeld("omschrijving", e.target.value || null)} /></label>
        </div>
      </div>

      <h2>Producten</h2>
      <div className="tablewrap" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead><tr>
            <th>Product</th>
            <th>Kostprijs<Uitleg tekst="Jouw inkoop-/kostprijs per stuk, exclusief btw." /></th>
            <th>Verkoopprijs<Uitleg tekst="De prijs per stuk die je de retailer factureert (jouw omzet), exclusief btw." /></th>
            <th>Winkels<Uitleg tekst="Het aantal winkels dat aan dit project meedoet voor dit product." /></th>
            <th>Stuks / winkel<Uitleg tekst="De eerste vulling: hoeveel stuks elke winkel bij de start afneemt. Dit voedt de EENMALIGE omzet en marge." /></th>
            <th>Rotatie / winkel / wk<Uitleg tekst="De verwachte doorverkoop per winkel per week ná de eerste vulling. Dit voedt de TERUGKERENDE omzet en marge." /></th>
            <th style={{ textAlign: "right" }}>Eenmalig omzet / marge</th>
            <th style={{ textAlign: "right" }}>Per week omzet / marge</th>
            <th></th>
          </tr></thead>
          <tbody>
            {d.producten.map((p: any, i: number) => (
              <tr key={i}>
                <td><input type="text" size={16} value={p.naam} aria-label="Productnaam"
                  onChange={(e) => zetRij("producten", i, "naam", e.target.value)} /></td>
                <td>{invoer("producten", i, "kostprijs", 74, undefined, true)}</td>
                <td>{invoer("producten", i, "verkoopprijs", 74, undefined, true)}</td>
                <td>{invoer("producten", i, "aantal_winkels", 64, "1")}</td>
                <td>{invoer("producten", i, "stuks_per_winkel", 64, "1")}</td>
                <td>{invoer("producten", i, "rotatie_per_winkel_per_week", 64, "0.1")}</td>
                <Cel>{fmtEur(b.rijen[i].eenmalig_omzet)}<br />
                  <span className={b.rijen[i].eenmalig_marge >= 0 ? "sig-green" : "sig-red"}>
                    {fmtEur(b.rijen[i].eenmalig_marge)}</span></Cel>
                <Cel>{fmtEur(b.rijen[i].week_omzet)}<br />
                  <span className={b.rijen[i].week_marge >= 0 ? "sig-green" : "sig-red"}>
                    {fmtEur(b.rijen[i].week_marge)}</span></Cel>
                <td><button className="chip off" title="Product verwijderen"
                  onClick={() => wegRij("producten", i)}>✕</button></td>
              </tr>
            ))}
            {!d.producten.length && <tr><td colSpan={9} className="sub">Nog geen producten.</td></tr>}
          </tbody>
        </table>
      </div>
      <button className="chip" style={{ marginTop: 8 }}
        onClick={() => setD({ ...d, producten: [...d.producten, { ...LEEG_PRODUCT }] })}>
        + product toevoegen
      </button>

      <h2>Kosten</h2>
      <p className="sub" style={{ marginTop: -6, maxWidth: 640 }}>
        Elke regel drukt op één van de twee uitkomsten: <b>eenmalig</b> gaat van de
        marge van de eerste vulling af, <b>looptijd</b> van de terugkerende marge over
        de hele looptijd.
      </p>
      <table className="data" style={{ maxWidth: 720 }}>
        <thead><tr>
          <th>Kostenpost</th>
          <th>Bedrag<Uitleg tekst="Totaalbedrag voor dit project (dus niet per week). Leeg = niet van toepassing." /></th>
          <th>Drukt op<Uitleg tekst="Eenmalig: hoort bij de start (listing fee, display). Looptijd: hoort bij de doorverkoop over de hele looptijd (marketing, co-op, logistiek)." /></th>
          <th></th>
        </tr></thead>
        <tbody>
          {d.kosten.map((k: any, i: number) => (
            <tr key={i}>
              <td>{k.soort === "overig"
                ? <input type="text" size={22} value={k.label} aria-label="Omschrijving kostenpost"
                    onChange={(e) => zetRij("kosten", i, "label", e.target.value)} />
                : k.label}
                {k.soort === "bijdrage_leverancier" && (
                  <span className="sig-green" style={{ fontSize: 10.5, marginLeft: 8 }}
                    title="Geld dat de fabrikant bijlegt: telt óp bij de nettomarge in plaats van eraf, en telt niet als omzet.">
                    + telt op bij de marge
                  </span>
                )}</td>
              <td>{invoer("kosten", i, "bedrag", 96, undefined, true)}</td>
              <td>
                <div className="seg">
                  <button className={!k.terugkerend ? "on" : ""}
                    onClick={() => zetRij("kosten", i, "terugkerend", 0)}>eenmalig</button>
                  <button className={k.terugkerend ? "on" : ""}
                    onClick={() => zetRij("kosten", i, "terugkerend", 1)}>looptijd</button>
                </div>
              </td>
              <td><button className="chip off" title="Kostenregel verwijderen"
                onClick={() => wegRij("kosten", i)}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button className="chip"
          onClick={() => setD({ ...d, kosten: [...d.kosten, { soort: "overig", label: "", bedrag: null, terugkerend: 0 }] })}>
          + extra kostenregel
        </button>
        {/* Bestaande projecten van vóór deze regel hebben hem nog niet. */}
        {!d.kosten.some((k: any) => k.soort === "bijdrage_leverancier") && (
          <button className="chip"
            onClick={() => setD({ ...d, kosten: [...d.kosten, { soort: "bijdrage_leverancier", label: "Bijdrage leverancier", bedrag: null, terugkerend: 0 }] })}>
            + bijdrage leverancier
          </button>
        )}
      </div>

      <h2>Resultaat</h2>
      <div className="grid kpi">
        <div className="card">
          <div className="kpi-label">Netto marge eenmalig — de vulling
            <Uitleg tekst="De eerste levering: winkels x stuks per winkel, tegen verkoopprijs. Nettomarge = productmarge min de eenmalige kosten, plus de eenmalige bijdrage leverancier. Het percentage is de nettomarge gedeeld door de eenmalige omzet." /></div>
          <div className="kpi-value">{fmtEur(b.eenmalig.marge)}<PctTag v={b.eenmalig.pct} /></div>
          <div className="kpi-sub">omzet {fmtEur(b.eenmalig.omzet)}</div>
          <div className="kpi-sub">productmarge {fmtEur(b.eenmalig.productmarge)} − kosten {fmtEur(b.eenmalig.kosten)}{b.eenmalig.bijdrage > 0 && <> + bijdrage {fmtEur(b.eenmalig.bijdrage)}</>}</div>
        </div>
        <div className="card">
          <div className="kpi-label">Netto marge terugkerend — de doorverkoop
            <Uitleg tekst="Rotatie x winkels, per week en opgeteld over de looptijd — de verwachte herbevoorrading nadat de vulling in het schap ligt. Nettomarge = productmarge over de looptijd min de looptijdkosten, plus de looptijd-bijdrage leverancier. Het percentage is de nettomarge gedeeld door de terugkerende omzet. Zonder start- en einddatum is er alleen een weekbeeld." /></div>
          <div className="kpi-value">{b.terugkerend.marge != null
            ? <>{fmtEur(b.terugkerend.marge)}<PctTag v={b.terugkerend.pct} /></> : "—"}</div>
          <div className="kpi-sub">
            {b.weken
              ? <>over {wk(b.weken)} wk · omzet {fmtEur(b.terugkerend.omzet!)} − kosten {fmtEur(b.terugkerend.kosten)}{b.terugkerend.bijdrage > 0 && <> + bijdrage {fmtEur(b.terugkerend.bijdrage)}</>}</>
              : "vul start- en einddatum in voor het looptijdtotaal"}
          </div>
          <div className="kpi-sub">per week: {fmtEur(b.terugkerend.weekOmzet)} omzet · {fmtEur(b.terugkerend.weekMarge)} marge</div>
        </div>
        <div className="card">
          <div className="kpi-label">Totaal project
            <Uitleg tekst="Vulling plus doorverkoop bij elkaar. De doorverkoop geldt als herbevoorrading (nieuwe omzet, want het schap wordt bijgevuld). Wordt er aan het einde níét herbevoorraad, dan komt een deel van de doorverkoop uit de al gefactureerde vulling en is dit totaal een bovengrens." /></div>
          <div className="kpi-value">{fmtEur(b.totaal.marge)}
            <PctTag v={b.totaal.omzet ? (b.totaal.marge / b.totaal.omzet) * 100 : null} /></div>
          <div className="kpi-sub">netto marge · omzet {fmtEur(b.totaal.omzet)}</div>
          {b.kostenBuitenBeeld > 0 && (
            // Looptijdkosten zonder looptijd tellen nergens mee; dat stil
            // laten gebeuren laat het project completer lijken dan het is.
            <div className="kpi-sub sig-red">
              excl. {fmtEur(b.kostenBuitenBeeld)} looptijdkosten (na bijdrage) —
              vul start- en einddatum in om ze mee te rekenen
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 18, flexWrap: "wrap" }}>
        {/* Geen "Opslaan"-knop meer: elke wijziging schrijft zichzelf
            gedebounced weg. Deze regel is het enige bewijs daarvan. */}
        <span className="sub">
          {saveStatus === "bezig" && "Bezig met opslaan…"}
          {saveStatus === "opgeslagen" && "Automatisch opgeslagen."}
          {saveStatus === "fout" && (
            <span className="sig-red">Niet opgeslagen — {saveError}</span>
          )}
          {saveStatus === "idle" && "Wijzigingen worden automatisch opgeslagen."}
        </span>
        <span className="sub" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center" }}>
          {portaalNaam ? (
            <>Ingelogd als <b style={{ marginLeft: 4 }}>{portaalNaam}</b></>
          ) : (
            <>Jouw naam
              <Uitleg tekst="Komt in het logboek bij deze wijziging." />
              <input type="text" placeholder="bijv. Willem" size={10} style={{ marginLeft: 8 }}
                value={naam} onChange={(e) => setNaam(e.target.value)} /></>
          )}
        </span>
        <button className="chip off" onClick={verwijder}>project verwijderen</button>
      </div>

      <h2>Logboek</h2>
      <table className="data" style={{ maxWidth: 640 }}>
        <thead><tr><th>Wanneer</th><th>Wie</th><th>Wat</th></tr></thead>
        <tbody>
          {d.log.map((l: any, i: number) => (
            <tr key={i}>
              <td className="mono sub">{tijd(l.op)}</td>
              <td>{l.door ?? "onbekend"}</td>
              <td className="sub">{l.actie}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
