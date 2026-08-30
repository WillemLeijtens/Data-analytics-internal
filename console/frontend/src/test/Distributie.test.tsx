import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Artikelanalyse from "../screens/Artikelanalyse";

// Distributie = het aantal winkels dat een artikel die week daadwerkelijk
// verkocht. Dat is een TELLING uit de feiten, dus de kolommen horen alleen te
// verschijnen bij retailers die winkelniveau leveren — bij de rest zou een
// leeg of geschat getal een meting suggereren die er niet is.

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn() };
});
import { apiGet } from "../api";

const ctx: any = { retailer: "etos", card: { naam: "Etos" }, cards: [], go: vi.fn() };

const artikel = (distributie: any) => ({
  ean: "120781690", naam: "TWEEZERMAN LASH CURLER", merk: "TWEEZERMAN",
  sparkline: { ytd: { 1: { omzet: 10, volume: 1 } }, lytd: {} },
  laatste_periode: { omzet: 10, volume: 1 },
  totaal_ytd: { omzet: 100, volume: 10 }, totaal_lytd: { omzet: 80, volume: 8 },
  on_counter: "2026-W01", on_counter_begrensd: false,
  status: null, status_reden: null, dekking: [],
  ytd_delta_pct: 25, ytd_vergelijkbaar: { nu: 100, vorig: 80 },
  distributie,
});

const DIST = {
  reeks: { ytd: { 1: 146, 2: 152 }, lytd: { 1: 111, 2: 118 } },
  laatste: 146,
  ytd: { nu: 152, vorig: 111.8, delta_pct: 36, periodes: 33 },
  twee_maanden: { nu: 139.5, vorig: 163.2, delta_pct: -14.5,
                  label: "juli-augustus 2026", vorig_label: "mei-juni 2026",
                  periodes: 8, vorige_periodes: 9 },
};

const antwoord = (extra: any) => ({
  available: true, labels: [], resolution: {}, periode_type: "week", jaar: 2026,
  laatste_periode: "2026-W34", filters: { merk: ["TWEEZERMAN"] }, dekking: [],
  ...extra,
});

const toon = () => render(<MemoryRouter><Artikelanalyse ctx={ctx} /></MemoryRouter>);

beforeEach(() => vi.mocked(apiGet).mockReset());

describe("Distributiekolommen", () => {
  it("verschijnen bij een retailer die winkelniveau levert", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      distributie_beschikbaar: true, artikelen: [artikel(DIST)] }));
    toon();
    expect(await screen.findByText(/Distributie$/)).toBeInTheDocument();
    expect(screen.getAllByText(/YTD vs LYTD/).length).toBe(2);   // omzet en distributie
    expect(screen.getByText(/2 mnd/)).toBeInTheDocument();
    expect(screen.getByText("146 winkels")).toBeInTheDocument();
    expect(screen.getByText("+36%")).toBeInTheDocument();
    expect(screen.getByText("-14,5%")).toBeInTheDocument();
  });

  it("blijven weg bij een retailer zonder winkel-ID in de feed", async () => {
    // Niet leeg maar wég: een lege kolom leest als "distributie nul".
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      distributie_beschikbaar: false, artikelen: [artikel(null)] }));
    toon();
    await screen.findByText("TWEEZERMAN LASH CURLER");
    expect(screen.queryByText(/2 mnd/)).not.toBeInTheDocument();
  });

  it("zet de twee winkelaantallen in de hover, zodat het percentage na te rekenen is", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      distributie_beschikbaar: true, artikelen: [artikel(DIST)] }));
    toon();
    const cel = (await screen.findByText("-14,5%")).closest("td")!;
    expect(cel.getAttribute("title")).toBe(
      "139,5 winkels in juli-augustus 2026 tegen 163,2 in mei-juni 2026");
  });

  it("meldt het als er geen vorig jaar is om mee te vergelijken", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      distributie_beschikbaar: true,
      artikelen: [artikel({ ...DIST, ytd: { nu: 152, vorig: null, delta_pct: null, periodes: 0 } })] }));
    toon();
    await screen.findByText("146 winkels");
    const cellen = screen.getAllByTitle("Geen vergelijkbare periodes met vorig jaar.");
    expect(cellen.length).toBeGreaterThan(0);
  });
});
