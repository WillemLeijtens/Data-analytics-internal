import { useEffect, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";
import { EmptyProfileCard } from "../components/shared";

export default function Instellingen({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any>(null);
  const [wt, setWt] = useState<any[]>([]);
  const [rt, setRt] = useState<any[]>([]);
  const [mail, setMail] = useState<any[]>([]);
  const [spUrl, setSpUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => apiGet(`/${ctx.retailer}/instellingen`).then((d) => {
    setData(d); setWt(d.winkels_targets); setRt(d.rotatie_targets); setMail(d.mail_rules);
  });
  useEffect(() => { load(); setMsg(null); }, [ctx.retailer]);

  if (!data) return <p className="sub">Laden…</p>;
  if (!ctx.card?.profiel) return <EmptyProfileCard retailer={ctx.retailer} go={ctx.go} />;

  const caps = data.capabilities;
  const winkelsReadonly = !!caps?.winkel;   // ICI: store count comes from the facts
  const pWord = caps?.periode === "maand" ? "maand" : "week";

  const saveAll = async () => {
    await apiSend(`/${ctx.retailer}/instellingen`, "PUT", {
      winkels_targets: wt, rotatie_targets: rt, mail_rules: mail,
    });
    setMsg("Alles opgeslagen."); load();
  };

  const upd = (arr: any[], set: any, i: number, key: string, v: any) => {
    const copy = [...arr]; copy[i] = { ...copy[i], [key]: v }; set(copy);
  };

  return (
    <>
      <h1>Instellingen — {ctx.card?.naam}</h1>

      <h2>SharePoint koppeling</h2>
      {data.sharepoint ? (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="mono">{data.sharepoint.map_url}</span>
            <span className="tag pos">Gekoppeld</span>
          </div>
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
        </div>
      ) : (
        <div className="dropzone">
          <p className="sub">Koppel de SharePoint-map met contracten; de console interpreteert de documenten
            en bewaakt de vervaldatums.</p>
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
        <thead><tr><th>Merk</th><th>Land</th><th>Banner</th><th>Aantal winkels</th><th>Target € / winkel / {pWord}</th></tr></thead>
        <tbody>
          {wt.map((s, i) => (
            <tr key={`${s.merk}${s.land}${s.banner}`}>
              <td>{s.merk}</td><td>{s.land}</td><td>{s.banner ?? "—"}</td>
              <td>{winkelsReadonly
                ? <span className="sub" title="Komt uit de aanlevering">uit feed</span>
                : <input type="number" style={{ width: 90 }} value={s.aantal_winkels ?? ""}
                    onChange={(e) => upd(wt, setWt, i, "aantal_winkels", e.target.value ? +e.target.value : null)} />}
              </td>
              <td><input type="number" style={{ width: 90 }} value={s.target_per_winkel ?? ""}
                onChange={(e) => upd(wt, setWt, i, "target_per_winkel", e.target.value ? +e.target.value : null)} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Rotatie-target</h2>
      {caps?.artikel ? (
        <table className="data" style={{ maxWidth: 640 }}>
          <thead><tr><th>Merk</th><th>Target stuks / winkel / week</th></tr></thead>
          <tbody>
            {rt.map((t, i) => (
              <tr key={t.merk}>
                <td>{t.merk}</td>
                <td><input type="number" step="0.5" style={{ width: 90 }} value={t.stuks_per_winkel_per_week}
                  onChange={(e) => upd(rt, setRt, i, "stuks_per_winkel_per_week", +e.target.value)} /></td>
              </tr>
            ))}
            {!rt.length && <tr><td colSpan={2} className="sub">Nog geen rotatie-targets.</td></tr>}
          </tbody>
        </table>
      ) : (
        <div className="card" style={{ background: "var(--quiet)", boxShadow: "none" }}>
          <span className="sub">Niet van toepassing: deze retailer levert geen artikelniveau.</span>
        </div>
      )}

      <h2>Automatische import uit mail</h2>
      {mail.map((m, i) => (
        <div key={m.id ?? i} className="card" style={{ marginBottom: 10, display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
          <b>{m.naam}</b>
          <button className={`chip ${m.actief ? "" : "off"}`}
            onClick={() => upd(mail, setMail, i, "actief", m.actief ? 0 : 1)}>
            {m.actief ? "ACTIEF" : "UIT"}
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
