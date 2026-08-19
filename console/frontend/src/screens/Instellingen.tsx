import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";
import { EmptyProfileCard, LoadState } from "../components/shared";


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

/** Handmatig een merk/land/banner-rij toevoegen, voor combinaties die (nog)
 *  niet in de feed zitten. */
function HandmatigeRij({ onAdd }: { onAdd: (m: string, l: string | null, b: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const [merk, setMerk] = useState("");
  const [land, setLand] = useState("");
  const [banner, setBanner] = useState("");
  if (!open) {
    return <button className="chip off" onClick={() => setOpen(true)}>+ handmatig een rij toevoegen</button>;
  }
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <input type="text" placeholder="Merk" size={12} aria-label="Merk"
        value={merk} onChange={(e) => setMerk(e.target.value.toUpperCase())} />
      <input type="text" placeholder="Land" size={4} aria-label="Land"
        value={land} onChange={(e) => setLand(e.target.value.toUpperCase())} />
      <input type="text" placeholder="Banner" size={6} aria-label="Banner (optioneel)"
        value={banner} onChange={(e) => setBanner(e.target.value.toUpperCase())} />
      <button className="btn ghost" disabled={!merk.trim()}
        onClick={() => {
          onAdd(merk.trim(), land.trim() || null, banner.trim() || null);
          setMerk(""); setLand(""); setBanner(""); setOpen(false);
        }}>Toevoegen</button>
      <button className="chip off" onClick={() => setOpen(false)}>annuleer</button>
    </span>
  );
}

export default function Instellingen({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [wt, setWt] = useState<any[]>([]);
  const [rt, setRt] = useState<any[]>([]);
  const [mail, setMail] = useState<any[]>([]);
  const [spUrl, setSpUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/instellingen`).then((d) => {
    setData(d); setError(null);
    setWt(d.winkels_targets); setRt(d.rotatie_targets); setMail(d.mail_rules);
  }).catch((e) => setError(String(e?.message ?? e)));
  useEffect(() => { setData(null); load(); setMsg(null); }, [ctx.retailer]);

  if (!data) return <LoadState error={error} reload={load} />;
  if (!ctx.card?.profiel) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const caps = data.capabilities;
  const winkelsReadonly = !!caps?.winkel;   // ICI: store count comes from the facts
  const pWord = caps?.periode === "maand" ? "maand" : "week";

  const saveAll = async () => {
    try {
      await apiSend(`/${ctx.retailer}/instellingen`, "PUT", {
        winkels_targets: wt, rotatie_targets: rt, mail_rules: mail,
      });
      setMsg("Alles opgeslagen."); load();
    } catch (e: any) {
      setMsg(`Opslaan mislukt — er is niets gewijzigd. (${e?.message ?? e})`);
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
  const feedCombos = (data.feed_combinaties ?? []).filter(
    (c: any) => c.merk && !wt.some((s) => wtKey(s) === wtKey(c)));
  const addWt = (merk: string, land: string | null, banner: string | null) =>
    setWt([...wt, { merk, land, banner, aantal_winkels: null, target_per_winkel: null }]);
  const feedMerken = Array.from(new Set((data.feed_combinaties ?? [])
    .map((c: any) => c.merk).filter(Boolean))) as string[];
  const rtMerken = feedMerken.filter((m) => !rt.some((t) => t.merk === m));

  return (
    <>
      <h1>Instellingen — {ctx.card?.naam}</h1>

      <h2>SharePoint koppeling</h2>
      {data.sharepoint ? (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="mono">{data.sharepoint.map_url}</span>
            <span className={`tag ${data.documenten.length ? "pos" : ""}`}>
              {data.documenten.length ? "Gekoppeld" : "Geregistreerd"}
            </span>
          </div>
          {data.documenten.length ? (
            <>
              <table className="data" style={{ marginTop: 14 }}>
                <thead><tr><th>Document</th><th>Type</th><th>Geldig tot</th><th>Signaal</th></tr></thead>
                <tbody>
                  {data.documenten.map((d: any) => (
                    <tr key={d.id}>
                      <td>{d.naam}</td><td>{d.type ?? "—"}</td><td className="mono">{d.geldig_tot ?? "—"}</td>
                      <td><span className={`brand-dot dot-${d.signaal}`} style={{ width: 9, height: 9 }} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="sub" style={{ marginTop: 10 }}>Deze documenten voeden het contractsignaal op de Overzicht-radar.</p>
            </>
          ) : (
            // Eerlijk over wat er (nog niet) gebeurt: de koppeling met
            // Microsoft Graph bestaat nog niet, dus er wordt niets bewaakt.
            <p className="sub" style={{ marginTop: 10 }}>
              De map is geregistreerd. Documentbewaking volgt zodra de Microsoft
              Graph-koppeling er is — er worden nu nog géén documenten opgehaald
              en het contractsignaal blijft grijs.
            </p>
          )}
        </div>
      ) : (
        <div className="dropzone">
          <p className="sub">Registreer hier de SharePoint-map met contracten. Zodra de Microsoft
            Graph-koppeling er is, worden de documenten opgehaald en de vervaldatums bewaakt.</p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 10 }}>
            <input type="url" placeholder="https://…sharepoint.com/sites/…" size={44}
              value={spUrl} onChange={(e) => setSpUrl(e.target.value)} />
            <button className="btn" disabled={!spUrl}
              onClick={async () => { await apiSend(`/${ctx.retailer}/sharepoint`, "POST", { map_url: spUrl }); load(); }}>
              Map koppelen
            </button>
          </div>
        </div>
      )}

      <h2>Winkelaantallen en targets</h2>
      <table className="data">
        <thead><tr><th>Merk</th><th>Land</th><th>Banner</th><th>Aantal winkels</th><th>Target € / winkel / {pWord}</th><th></th></tr></thead>
        <tbody>
          {wt.map((s, i) => (
            <tr key={`${s.merk}${s.land}${s.banner}`}>
              <td>{s.merk}</td><td>{s.land}</td><td>{s.banner ?? "—"}</td>
              <td>{winkelsReadonly
                ? <span className="sub" title="Komt uit de aanlevering">uit feed</span>
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
          ))}
          {!wt.length && !feedCombos.length && (
            <tr><td colSpan={6} className="sub">Nog geen rijen — importeer eerst een bestand,
              of voeg hieronder handmatig een rij toe.</td></tr>
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
        <HandmatigeRij onAdd={addWt} />
      </div>

      <h2>Rotatietarget</h2>
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
        <div className="card" style={{ background: "var(--quiet)", boxShadow: "none" }}>
          <span className="sub">Niet van toepassing: deze retailer levert geen artikelniveau.</span>
        </div>
      )}

      <h2>Automatische import uit mail</h2>
      {/* Er draait nog geen poller voor de console: een klikbare ACTIEF-
          toggle zou beloven dat er iets gebeurt terwijl er niets gebeurt. */}
      <div className="level-strip" style={{ borderLeft: "3px solid #B4690E" }}>
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
