import { Fragment, useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";
import { EmptyProfileCard, LoadState, ThemaKeuze, Uitleg } from "../components/shared";


/** Winkelaantallen met terugwerkende kracht. Zonder datums wordt de hele
 *  historie door het getal van vandaag gedeeld en verdwijnt juist het effect
 *  van een gekrompen winkelbestand op de gemiddelde omzet per winkel. */
function MetingenBeheer({ retailer, rij, metingen, herlaad }:
  { retailer: string; rij: any; metingen: any[]; herlaad: () => void }) {
  const [open, setOpen] = useState(false);
  const [aantal, setAantal] = useState("");
  const [datum, setDatum] = useState("");
  const [fout, setFout] = useState<string | null>(null);

  const toevoegen = async () => {
    try {
      await apiSend(`/${retailer}/winkelaantallen`, "POST", {
        merk: rij.merk, land: rij.land, banner: rij.banner,
        aantal_winkels: +aantal, geldig_vanaf: datum,
      });
      setAantal(""); setDatum(""); setFout(null); herlaad();
    } catch (e: any) {
      setFout(String(e?.message ?? e));
    }
  };

  return (
    <div style={{ marginTop: 4 }}>
      <button className="chip off" style={{ fontSize: 10 }} onClick={() => setOpen(!open)}>
        {open ? "verberg historie" : `historie (${metingen.length})`}
      </button>
      {open && (
        <div style={{ marginTop: 6 }}>
          {metingen.map((m) => (
            <div key={m.id} className="sub" style={{ fontSize: 10.5, display: "flex", gap: 8, alignItems: "center" }}>
              <span className="mono">{m.geldig_vanaf}</span>
              <span>{m.aantal_winkels} winkels</span>
              <button className="chip off" style={{ fontSize: 9 }} title="Meting verwijderen"
                onClick={async () => {
                  await apiSend(`/${retailer}/winkelaantallen/${m.id}`, "DELETE");
                  herlaad();
                }}>✕</button>
            </div>
          ))}
          {!metingen.length && <div className="sub" style={{ fontSize: 10.5 }}>Nog geen metingen.</div>}
          <div style={{ display: "flex", gap: 5, marginTop: 5, alignItems: "center" }}>
            <input type="number" min={1} placeholder="aantal" style={{ width: 70 }}
              aria-label={`Historisch winkelaantal ${rij.merk}`}
              value={aantal} onChange={(e) => setAantal(e.target.value)} />
            <input type="date" style={{ width: 130 }} aria-label="Geldig vanaf"
              value={datum} onChange={(e) => setDatum(e.target.value)} />
            <button className="btn ghost" style={{ fontSize: 10, padding: "3px 8px" }}
              disabled={!aantal || !datum} onClick={toevoegen}>vastleggen</button>
          </div>
          {fout && <div className="sub sig-red" style={{ fontSize: 10.5 }}>{fout}</div>}
        </div>
      )}
    </div>
  );
}

// De handmatige rij is bewust weg: een merk-land-combinatie die niet in de
// feed zit heeft geen omzet om door een winkelaantal te delen, dus zo'n rij
// deed niets behalve de tabel vullen. De keuzes komen nu uit de feed.

/** Bedrijfsnormen: geldt voor de hele app, niet per retailer — het is een
 *  norm van ons, niet van hen. Twee drempels, want het zijn twee
 *  beslissingen: de eenmalige vulling is een investering die je één keer
 *  doet en mag krapper; de terugkerende omzet moet het jaar rond dragen. */
function BedrijfsnormenKaart() {
  const [data, setData] = useState<any>(null);
  const [een, setEen] = useState("");
  const [terug, setTerug] = useState("");
  const [bezig, setBezig] = useState(false);
  const [fout, setFout] = useState<string | null>(null);
  const [gelukt, setGelukt] = useState(false);

  const vul = (r: any) => {
    setData(r);
    setEen(r.drempel_eenmalig_pct == null ? "" : String(r.drempel_eenmalig_pct));
    setTerug(r.drempel_terugkerend_pct == null ? "" : String(r.drempel_terugkerend_pct));
  };
  useEffect(() => {
    apiGet("/systeem/bedrijf").then(vul).catch((e) => setFout(String(e?.message ?? e)));
  }, []);

  const opslaan = async () => {
    setBezig(true);
    setFout(null);
    setGelukt(false);
    try {
      // Leeg veld = geen drempel. Niet 0: dat zou "elke marge boven nul is
      // goed" betekenen, en dat is een norm in plaats van het ontbreken ervan.
      const getal = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
      vul(await apiSend("/systeem/bedrijf", "PUT", {
        drempel_eenmalig_pct: getal(een),
        drempel_terugkerend_pct: getal(terug),
      }));
      setGelukt(true);
    } catch (e: any) {
      setFout(String(e?.message ?? e));
    } finally {
      setBezig(false);
    }
  };

  if (!data) return null;
  return (
    <>
      <h2>Bedrijfsnormen</h2>
      <div className="card">
        <p className="sub" style={{ margin: "0 0 12px", maxWidth: 620 }}>
          De minimale nettomarge waaraan een project moet voldoen, als
          percentage van de omzet. De projectcalculator toetst er direct aan en
          zet een rode driehoek bij wat het niet haalt. Leeg laten betekent:
          niet meten.
        </p>
        <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label>
            <span className="eyebrow">Drempel eenmalige marge</span>
            <Uitleg tekst="De marge op de eerste vulling: sell-in min de eenmalige kosten (listing fee, display), gedeeld door die omzet. Een investering die je één keer doet — vaak mag die krapper dan de doorverkoop." /><br />
            <input type="number" min={0} max={99.9} step="0.1" size={6} value={een}
              aria-label="Drempel eenmalige marge" placeholder="—"
              onChange={(e) => setEen(e.target.value)} /> %
          </label>
          <label>
            <span className="eyebrow">Drempel terugkerende marge</span>
            <Uitleg tekst="De marge op de doorverkoop over de looptijd: die omzet min de looptijdkosten (marketing, co-op, logistiek), gedeeld door die omzet. Dit is wat het project het jaar rond moet dragen." /><br />
            <input type="number" min={0} max={99.9} step="0.1" size={6} value={terug}
              aria-label="Drempel terugkerende marge" placeholder="—"
              onChange={(e) => setTerug(e.target.value)} /> %
          </label>
          <button className="btn" disabled={bezig} onClick={opslaan}>
            {bezig ? "Bezig…" : "Opslaan"}
          </button>
          {gelukt && <span className="sub sig-green">Opgeslagen</span>}
          {fout && <span className="sub sig-red">{fout}</span>}
        </div>
        {data.bijgewerkt_op && (
          <p className="sub" style={{ margin: "10px 0 0" }}>
            Laatst gewijzigd {data.bijgewerkt_op.replace("T", " ")}
            {data.bijgewerkt_door ? ` door ${data.bijgewerkt_door}` : ""}
          </p>
        )}
      </div>
    </>
  );
}

/** Retailer-onafhankelijk: de Anthropic-sleutel geldt voor de hele app, dus
 *  dit blok laadt los van ctx.retailer en staat gelijk op elke
 *  Instellingenpagina. */
function AnthropicSleutelKaart() {
  const [status, setStatus] = useState<any>(null);
  const [invoer, setInvoer] = useState("");
  const [bezig, setBezig] = useState<"opslaan" | "testen" | null>(null);
  const [fout, setFout] = useState<string | null>(null);

  const laad = () => apiGet("/systeem/anthropic").then(setStatus).catch((e) => setFout(String(e?.message ?? e)));
  useEffect(() => { laad(); }, []);

  const opslaan = async () => {
    setBezig("opslaan"); setFout(null);
    try {
      const r = await apiSend("/systeem/anthropic", "PUT", { api_key: invoer });
      setStatus(r); setInvoer("");
    } catch (e: any) {
      setFout(String(e?.message ?? e));
    } finally {
      setBezig(null);
    }
  };

  const testen = async () => {
    setBezig("testen"); setFout(null);
    try {
      setStatus(await apiSend("/systeem/anthropic/test", "POST"));
    } catch (e: any) {
      setFout(String(e?.message ?? e));
    } finally {
      setBezig(null);
    }
  };

  if (!status) return null;
  const dot = status.laatst_status === "ok" ? "green" : status.ingesteld ? "red" : "grey";

  return (
    <>
      <h2>AI-contractanalyse (Claude API)</h2>
      <div className="card">
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span className={`brand-dot dot-${dot}`} style={{ width: 9, height: 9 }} />
          <span className="sub">
            {status.ingesteld
              ? `${status.gemaskeerd} · ${status.bron === "database" ? "uit de app" : "uit de omgeving"}`
              : "Geen sleutel ingesteld"}
          </span>
          {status.laatst_getest_op && (
            <span className="sub">
              laatst getest {status.laatst_getest_op.slice(0, 16).replace("T", " ")}
              {status.laatst_status === "fout" && status.laatst_melding ? ` — ${status.laatst_melding}` : ""}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
          <input type="password" placeholder="sk-ant-…" size={44} aria-label="Anthropic API-sleutel"
            value={invoer} onChange={(e) => setInvoer(e.target.value)} />
          <button className="btn" disabled={!invoer || bezig !== null} onClick={opslaan}>
            {bezig === "opslaan" ? "Bezig…" : "Opslaan & testen"}
          </button>
          {status.ingesteld && (
            <button className="btn ghost" disabled={bezig !== null} onClick={testen}>
              {bezig === "testen" ? "Bezig…" : "Test opnieuw"}
            </button>
          )}
        </div>
        <p className="sub" style={{ marginTop: 8 }}>
          Een lege sleutel opslaan wist de app-instelling en valt terug op de omgevingsvariabele
          (indien gezet). Voedt de contractanalyse bij Contract hieronder.
        </p>
        {fout && <p className="sub sig-red" style={{ marginTop: 8 }}>{fout}</p>}
      </div>
    </>
  );
}

export default function Instellingen({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [wt, setWt] = useState<any[]>([]);
  // Winkelaantallen per artikel. Blijven bewaard als een scope terug naar
  // merkniveau gaat: omschakelen mag geen invoer weggooien.
  const [aw, setAw] = useState<any[]>([]);
  // Vanaf hoeveel lege periodes een winkel "let op" of "gestopt" heet.
  const [ws, setWs] = useState<any | null>(null);
  // Welke rijen hun artikelen uitgeklapt tonen — schermstand, geen instelling.
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [rt, setRt] = useState<any[]>([]);
  const [mail, setMail] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [contractBezig, setContractBezig] = useState(false);
  const [contractFout, setContractFout] = useState<string | null>(null);
  const [contractHistorie, setContractHistorie] = useState<any[] | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/instellingen`).then((d) => {
    setData(d); setError(null);
    setWt(d.winkels_targets); setRt(d.rotatie_targets); setMail(d.mail_rules);
    setAw(d.artikel_winkels ?? []);
    setWs(d.winkelsignaal ?? null);
  }).catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { setData(null); load(); setMsg(null); }, [ctx.retailer]);

  if (!data) return <LoadState error={error} reload={load} />;
  if (!ctx.card?.profiel) {
    // Het thema is een voorkeur van de gebruiker, niet van de retailer, en
    // hoort dus ook bereikbaar te zijn zolang er nog geen profiel is.
    return (<>
      <h1>Instellingen</h1>
      <h2>Weergave</h2>
      <ThemaKeuze />
      <hr className="hairline" />
      <AnthropicSleutelKaart />
      <hr className="hairline" />
      <BedrijfsnormenKaart />
      <hr className="hairline" />
      <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />
    </>);
  }

  const caps = data.capabilities;
  const winkelsReadonly = !!caps?.winkel;   // ICI: store count comes from the facts
  const pWord = caps?.periode === "maand" ? "maand" : "week";

  const saveAll = async () => {
    try {
      await apiSend(`/${ctx.retailer}/instellingen`, "PUT", {
        winkels_targets: wt, artikel_winkels: aw, winkelsignaal: ws,
        rotatie_targets: rt, mail_rules: mail,
      });
      setMsg("Alles opgeslagen."); load();
    } catch (e: any) {
      setMsg(`Opslaan mislukt — er is niets gewijzigd. (${e?.message ?? e})`);
    }
  };

  const uploadContract = async (file: File) => {
    setContractBezig(true); setContractFout(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      await apiSend(`/${ctx.retailer}/contract`, "POST", fd);
      setContractHistorie(null);  // vorige historie is nu stale, opnieuw laden bij openen
      load();
    } catch (e: any) {
      setContractFout(String(e?.message ?? e));
    } finally {
      setContractBezig(false);
    }
  };

  const upd = (arr: any[], set: any, i: number, key: string, v: any) => {
    const copy = [...arr]; copy[i] = { ...copy[i], [key]: v }; set(copy);
  };
  const weg = (arr: any[], set: any, i: number) => set(arr.filter((_, j) => j !== i));

  // Rijen toevoegen: zonder dit is een verse installatie een doodlopende
  // straat — de tabellen begonnen leeg en er was niets om te bewerken.
  const wtKey = (s: any) => `${s.merk}|${s.land}|${s.banner ?? ""}`;
  // Vorige meting per scope: laat zien dat een merk in minder winkels ligt.
  const vorigeMeting: Record<string, any> = {};
  for (const h of data.winkels_historie ?? []) {
    const k = wtKey(h);
    vorigeMeting[k] = vorigeMeting[k] ? { ...vorigeMeting[k], vorig: vorigeMeting[k].nu } : {};
    vorigeMeting[k].nu = h;
  }
  // De artikelen die deze retailer voor deze scope levert, met het
  // ingestelde aantal. De lijst komt uit de feed: een artikel dat niet
  // geleverd wordt kan ook geen winkelaantal hebben.
  const artikelenVan = (s: any) => (data.feed_artikelen ?? [])
    .filter((a: any) => wtKey(a) === wtKey(s));
  const awKey = (a: any) => `${wtKey(a)}|${a.artikel_ean}`;
  // Wat de app zelf geteld heeft uit de aanlevering, per scope. Alleen
  // gevuld als de feed winkelniveau levert.
  const geteld: Record<string, any> = {};
  for (const g of data.feed_winkels ?? []) geteld[wtKey(g)] = g;
  const awWaarde = (s: any, ean: string) =>
    aw.find((a) => awKey(a) === `${wtKey(s)}|${ean}`)?.aantal_winkels ?? null;
  const zetAw = (s: any, ean: string, waarde: number | null) => {
    const sleutel = `${wtKey(s)}|${ean}`;
    const rest = aw.filter((a) => awKey(a) !== sleutel);
    setAw(waarde == null ? rest : [...rest, {
      merk: s.merk, land: s.land, banner: s.banner ?? null,
      artikel_ean: ean, aantal_winkels: waarde }]);
  };
  /** Het getal waarmee gerekend wordt: op artikelniveau het grootste artikel.
   *  Spiegelt engine/winkelniveau.effectief() — zie daar waarom het grootste
   *  en niet de som. */
  const effectief = (s: any): number | null => {
    if (s.niveau !== "artikel") return s.aantal_winkels ?? null;
    const getallen = artikelenVan(s)
      .map((a: any) => awWaarde(s, a.artikel_ean))
      .filter((v: number | null): v is number => !!v && v > 0);
    return getallen.length ? Math.max(...getallen) : null;
  };

  const feedCombos = (data.feed_combinaties ?? []).filter(
    (c: any) => c.merk && !wt.some((s) => wtKey(s) === wtKey(c)));
  const addWt = (merk: string, land: string | null, banner: string | null) =>
    setWt([...wt, { merk, land, banner, aantal_winkels: null,
                    target_per_winkel: null, niveau: "merk" }]);
  const feedMerken = Array.from(new Set((data.feed_combinaties ?? [])
    .map((c: any) => c.merk).filter(Boolean))) as string[];
  const rtMerken = feedMerken.filter((m) => !rt.some((t) => t.merk === m));

  return (
    <>
      <h1>Instellingen — {ctx.card?.naam}</h1>

      <h2>Weergave</h2>
      <ThemaKeuze />

      <AnthropicSleutelKaart />
      <hr className="hairline" />
      <BedrijfsnormenKaart />

      <h2>Contract</h2>
      {data.documenten.length ? (
        <div className="card">
          {data.documenten.map((d: any) => (
            <div key={d.id}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <b>{d.naam}</b>
                <span className="sub">{d.type ?? "—"}</span>
                <span className="mono sub">geldig tot {d.geldig_tot ?? "—"}</span>
                <span className={`brand-dot dot-${d.signaal}`} style={{ width: 9, height: 9 }} />
                <span className="sub" style={{ marginLeft: "auto" }}>
                  {d.bestandsnaam} · geüpload {d.geupload_op?.slice(0, 10) ?? "—"}
                  {d.geupload_door ? ` door ${d.geupload_door}` : ""}
                </span>
              </div>
              {d.conclusie && <p className="sub" style={{ marginTop: 10 }}>{d.conclusie}</p>}
              {!!d.condities?.length && (
                <table className="data" style={{ marginTop: 10 }}>
                  <thead><tr><th>Onderwerp</th><th>Afspraak</th></tr></thead>
                  <tbody>
                    {d.condities.map((c: any, i: number) => (
                      <tr key={i}><td>{c.onderwerp}</td><td>{c.afspraak}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
            <label className="btn ghost" style={{ cursor: contractBezig ? "default" : "pointer" }}>
              {contractBezig ? "Bezig met analyseren…" : "Nieuw contract uploaden (vervangt dit)"}
              <input type="file" accept="application/pdf" disabled={contractBezig} style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadContract(f); e.target.value = ""; }} />
            </label>
            <button className="chip off" style={{ fontSize: 10 }}
              onClick={async () => {
                if (contractHistorie) { setContractHistorie(null); return; }
                const r = await apiGet<{ historie: any[] }>(`/${ctx.retailer}/contract/historie`);
                setContractHistorie(r.historie);
              }}>
              {contractHistorie ? "verberg historie" : "eerdere contracten"}
            </button>
            {contractFout && <span className="sub sig-red">{contractFout}</span>}
          </div>
          {contractHistorie && (
            contractHistorie.length ? (
              <div style={{ marginTop: 10 }}>
                {contractHistorie.map((h: any) => (
                  <div key={h.id} className="sub" style={{ fontSize: 10.5, marginTop: 6, borderTop: "1px solid var(--t-border)", paddingTop: 6 }}>
                    <b>{h.naam}</b> — vervangen op {h.vervangen_op?.slice(0, 16).replace("T", " ")}
                    {h.geldig_tot ? ` · gold tot ${h.geldig_tot}` : ""}
                    {h.conclusie && <div style={{ marginTop: 2 }}>{h.conclusie}</div>}
                  </div>
                ))}
              </div>
            ) : <div className="sub" style={{ fontSize: 10.5, marginTop: 8 }}>Nog geen eerdere contracten.</div>
          )}
        </div>
      ) : (
        <div className="dropzone">
          <p className="sub">Upload het contract als PDF. Claude haalt automatisch de looptijd
            (loopt dit nog of is het verlopen) en de afgesproken condities eruit — dit voedt
            meteen het contractsignaal op de Overzicht-radar.</p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 10 }}>
            <label className="btn" style={{ cursor: contractBezig ? "default" : "pointer" }}>
              {contractBezig ? "Bezig met analyseren…" : "Contract uploaden"}
              <input type="file" accept="application/pdf" disabled={contractBezig} style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadContract(f); e.target.value = ""; }} />
            </label>
          </div>
          {contractFout && <p className="sub sig-red" style={{ marginTop: 10 }}>{contractFout}</p>}
        </div>
      )}

      <h2>Doelstellingen</h2>
      <p className="sub" style={{ marginTop: -6, maxWidth: 720 }}>
        Waar de analyses aan meten: het winkelbestand waar de omzet per winkel
        door gedeeld wordt, het omzettarget per winkel, en het rotatietarget
        per artikel.
      </p>

      <h3>Winkelaantallen en targets</h3>
      <table className="data">
        <thead><tr><th>Merk</th><th>Land</th><th>Formule</th><th>Niveau</th><th>Aantal winkels</th><th>Target € / winkel / {pWord}</th><th></th></tr></thead>
        <tbody>
          {wt.map((s, i) => (
            <Fragment key={`${s.merk}${s.land}${s.banner}`}>
            <tr>
              <td>{s.merk}</td><td>{s.land}</td><td>{s.banner ?? "—"}</td>
              <td>{winkelsReadonly ? <span className="sub">—</span> : (
                <div className="seg">
                  <button className={s.niveau !== "artikel" ? "on" : ""}
                    onClick={() => upd(wt, setWt, i, "niveau", "merk")}>Merk</button>
                  <button className={s.niveau === "artikel" ? "on" : ""}
                    onClick={() => {
                      upd(wt, setWt, i, "niveau", "artikel");
                      setOpen({ ...open, [wtKey(s)]: true });
                    }}>Artikel</button>
                </div>
              )}</td>
              <td>{winkelsReadonly
                ? (() => {
                    // Automatisch ingevuld: het aantal winkels MET omzet in
                    // het laatste jaar van de feed. Het getal tonen in plaats
                    // van alleen "uit feed" — anders moet je het elders
                    // opzoeken om te weten waar de app mee rekent.
                    const g = geteld[wtKey(s)];
                    if (!g) return <span className="sub" title="Komt uit de aanlevering">uit feed</span>;
                    return (
                      <>
                        <b>{g.aantal_winkels}</b>
                        <div className="sub" style={{ fontSize: 10.5, marginTop: 2 }}>
                          automatisch ingevuld
                          <Uitleg tekst={`Geteld uit het importbestand: winkels met omzet voor dit merk in ${g.jaar}. Niet handmatig in te vullen — een afwijkend getal zou stilletjes winnen in de schermen die het gebruiken. Winkels die het hele jaar niets verkochten tellen niet mee; die zouden de omzet per winkel omlaag drukken zonder dat er iets veranderd is.`} />
                        </div>
                      </>
                    );
                  })()
                : s.niveau === "artikel"
                ? <>
                    {/* Het merkgetal is hier een AFGELEIDE: het grootste
                        artikel. Zie engine/winkelniveau.py voor waarom niet
                        de som — en waarom dit het merkgemiddelde iets te
                        hoog kan laten uitvallen als artikelen in
                        verschillende winkels liggen. */}
                    <b>{effectief(s) ?? "—"}</b>
                    <Uitleg tekst="Afgeleid uit de artikelen hieronder: het aantal winkels van het grootste artikel. Niet de som — een winkel die twee artikelen voert zou dan dubbel tellen. Liggen artikelen juist in verschillende winkels, dan is het echte aantal hoger en valt de omzet per winkel op merkniveau iets te hoog uit." />
                    <div className="sub" style={{ fontSize: 10.5 }}>
                      <button className="chip off" style={{ fontSize: 10 }}
                        onClick={() => setOpen({ ...open, [wtKey(s)]: !open[wtKey(s)] })}>
                        {open[wtKey(s)] ? "verberg" : "toon"} {artikelenVan(s).length} artikelen
                      </button>
                    </div>
                  </>
                : <>
                    <input type="number" min={1} style={{ width: 90 }} value={s.aantal_winkels ?? ""}
                      aria-label={`Aantal winkels ${s.merk} ${s.land ?? ""} ${s.banner ?? ""}`}
                      onChange={(e) => upd(wt, setWt, i, "aantal_winkels", e.target.value ? +e.target.value : null)} />
                    {(() => {
                      // Was het eerder anders? Dan is dát het distributieverhaal.
                      const h = vorigeMeting[wtKey(s)];
                      if (!h?.vorig || h.vorig.aantal_winkels === h.nu.aantal_winkels) return null;
                      const omlaag = h.nu.aantal_winkels < h.vorig.aantal_winkels;
                      return (
                        <div className="sub" style={{ fontSize: 10.5, marginTop: 2 }}
                          title={`Gewijzigd op ${h.nu.gemeten_op?.slice(0, 10)}`}>
                          <span className={omlaag ? "sig-red" : "sig-green"}>
                            {omlaag ? "▼" : "▲"} was {h.vorig.aantal_winkels}
                          </span>{" "}sinds {h.nu.geldig_vanaf ?? h.nu.gemeten_op?.slice(0, 10)}
                        </div>
                      );
                    })()}
                    <MetingenBeheer retailer={ctx.retailer} rij={s}
                      metingen={(data.winkels_historie ?? []).filter((h: any) => wtKey(h) === wtKey(s))}
                      herlaad={load} />
                  </>}
              </td>
              <td><input type="number" min={0} style={{ width: 90 }} value={s.target_per_winkel ?? ""}
                aria-label={`Target per winkel ${s.merk} ${s.land ?? ""} ${s.banner ?? ""}`}
                onChange={(e) => upd(wt, setWt, i, "target_per_winkel", e.target.value ? +e.target.value : null)} /></td>
              <td><button className="chip off" title="Rij verwijderen (pas definitief na Alles opslaan)"
                onClick={() => weg(wt, setWt, i)}>✕</button></td>
            </tr>
            {/* Artikelniveau: de gekoppelde artikelen uit de feed, elk met
                een eigen winkelaantal. Het merkgetal erboven volgt eruit. */}
            {s.niveau === "artikel" && open[wtKey(s)] && (
              artikelenVan(s).length
                ? artikelenVan(s).map((a: any) => (
                    <tr key={awKey(a)} className="sub">
                      <td colSpan={3} style={{ paddingLeft: 26 }}>
                        ↳ {a.artikel_naam || "naamloos"}
                        <span className="mono" style={{ marginLeft: 8 }}>{a.artikel_ean}</span>
                      </td>
                      <td className="sub">artikel</td>
                      <td>
                        <input type="number" min={1} style={{ width: 90 }}
                          value={awWaarde(s, a.artikel_ean) ?? ""}
                          aria-label={`Aantal winkels ${a.artikel_naam || a.artikel_ean}`}
                          onChange={(e) => zetAw(s, a.artikel_ean,
                            e.target.value ? +e.target.value : null)} />
                      </td>
                      {/* Targets blijven op merk-landniveau: een target per
                          artikel is een andere afspraak dan we maken. */}
                      <td colSpan={2}></td>
                    </tr>
                  ))
                : <tr><td colSpan={7} className="sub" style={{ paddingLeft: 26 }}>
                    Geen artikelen in de feed voor deze combinatie — deze retailer
                    levert geen artikelniveau, of er is nog niets geïmporteerd.
                  </td></tr>
            )}
            </Fragment>
          ))}
          {!wt.length && !feedCombos.length && (
            <tr><td colSpan={7} className="sub">Nog geen rijen — importeer eerst een bestand.</td></tr>
          )}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
        {feedCombos.length > 0 && <span className="sub">Uit de feed:</span>}
        {feedCombos.map((c: any) => (
          <button key={wtKey(c)} className="chip" onClick={() => addWt(c.merk, c.land, c.banner)}>
            + {c.merk}{c.land ? ` · ${c.land}` : ""}{c.banner ? ` · ${c.banner}` : ""}
          </button>
        ))}
      </div>

      {winkelsReadonly && ws && (
        <>
          <h3>Stille winkels</h3>
          <p className="sub" style={{ marginTop: -6, maxWidth: 700 }}>
            Vanaf hoeveel opeenvolgende {pWord}en zonder omzet een winkel op
            het dashboard onder <b>Let op</b> valt, en vanaf hoeveel onder
            <b> Gestopte winkels</b>. Wat daaronder blijft wordt niet gemeld.
            Deze drempels zijn de <b>ondergrens</b>: daarbovenop weegt de app
            automatisch het eigen verkoopritme van elke winkel mee — een
            winkel die om de drie {pWord}en iets verkoopt is na zes stille{" "}
            {pWord}en niet gestopt, dat is zijn patroon.
          </p>
          <div className="card" style={{ display: "flex", gap: 22, flexWrap: "wrap",
                                          alignItems: "flex-end" }}>
            <label>
              <span className="eyebrow">Let op vanaf</span>
              <Uitleg tekst={`Nog geen conclusie, wel opvallend: deze winkel verkocht dit merk een aantal ${pWord}en niet meer. Minimaal 1.`} /><br />
              <input type="number" min={1} max={104} size={5} value={ws.letop_vanaf}
                aria-label="Let op vanaf"
                onChange={(e) => setWs({ ...ws, letop_vanaf: +e.target.value })} /> {pWord}en
            </label>
            <label>
              <span className="eyebrow">Gestopt vanaf</span>
              <Uitleg tekst={`Vanaf hier telt de winkel als gestopt en telt zijn gemiste omzet mee in het totaal. Kan niet lager liggen dan de 'let op'-drempel.`} /><br />
              <input type="number" min={ws.letop_vanaf} max={104} size={5}
                value={ws.gestopt_vanaf} aria-label="Gestopt vanaf"
                onChange={(e) => setWs({ ...ws, gestopt_vanaf: +e.target.value })} /> {pWord}en
            </label>
            {/* De standaard is geredeneerd in maanden; bij een weekfeed is
                twee lege weken niets. Dat hoort hier te staan, niet in een
                commit-bericht. */}
            {pWord === "week" && ws.gestopt_vanaf <= 2 && (
              <span className="sub" style={{ flex: "1 1 260px", color: "var(--warn)" }}>
                Deze feed levert per week. Twee lege weken is bij een
                langzaamloper normaal — op een echte export leverde die
                instelling honderden meldingen op met € 0 gemiste omzet.
              </span>
            )}
          </div>
        </>
      )}

      <h3>Rotatietarget</h3>
      {caps?.artikel ? (
        <>
          <table className="data" style={{ maxWidth: 640 }}>
            <thead><tr><th>Merk</th><th>Target stuks / winkel / week</th><th></th></tr></thead>
            <tbody>
              {rt.map((t, i) => (
                <tr key={t.merk}>
                  <td>{t.merk}</td>
                  <td><input type="number" step="0.5" min={0.5} style={{ width: 90 }}
                    value={t.stuks_per_winkel_per_week ?? ""}
                    aria-label={`Rotatietarget ${t.merk}`}
                    onChange={(e) => upd(rt, setRt, i, "stuks_per_winkel_per_week",
                      e.target.value ? +e.target.value : null)} /></td>
                  <td><button className="chip off" title="Rij verwijderen (pas definitief na Alles opslaan)"
                    onClick={() => weg(rt, setRt, i)}>✕</button></td>
                </tr>
              ))}
              {!rt.length && !rtMerken.length &&
                <tr><td colSpan={3} className="sub">Nog geen rotatietargets — importeer eerst een bestand.</td></tr>}
            </tbody>
          </table>
          {rtMerken.length > 0 && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
              <span className="sub">Uit de feed:</span>
              {rtMerken.map((m) => (
                <button key={m} className="chip"
                  onClick={() => setRt([...rt, { merk: m, stuks_per_winkel_per_week: null }])}>
                  + {m}
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="card" style={{ background: "var(--t-card2)", boxShadow: "none" }}>
          <span className="sub">Niet van toepassing: deze retailer levert geen artikelniveau.</span>
        </div>
      )}

      <h2>Automatische import uit mail</h2>
      {/* Er draait nog geen poller voor de console: een klikbare ACTIEF-
          toggle zou beloven dat er iets gebeurt terwijl er niets gebeurt. */}
      <div className="level-strip" style={{ borderLeft: "3px solid var(--warn)" }}>
        <span className="sub"><b>Nog niet actief.</b> Importeren gaat op dit moment handmatig
          via <a style={{ cursor: "pointer" }} onClick={() => ctx.go(ctx.retailer, "import")}>Import</a>.
          De regels hieronder worden bewaard en gaan werken zodra de mailkoppeling live is.</span>
      </div>
      {mail.map((m, i) => (
        <div key={m.id ?? i} className="card" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
          <b>{m.naam}</b>
          <button className="chip off" disabled
            title="Nog niet actief: de mailkoppeling voor de console bestaat nog niet">
            {m.actief ? "ACTIEF (WACHT OP KOPPELING)" : "UIT"}
          </button>
          <span className="mono">{m.afzender}</span>
          <span className="mono sub">{m.bijlage_glob}</span>
          <span className="sub" style={{ marginLeft: "auto" }}>laatste run: {m.laatste_run ?? "—"}</span>
        </div>
      ))}

      <div style={{ display: "flex", gap: 14, alignItems: "center", marginTop: 24 }}>
        <button className="btn" onClick={saveAll}>Alles opslaan</button>
        <span className="sub">{msg ?? "Opslaan gebeurt in één keer (atomair): alles of niets."}</span>
      </div>
    </>
  );
}
