import { useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { RetailerCard, apiGet } from "./api";
import logo from "./ds/logo-white.svg";
import Overzicht from "./screens/Overzicht";
import Dashboard from "./screens/Dashboard";
import Artikelanalyse from "./screens/Artikelanalyse";
import Promoties from "./screens/Promoties";
import Assortiment from "./screens/Assortiment";
import ImportScreen from "./screens/Import";
import ImportStatus from "./screens/ImportStatus";
import Parser from "./screens/Parser";
import Instellingen from "./screens/Instellingen";
import Projecten from "./screens/Projecten";
import Changelog from "./screens/Changelog";
import Conclusie from "./screens/Conclusie";

const SIG_DOT: Record<string, string> = {
  green: "dot-green", orange: "dot-orange", red: "dot-red", grey: "dot-grey",
};

// Screens that exist for the 'alle retailers' tab (README: Overzicht, Import,
// Import status); everything else needs a concrete retailer.
const ALL_SCREENS = new Set(["overzicht", "projecten", "import", "import-status", "changelog"]);

export type ShellCtx = {
  retailer: string;                 // 'alle' | retailer id
  card: RetailerCard | null;        // card of the active retailer
  cards: RetailerCard[];
  go: (retailer: string, screen?: string) => void;
};

function Chevron() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10">
      <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function Sidebar({ ctx, screen }: { ctx: ShellCtx; screen: string }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ ANALYSES: true, OPERATIE: true });
  const caps = ctx.card?.capabilities ?? null;
  const noProfile = ctx.retailer !== "alle" && !ctx.card?.profiel;
  const noArticle = noProfile || (caps ? !caps.artikel : false);
  const artTitle = noProfile ? "Gegevens niet beschikbaar: nog geen parser-profiel"
    : "Gegevens niet beschikbaar: deze retailer levert geen artikelniveau";

  const item = (id: string, label: string, opts?: { sub?: boolean; disabled?: boolean; title?: string }) => (
    <button
      key={id}
      className={`nav-item ${opts?.sub ? "nav-sub" : ""} ${screen === id ? "active" : ""} ${opts?.disabled ? "disabled" : ""}`}
      title={opts?.disabled ? opts?.title : undefined}
      onClick={() => !opts?.disabled && ctx.go(ctx.retailer, id)}
    >
      {label}
    </button>
  );
  const group = (name: string, children: React.ReactNode) => (
    <div key={name}>
      <button className={`nav-group ${open[name] ? "" : "closed"}`}
        onClick={() => setOpen((o) => ({ ...o, [name]: !o[name] }))}>
        <Chevron /> {name}
      </button>
      {open[name] && children}
    </div>
  );

  return (
    <nav className="sidebar">
      <div className="logo"><img src={logo} alt="By Leijtens" /></div>
      {item("overzicht", "Overzicht")}
      {item("projecten", "Projectcalculator")}
      {group("ANALYSES", <>
        {/* Conclusie bovenaan: dat is de samenvatting van de vier analyses
            eronder, dus je begint daar en duikt daarna pas de details in. */}
        {item("conclusie", "Conclusie", { sub: true, disabled: ctx.retailer === "alle" })}
        {item("dashboard", "Dashboard", { sub: true, disabled: ctx.retailer === "alle" })}
        {item("artikelen", "Artikelanalyse", { sub: true, disabled: ctx.retailer === "alle" || noArticle, title: artTitle })}
        {item("promoties", "Promoties", { sub: true, disabled: ctx.retailer === "alle" })}
        {item("assortiment", "Assortimentsanalyse", { sub: true, disabled: ctx.retailer === "alle" || noArticle, title: artTitle })}
      </>)}
      {group("OPERATIE", <>
        {item("import", "Import", { sub: true })}
        {item("import-status", "Import status", { sub: true })}
        {item("parser", "Parser", { sub: true, disabled: ctx.retailer === "alle" })}
      </>)}
      {item("instellingen", "Instellingen", { disabled: ctx.retailer === "alle" })}
      <div className="sidebar-bottom">
        {item("changelog", "Changelog")}
        <div className="foot">Willem Leijtens</div>
      </div>
    </nav>
  );
}

