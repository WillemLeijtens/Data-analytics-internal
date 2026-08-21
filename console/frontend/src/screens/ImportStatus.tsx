import { ShellCtx } from "../App";
import { DatagatenPaneel, LoadState, useApi } from "../components/shared";

export default function ImportStatus({ ctx }: { ctx: ShellCtx }) {
  const { data, error, reload } = useApi<any[]>(
    `/import-status${ctx.retailer !== "alle" ? `?retailer_id=${ctx.retailer}` : ""}`);

  if (!data) return <LoadState error={error} reload={reload} />;
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
              {r.feeds.length ? `${r.feeds.length} feed(s)` : "nog geen feeds"}
            </span>
          </div>
          {r.feeds.map((f: any) => (
            <div key={f.feed + f.scope} style={{ display: "grid", gridTemplateColumns: "10px 1fr 1fr 160px 80px", gap: 12, alignItems: "center", padding: "8px 0", borderTop: "1px solid var(--t-card2)", marginTop: 8 }}>
              {/* Eigen kleur per feed: één merk dat weken achterloopt hoort
                  hier op te vallen, ook als de rest actueel is. */}
              <span className={`brand-dot dot-${f.signaal ?? r.signaal}`} style={{ margin: 0 }}
                title={f.achter > 1 ? `${f.achter} periode(s) achter` : "actueel"} />
              <span>{f.feed}</span>
              <span className="sub">{f.scope}{f.achter > 1 ? ` · ${f.achter} achter` : ""}</span>
              <span className="mono" style={{ whiteSpace: "nowrap" }}>
                {/* De database slaat UTC op; toon Nederlandse tijd. */}
                {f.periode} · {f.ts
                  ? new Date(f.ts.replace(" ", "T") + "Z").toLocaleString("nl-NL",
                      { day: "2-digit", month: "2-digit", year: "numeric",
                        hour: "2-digit", minute: "2-digit" })
                  : "—"}
              </span>
              <span style={{ textAlign: "right" }}>{f.rijen} rijen</span>
            </div>
          ))}
          {/* Meerjarige gaten horen bij de aanleverstatus: het gaat over wat
              er níet binnenkwam. */}
          <DatagatenPaneel retailer={r.retailer} />
        </div>
      ))}
    </>
  );
}
