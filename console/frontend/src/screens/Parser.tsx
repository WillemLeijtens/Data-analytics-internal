import { useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "../api";
import { ShellCtx } from "../App";

/** Leesscherm. Parsers worden per retailer in het Claude Code-project
 *  gebouwd tegen een echt aanleverbestand; in de app valt er niets in te
 *  stellen. Hier zie je alleen wát de parser herkent en levert, en kun je
 *  een bestand controleren zonder het te importeren. */
export default function Parser({ ctx }: { ctx: ShellCtx }) {
  const [profiles, setProfiles] = useState<any[]>([]);
  const [testResult, setTestResult] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTestResult(null); setMsg(null);
    apiGet("/parser/profielen")
      .then(setProfiles)
      .catch((e) => setMsg(`Profielen laden mislukt: ${e?.message ?? e}`));
  }, [ctx.retailer]);

  const sel = profiles.find((p) => p.retailer_id === ctx.retailer) ?? null;
  const caps = sel?.capabilities ?? null;

  const controleer = async (f: File | null) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      setTestResult(await apiSend(`/parser/${ctx.retailer}/test`, "POST", fd));
    } catch (e: any) {
      setMsg(`Controleren mislukt: ${e?.message ?? e}`);
    }
  };

  if (!sel) {
    return (<>
      <h1>Parser — {ctx.card?.naam}</h1>
      <div className="card">
        <div className="eyebrow">Nog geen parser voor deze retailer</div>
        <p className="sub" style={{ marginTop: 10 }}>
          Elke retailer heeft een <b>eigen ingebouwde parser</b>, gebouwd in het
          Claude&nbsp;Code-project tegen een écht aanleverbestand — pas dan is
          zeker dat tabbladen, kolommen en totalen kloppen. Kruidvat en
          ICI&nbsp;Paris&nbsp;XL werken zo.
        </p>
        <p className="sub">
          <b>Wat jij doet:</b> deel een voorbeeldbestand van deze retailer.
          Zodra de parser meekomt met een update, upload je gewoon bij
          <b> Import</b> en verschijnen alle analyses vanzelf.
        </p>
      </div>
    </>);
  }

  const levert: [string, boolean][] = [
    ["Merk", !!caps?.merk], ["Artikel (EAN)", !!caps?.artikel],
    ["Winkel", !!caps?.winkel], ["Formule", !!caps?.banner],
    ["Land", !!caps?.land], ["Volume (stuks)", !!caps?.volume],
  ];
  const builtin = sel.definition?.builtin;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
        <div>
          <h1>Parser — {ctx.card?.naam}</h1>
          <p className="sub">Deze retailer heeft een <b>ingebouwde parser</b>: bestanden
            worden automatisch herkend en ingelezen. Er is niets in te stellen.</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn ghost" onClick={() => fileRef.current?.click()}>Controleren op bestand</button>
          <input ref={fileRef} type="file" hidden accept=".xlsx,.csv"
            onChange={(e) => { controleer(e.target.files?.[0] ?? null); e.target.value = ""; }} />
        </div>
      </div>
      {msg && <p className="sub" style={{ color: "var(--main)" }}>{msg}</p>}

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 18 }}>
        <div className="card">
          <div className="eyebrow" style={{ marginBottom: 10 }}>Hoe het bestand herkend wordt</div>
          <p className="sub">Op de <b>structuur</b> van het bestand, niet op naam of
            tabvolgorde: {builtin === "kruidvat_dwh"
              ? "het werkblad met het metadatablok (Country/Formula/Brand) én een 'SKU No.'-kop; van meerdere bladen wint het blad waarvan het regelaantal klopt met zijn eigen Total-rij."
              : builtin === "ici_maandrapport"
                ? "de tabbladen met een Store/Address-kop gevolgd door maandkolommen, plus het merk-tabblad voor de controle op de totalen."
                : builtin === "etos_datagrid"
                  ? "de UPC-kopregel met daarboven weekkoppen met Ending-datums. Gecontroleerd op merkental, weekbereik en ISO-einddatums uit het metadatablok — dit formaat heeft geen totalenrij, dus dat is de maximale controle."
                  : "de kolomkoppen en het bestandstype die in dit profiel vastliggen."}</p>
          <p className="sub">Hernoemt de retailer een bestand of tabblad, dan blijft de
            herkenning gewoon werken.</p>
        </div>
        <div className="card">
          <div className="eyebrow" style={{ marginBottom: 10 }}>Wat de parser levert</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="chip static">{caps?.periode === "maand" ? "per maand" : "per week"}</span>
            {levert.map(([label, on]) => (
              <span key={label} className={`chip static ${on ? "" : "off"}`}>{label}</span>
            ))}
          </div>
          <p className="sub" style={{ marginTop: 12 }}>Grijze labels levert deze retailer
            niet; de analyses passen zich daarop aan.</p>
        </div>
      </div>

      {testResult && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="eyebrow">Controleresultaat</div>
          {testResult.ok ? (
            <p className="sub">✓ {testResult.rijen} regels leesbaar · periodes {testResult.periodes.join(", ")}</p>
          ) : (
            <p className="sub sig-red">{testResult.fout}</p>
          )}
        </div>
      )}

      <p className="sub" style={{ marginTop: 22 }}>
        Klopt er iets niet aan wat de parser leest, of levert de retailer voortaan
        een ander formaat? Deel het nieuwe bestand — de parser wordt in het
        project aangepast en komt mee met een update.
      </p>
    </>
  );
}