function RetailerPicker({ ctx, screen }: { ctx: ShellCtx; screen: string }) {
  return (
    <div className="card empty-card">
      <div className="eyebrow">Kies een retailer</div>
      <h2 style={{ marginTop: 10 }}>Dit scherm is per retailer</h2>
      <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 18, flexWrap: "wrap" }}>
        {ctx.cards.map((c) => (
          <button key={c.id} className="btn ghost" onClick={() => ctx.go(c.id, screen)}>{c.naam}</button>
        ))}
      </div>
    </div>
  );
}

function Shell() {
  const { retailer = "alle", screen = "overzicht" } = useParams();
  const nav = useNavigate();
  const [cards, setCards] = useState<RetailerCard[]>([]);
  const [apiDown, setApiDown] = useState(false);
  const refresh = () => apiGet<{ retailers: RetailerCard[] }>("/overview")
    .then((o) => { setCards(o.retailers); setApiDown(false); })
    .catch(() => setApiDown(true));
  useEffect(() => { refresh(); }, [retailer, screen]);

  const ctx: ShellCtx = useMemo(() => ({
    retailer,
    cards,
    card: cards.find((c) => c.id === retailer) ?? null,
    go: (r, s) => {
      // Tab click keeps the screen; from Overzicht jump to Dashboard;
      // 'alle retailers' goes to Overzicht.
      let target = s ?? screen;
      if (s === undefined) {
        if (r === "alle") target = ALL_SCREENS.has(screen) ? screen : "overzicht";
        else if (screen === "overzicht") target = "dashboard";
      }
      nav(`/${r}/${target}`);
    },
  }), [retailer, screen, cards]);

  const body = () => {
    if (retailer === "alle" && !ALL_SCREENS.has(screen)) return <RetailerPicker ctx={ctx} screen={screen} />;
    switch (screen) {
      case "overzicht": return <Overzicht ctx={ctx} />;
      case "projecten": return <Projecten ctx={ctx} />;
      case "dashboard": return <Dashboard ctx={ctx} />;
      case "artikelen": return <Artikelanalyse ctx={ctx} />;
      case "promoties": return <Promoties ctx={ctx} />;
      case "assortiment": return <Assortiment ctx={ctx} />;
      case "import": return <ImportScreen ctx={ctx} />;
      case "import-status": return <ImportStatus ctx={ctx} />;
      case "parser": return <Parser ctx={ctx} />;
      case "instellingen": return <Instellingen ctx={ctx} />;
      case "conclusie": return <Conclusie ctx={ctx} />;
      case "changelog": return <Changelog />;
      default: return <Navigate to={`/${retailer}/overzicht`} replace />;
    }
  };

  return (
    <div className="layout">
      <Sidebar ctx={ctx} screen={screen} />
      <div className="main-col">
        <div className="tabs">
          <button className={`tab ${retailer === "alle" ? "active" : ""}`} onClick={() => ctx.go("alle")}>
            Alle retailers
          </button>
          {cards.map((c) => (
            <button key={c.id} className={`tab ${retailer === c.id ? "active" : ""}`} onClick={() => ctx.go(c.id)}>
              <span className={`dot ${SIG_DOT[c.signalen.composiet]}`} />
              {c.naam}
              <span className="meta">
                {c.profiel ? `${c.capabilities?.periode === "maand" ? "MAAND" : "WEEK"} · V${c.profiel.versie}` : "NIEUW"}
              </span>
            </button>
          ))}
        </div>
        <main className="content">
          {apiDown && (
            <div className="level-strip" style={{ borderLeft: "3px solid var(--neg)" }}>
              <span className="sub">De server is op dit moment niet bereikbaar — gegevens kunnen verouderd zijn.</span>
              <a style={{ cursor: "pointer", marginLeft: "auto" }} onClick={refresh}>Opnieuw proberen</a>
            </div>
          )}
          {body()}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/:retailer/:screen" element={<Shell />} />
      <Route path="/:retailer" element={<Shell />} />
      <Route path="*" element={<Navigate to="/alle/overzicht" replace />} />
    </Routes>
  );
}
