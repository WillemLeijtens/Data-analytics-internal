import { useEffect, useState } from "react";
import { apiGet } from "../api";
import { ShellCtx } from "../App";

export default function ImportStatus({ ctx }: { ctx: ShellCtx }) {
  const [data, setData] = useState<any[]>([]);
  useEffect(() => {
    apiGet(`/import-status${ctx.retailer !== "alle" ? `?retailer_id=${ctx.retailer}` : ""}`).then(setData);
  }, [ctx.retailer]);

  return (
    <>
      <h1>Import status{ctx.card ? ` — ${ctx.card.naam}` : ""}</h1>
      {data.map((r) => (
        <div key={r.retailer} className="card" style={{ marginTop: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className={`brand-dot dot-${r.signaal}`} style={{ width: 9, height: 9 }} />
            <h3 style={{ fontSize: 17, margin: 0 }}>{r.naam}</h3>
            <span className="sub" style={{ letterSpacing: "0.12em" }}>
              {r.periode_type?.toUpperCase() ?? "—"} / {r.profiel ? `PROFIEL V${r.profiel.versie}` : "GEEN PROFIEL"}
            </span>
            <span className="sub" style={{ marginLeft: "auto" }}>
              {r.feeds.length ? `${r.feeds.length} feed(s) actueel` : "nog geen feeds"}
            </span>
          </div>
          {r.feeds.map((f: any) => (
            <div key={f.feed + f.scope} style={{ display: "grid", gridTemplateColumns: "10px 1fr 1fr 160px 80px", gap: 12, alignItems: "center", padding: "8px 0", borderTop: "1px solid var(--quiet)", marginTop: 8 }}>
              <span className="brand-dot dot-green" style={{ margin: 0 }} />
              <span>{f.feed}</span>
              <span className="sub">{f.scope}</span>
              <span className="mono" style={{ whiteSpace: "nowrap" }}>{f.periode} · {f.ts?.slice(0, 16)}</span>
              <span style={{ textAlign: "right" }}>{f.rijen} rijen</span>
            </div>
          ))}
        </div>
      ))}
    </>
  );
}
