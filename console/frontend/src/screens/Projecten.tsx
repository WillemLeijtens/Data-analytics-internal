import { useEffect, useState } from "react";
import { apiGet, apiSend, fmtEur } from "../api";
import { ShellCtx } from "../App";
import { LoadState, Uitleg } from "../components/shared";

/* De formules staan hier nog een keer, alleen voor directe feedback tijdens
   het typen; de backend (engine/projecten.py) is de geteste bron en levert
   de cijfers voor de lijst en na het opslaan. */
const n = (v: any) => (v == null || v === "" ? 0 : +v || 0);

function looptijdWeken(start?: string | null, eind?: string | null): number | null {
  if (!start || !eind) return null;
  const dagen = (new Date(eind).getTime() - new Date(start).getTime()) / 86400000;
  if (dagen < 0 || isNaN(dagen)) return null;
  return Math.max(1, Math.round(dagen / 7));
}

function bereken(proj: any, producten: any[], kosten: any[]) {
  const rijen = producten.map((p) => {
    const margeStuk = n(p.verkoopprijs) - n(p.kostprijs) - n(p.verpakking_per_stuk);
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
  const kostenEenmalig = kosten.filter((k) => !k.terugkerend).reduce((a, k) => a + n(k.bedrag), 0);
  const kostenLooptijd = kosten.filter((k) => k.terugkerend).reduce((a, k) => a + n(k.bedrag), 0);
  const som = (veld: string) => rijen.reduce((a, r: any) => a + r[veld], 0);
  const eenOmzet = som("eenmalig_omzet"), eenProductmarge = som("eenmalig_marge");
  const weekOmzet = som("week_omzet"), weekMarge = som("week_marge");
  const eenMarge = eenProductmarge - kostenEenmalig;
  const terugOmzet = weken ? weekOmzet * weken : null;
  const terugMarge = weken ? weekMarge * weken - kostenLooptijd : null;
  const pct = (m: number, o: number) => (o ? (m / o) * 100 : null);
  return {
    rijen, weken,
    eenmalig: { omzet: eenOmzet, productmarge: eenProductmarge, kosten: kostenEenmalig,
                marge: eenMarge, pct: pct(eenMarge, eenOmzet) },
    terugkerend: { weekOmzet, weekMarge, omzet: terugOmzet, kosten: kostenLooptijd,
                   marge: terugMarge,
                   pct: terugMarge != null && terugOmzet ? pct(terugMarge, terugOmzet) : null },
    totaal: { omzet: eenOmzet + (terugOmzet ?? 0), marge: eenMarge + (terugMarge ?? 0) },
  };
}

const pctTxt = (v: number | null) => (v == null ? "" : ` · ${v.toLocaleString("nl-NL", { maximumFractionDigits: 1 })}%`);
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
  const basis = `${weken} ${weken === 1 ? "week" : "weken"}`;
  if (nu < s) return `${basis} · start over ${Math.max(1, Math.ceil((s - nu) / 604800000))} wk`;
  if (nu > e) return `${basis} · afgelopen`;
  return `${basis} · nog ${Math.max(1, Math.ceil((e - nu) / 604800000))} wk`;
}

function Cel({ children }: { children: React.ReactNode }) {
  return <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{children}</td>;
}

function Geld({ v, accent }: { v: number | null; accent?: boolean }) {
  if (v == null) return <span className="sub">—</span>;
  return <span className={accent ? (v >= 0 ? "sig-green" : "sig-red") : undefined}>{fmtEur(v)}</span>;
}

const LEEG_PRODUCT = { naam: "", kostprijs: null, verkoopprijs: null, aantal_winkels: null,
                       stuks_per_winkel: null, rotatie_per_winkel_per_week: null,
                       verpakking_per_stuk: null };

export default function Projecten({ ctx }: { ctx: ShellCtx }) {
  const [lijst, setLijst] = useState<any[] | null>(null);
  const [gekozen, setGekozen] = useState<number | null>(null);
  const [d, setD] = useState<any | null>(null);          // het open project
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Naam voor het logboek: per browser bewaard, één keer invullen.
  const [naam, setNaam] = useState(() => localStorage.getItem("bl-naam") ?? "");
  useEffect(() => { localStorage.setItem("bl-naam", naam); }, [naam]);

  const laadLijst = () => apiGet("/projecten")
    .then((r) => { setLijst(r); setError(null); })
    .catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { laadLijst(); }, []);

  const open = (id: number) => {
    setGekozen(id); setD(null); setMsg(null);
    apiGet(`/projecten/${id}`).then(setD).catch((e) => setError(String(e?.message ?? e)));
  };
  const sluit = () => { setGekozen(null); setD(null); setMsg(null); laadLijst(); };

  const nieuw = async () => {
    try {
      const p = await apiSend<any>("/projecten", "POST", {
        naam: "Nieuw project",
        retailer_id: ctx.retailer !== "alle" ? ctx.retailer : null,
        door: naam || null,
      });
      setLijst(null); setGekozen(p.id); setD(p);
    } catch (e: any) { setError(String(e?.message ?? e)); }
  };

  const opslaan = async () => {
    try {
      const r = await apiSend<any>(`/projecten/${d.id}`, "PUT", { ...d, door: naam || null });
      setD(r); setMsg("Opgeslagen.");
    } catch (e: any) { setMsg(`Opslaan mislukt — er is niets gewijzigd. (${e?.message ?? e})`); }
  };

  const verwijder = async () => {
    if (!window.confirm(`Project "${d.naam}" definitief verwijderen?`)) return;
    await apiSend(`/projecten/${d.id}`, "DELETE");
    sluit();
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
                  breed = 74, stap?: string) => (
    <input type="number" min={0} step={stap ?? "0.01"} style={{ width: breed }}
      value={num(d[lijstNaam][i][veld])} aria-label={veld}
      onChange={(e) => zetRij(lijstNaam, i, veld, e.target.value === "" ? null : +e.target.value)} />
  );

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
            Jouw naam voor het logboek
            <Uitleg tekst="Wordt vastgelegd bij aanmaken en wijzigen, zodat het logboek laat zien wie wat deed. Eén keer invullen; blijft in deze browser bewaard." />
            <input type="text" placeholder="bijv. Willem" size={12} style={{ marginLeft: 8 }}
              value={naam} onChange={(e) => setNaam(e.target.value)} />
          </span>
        </div>
        <table className="data">
          <thead><tr>
            <th>Project</th><th>Retailer</th><th>Looptijd</th>
            <th style={{ textAlign: "right" }}>Eenmalige marge</th>
            <th style={{ textAlign: "right" }}>Terugkerende marge</th>
            <th>Laatst gewijzigd</th>
          </tr></thead>
          <tbody>
            {lijst.map((p) => (
              <tr key={p.id} className="click" onClick={() => open(p.id)}>
                <td>{p.naam}<br /><span className="sub">{p.aantal_producten} product{p.aantal_producten === 1 ? "" : "en"}</span></td>
                <td>{p.retailer_naam ?? "—"}</td>
                <td className="sub">{looptijdTekst(p.start_datum, p.eind_datum)}</td>
                <Cel><Geld v={p.eenmalig.marge} accent /></Cel>
                <Cel><Geld v={p.terugkerend.marge} accent /></Cel>
                <td className="sub">{tijd(p.gewijzigd_op ?? p.aangemaakt_op)} · {p.gewijzigd_door ?? p.aangemaakt_door ?? "onbekend"}</td>
              </tr>
            ))}
            {!lijst.length && <tr><td colSpan={6} className="sub">
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
            <th>Verpakking / stuk<Uitleg tekst="Verpakkingskosten per stuk; gaat van de marge per stuk af (eenmalig én terugkerend). Eenmalige verpakkingskosten die niet per stuk te verdelen zijn, zet je bij de kosten hieronder." /></th>
            <th style={{ textAlign: "right" }}>Eenmalig omzet / marge</th>
            <th style={{ textAlign: "right" }}>Per week omzet / marge</th>
            <th></th>
          </tr></thead>
          <tbody>
            {d.producten.map((p: any, i: number) => (
              <tr key={i}>
                <td><input type="text" size={16} value={p.naam} aria-label="Productnaam"
                  onChange={(e) => zetRij("producten", i, "naam", e.target.value)} /></td>
                <td>{invoer("producten", i, "kostprijs")}</td>
                <td>{invoer("producten", i, "verkoopprijs")}</td>
                <td>{invoer("producten", i, "aantal_winkels", 64, "1")}</td>
                <td>{invoer("producten", i, "stuks_per_winkel", 64, "1")}</td>
                <td>{invoer("producten", i, "rotatie_per_winkel_per_week", 64, "0.1")}</td>
                <td>{invoer("producten", i, "verpakking_per_stuk")}</td>
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
            {!d.producten.length && <tr><td colSpan={10} className="sub">Nog geen producten.</td></tr>}
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
                : k.label}</td>
              <td>{invoer("kosten", i, "bedrag", 96)}</td>
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
      <button className="chip" style={{ marginTop: 8 }}
        onClick={() => setD({ ...d, kosten: [...d.kosten, { soort: "overig", label: "", bedrag: null, terugkerend: 0 }] })}>
        + extra kostenregel
      </button>

      <h2>Resultaat</h2>
      <div className="grid kpi">
        <div className="card">
          <div className="kpi-label">Eenmalig — de vulling
            <Uitleg tekst="De eerste levering: winkels x stuks per winkel, tegen verkoopprijs. Marge = omzet min productkosten min de eenmalige kostenregels." /></div>
          <div className="kpi-value">{fmtEur(b.eenmalig.marge)}</div>
          <div className="kpi-sub">marge{pctTxt(b.eenmalig.pct)} · omzet {fmtEur(b.eenmalig.omzet)}</div>
          <div className="kpi-sub">productmarge {fmtEur(b.eenmalig.productmarge)} − kosten {fmtEur(b.eenmalig.kosten)}</div>
        </div>
        <div className="card">
          <div className="kpi-label">Terugkerend — de doorverkoop
            <Uitleg tekst="Rotatie x winkels, per week en opgeteld over de looptijd. De looptijdkosten gaan hier vanaf. Zonder start- en einddatum is er alleen een weekbeeld." /></div>
          <div className="kpi-value">{b.terugkerend.marge != null ? fmtEur(b.terugkerend.marge) : "—"}</div>
          <div className="kpi-sub">
            {b.weken
              ? <>marge over {b.weken} wk{pctTxt(b.terugkerend.pct)} · omzet {fmtEur(b.terugkerend.omzet!)} − kosten {fmtEur(b.terugkerend.kosten)}</>
              : "vul start- en einddatum in voor het looptijdtotaal"}
          </div>
          <div className="kpi-sub">per week: {fmtEur(b.terugkerend.weekOmzet)} omzet · {fmtEur(b.terugkerend.weekMarge)} marge</div>
        </div>
        <div className="card">
          <div className="kpi-label">Totaal project</div>
          <div className="kpi-value">{fmtEur(b.totaal.marge)}</div>
          <div className="kpi-sub">marge · omzet {fmtEur(b.totaal.omzet)}</div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 18, flexWrap: "wrap" }}>
        <button className="btn" onClick={opslaan}>Opslaan</button>
        <span className="sub">{msg ?? "Wijzigingen staan pas vast na Opslaan."}</span>
        <span className="sub" style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center" }}>
          Jouw naam
          <Uitleg tekst="Komt in het logboek bij deze wijziging." />
          <input type="text" placeholder="bijv. Willem" size={10} style={{ marginLeft: 8 }}
            value={naam} onChange={(e) => setNaam(e.target.value)} />
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
