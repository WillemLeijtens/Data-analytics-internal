import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Assortiment from "../screens/Assortiment";

// De vraag die dit scherm moest beantwoorden: "1142 winkels komt niet terug
// in de instellingen". Dat kan kloppen — dan is het merkaantal gebruikt en
// niet een aantal per artikel. Per regel hoort te staan welk van de twee het
// is, en waar de rotatie op rust: de weken van deze maand die geleverd zijn.

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn() };
});
import { apiGet } from "../api";

const ctx: any = { retailer: "kruidvat", card: { naam: "Kruidvat" }, cards: [], go: vi.fn() };

const artikel = (extra: any = {}) => ({
  ean: "31210001", naam: "Slant Tweezer", merk: "TWEEZERMAN",
  rotatie: 0.34, target: 1.7, score: 20, advies: "Mogelijke delist",
  actieve_periodes: 34, winkels: 1205, winkels_bron: "merk",
  maand_volume: 820, maand_weken: 2, dekking: null, ...extra,
});

const antwoord = (artikelen: any[]) => ({
  available: true, labels: [], resolution: {}, periode_type: "week",
  dekking: [], maand: { label: "augustus 2026", periodes: ["2026-W32", "2026-W33"], weken: 2 },
  stats: { op_target: 0, onder_target: 0, delist: 1 },
  artikelen,
});

const toon = () => render(<MemoryRouter><Assortiment ctx={ctx} /></MemoryRouter>);

beforeEach(() => vi.mocked(apiGet).mockReset());

describe("Assortimentsanalyse", () => {
  it("noemt de maand waarover de rotatie rekent in de kolomkop", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord([artikel()]));
    toon();
    expect(await screen.findByText(/Rotatie \(huidige maand\)/)).toBeInTheDocument();
    expect(screen.getByText(/augustus 2026 · 2 weken/)).toBeInTheDocument();
  });

  it("zet onder de rotatie waar hij op rust, inclusief de herkomst van het winkelaantal", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord([artikel()]));
    toon();
    // Zonder "(merkaantal)" ga je in Instellingen op de verkeerde plek zoeken.
    expect(await screen.findByText(/820 st in 2 weken · 1205 winkels \(merkaantal\)/))
      .toBeInTheDocument();
  });

  it("meldt het als het winkelaantal per artikel is ingesteld", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord([
      artikel({ winkels: 120, winkels_bron: "artikel" })]));
    toon();
    expect(await screen.findByText(/120 winkels \(per artikel ingesteld\)/))
      .toBeInTheDocument();
  });

  it("legt allebei de scenario's uit achter het vraagteken", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord([artikel()]));
    toon();
    const knop = await screen.findByLabelText(/Uitleg:/);
    const tekst = knop.getAttribute("aria-label") ?? "";
    expect(tekst).toMatch(/per artikel ingesteld/);
    expect(tekst).toMatch(/merkaantal/);
    expect(tekst).toMatch(/augustus 2026, 2 weken geleverd/);
  });
});
