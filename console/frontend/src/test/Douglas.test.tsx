import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Artikelanalyse from "../screens/Artikelanalyse";
import Assortiment from "../screens/Assortiment";
import { LevelStrip } from "../components/shared";

// Douglas levert alleen netto-omzet, geen stuks, en de omzet per artikel en
// per winkel als twee aparte maandrapporten. Wat het scherm daarmee doet:
// geen Volume-stand, een nette melding in plaats van een assortimentsanalyse
// vol "geen verkoop", en uitleg bij het label als het winkelrapport achterloopt.

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn() };
});
import { apiGet } from "../api";

const ctx: any = { retailer: "douglas", card: { naam: "Douglas" }, cards: [], go: vi.fn() };

const artikel = {
  ean: "8015150261166", naam: "GOCCE MAGICHE MAGIC DROPS 30 ML", merk: "COLLISTAR",
  sparkline: { ytd: { 8: { omzet: 19459, volume: 0 } }, lytd: { 8: { omzet: 17543, volume: 0 } } },
  laatste_periode: { omzet: 19459, volume: 0 }, totaal_ytd: { omzet: 19459, volume: 0 },
  totaal_lytd: { omzet: 17543, volume: 0 }, on_counter: "2025-08", on_counter_begrensd: true,
  status: null, status_reden: null, dekking: [], ytd_delta_pct: 10.9,
  ytd_vergelijkbaar: { nu: 19459, vorig: 17543 }, distributie: null,
};

beforeEach(() => vi.mocked(apiGet).mockReset());

describe("Douglas zonder volume", () => {
  it("de artikelanalyse zet de Volume-stand uit", async () => {
    vi.mocked(apiGet).mockResolvedValue({
      available: true, labels: ["OP MAANDNIVEAU"], resolution: {}, periode_type: "maand",
      jaar: 2026, laatste_periode: "2026-08", filters: { merk: ["COLLISTAR"] }, dekking: [],
      distributie_beschikbaar: false, capabilities: { volume: false }, artikelen: [artikel],
    });
    render(<MemoryRouter><Artikelanalyse ctx={ctx} /></MemoryRouter>);
    const knop = await screen.findByRole("button", { name: "Volume" });
    expect(knop).toBeDisabled();
    expect(knop.getAttribute("title")).toMatch(/geen volumedata/);
    // Omzet is de stand, ook al stond Volume eerst aan.
    expect(screen.getByRole("button", { name: "Omzet" }).className).toContain("on");
  });

  it("de assortimentsanalyse legt uit waarom er geen rotatie is", async () => {
    vi.mocked(apiGet).mockResolvedValue({ available: false, reason: "GEEN VOLUMEDATA", labels: [] });
    render(<MemoryRouter><Assortiment ctx={ctx} /></MemoryRouter>);
    expect(await screen.findByText(/Geen volumedata voor deze retailer/)).toBeInTheDocument();
    expect(screen.getByText(/stuks per winkel per week/)).toBeInTheDocument();
  });
});

describe("achterlopend winkelrapport", () => {
  it("het label krijgt uitleg, met de maand erin", () => {
    render(<MemoryRouter>
      <LevelStrip labels={["OP MAANDNIVEAU", "WINKELBESTAND T/M 2026-08"]} retailer="douglas" />
    </MemoryRouter>);
    expect(screen.getByText("WINKELBESTAND T/M 2026-08")).toBeInTheDocument();
    const uitleg = screen.getAllByLabelText(/Uitleg:/).map((b) => b.getAttribute("aria-label") ?? "");
    expect(uitleg.some((t) => /winkelrapport loopt achter/.test(t))).toBe(true);
  });
});
