import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Conclusie from "../screens/Conclusie";

// Het scherm hoort bruikbaar te zijn zonder API-sleutel (dan alleen de
// bevindingen) en zichzelf bij te werken zodra de opgeslagen tekst niet meer
// bij de huidige cijfers hoort.

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn(), apiSend: vi.fn() };
});
import { apiGet, apiSend } from "../api";

const ctx: any = { retailer: "etos", card: { naam: "Etos" }, cards: [], go: vi.fn() };

const antwoord = (extra: any = {}) => ({
  beschikbaar: true,
  reden: null,
  context: { retailer: "Etos", periode_type: "week", laatste_periode: "2026-W33" },
  bevindingen: [
    { onderdeel: "winkels", ernst: "rood", kop: "101 winkels stilgevallen",
      tekst: "101 winkel/merk-combinaties verkopen niets meer.", cijfers: { aantal: 101 } },
  ],
  conclusie: null,
  verouderd: false,
  sleutel_ingesteld: false,
  ...extra,
});

const toon = () => render(<MemoryRouter><Conclusie ctx={ctx} /></MemoryRouter>);

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  vi.mocked(apiSend).mockReset();
});

describe("Conclusie", () => {
  it("toont de bevindingen en vraagt niets aan Claude zonder sleutel", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord());
    toon();
    expect(await screen.findByText("101 winkels stilgevallen")).toBeInTheDocument();
    expect(screen.getByText(/Geen Anthropic-sleutel ingesteld/)).toBeInTheDocument();
    expect(apiSend).not.toHaveBeenCalled();
  });

  it("laat een eerder geschreven conclusie staan als de sleutel weg is", async () => {
    // De tekst bestaat al en blijft geldig; alleen schrijven heeft een
    // sleutel nodig. Hem verbergen zou werk weggooien dat al betaald is.
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      sleutel_ingesteld: false,
      conclusie: { samenvatting: "Eerder geschreven.", advies: [], waarschuwingen: [],
                   gegenereerd_op: "2026-08-01T10:00:00" },
    }));
    toon();
    expect(await screen.findByText("Eerder geschreven.")).toBeInTheDocument();
    expect(apiSend).not.toHaveBeenCalled();
  });

  it("legt bij het vraagteken uit wanneer er een nieuwe tekst komt", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      sleutel_ingesteld: true, verouderd: false,
      conclusie: { samenvatting: "Actueel.", advies: [], waarschuwingen: [],
                   gegenereerd_op: "2026-08-25T10:00:00" },
    }));
    toon();
    await screen.findByText("Actueel.");
    // Geen knop meer: de tekst werkt zichzelf bij, dus valt er niets te drukken.
    expect(screen.queryByRole("button", { name: /schrijven/i })).not.toBeInTheDocument();
    const vraagteken = screen.getByRole("button", { name: /Uitleg: Deze tekst wordt automatisch/ });
    fireEvent.mouseEnter(vraagteken);
    expect(screen.getByText(/nieuwe data voor déze retailer is geïmporteerd/))
      .toBeInTheDocument();
  });

  it("schrijft vanzelf een conclusie als er nog geen is", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({ sleutel_ingesteld: true }));
    vi.mocked(apiSend).mockResolvedValue(antwoord({
      sleutel_ingesteld: true,
      conclusie: { samenvatting: "Etos verliest winkelbereik.", advies: [],
                   waarschuwingen: [], gegenereerd_op: "2026-08-25T10:00:00" },
    }));
    toon();
    await waitFor(() => expect(apiSend).toHaveBeenCalledWith("/etos/conclusie", "POST", {}));
    expect(await screen.findByText("Etos verliest winkelbereik.")).toBeInTheDocument();
  });

  it("werkt zichzelf bij zodra de opgeslagen tekst verouderd is", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      sleutel_ingesteld: true, verouderd: true,
      conclusie: { samenvatting: "Oude tekst.", advies: [], waarschuwingen: [],
                   gegenereerd_op: "2026-08-01T10:00:00" },
    }));
    vi.mocked(apiSend).mockResolvedValue(antwoord({
      sleutel_ingesteld: true,
      conclusie: { samenvatting: "Nieuwe tekst.", advies: [], waarschuwingen: [],
                   gegenereerd_op: "2026-08-25T10:00:00" },
    }));
    toon();
    await waitFor(() => expect(apiSend).toHaveBeenCalled());
    expect(await screen.findByText("Nieuwe tekst.")).toBeInTheDocument();
  });

  it("laat een actuele conclusie met rust — geen onnodige API-call", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      sleutel_ingesteld: true, verouderd: false,
      conclusie: { samenvatting: "Actueel.", advies: [], waarschuwingen: [],
                   gegenereerd_op: "2026-08-25T10:00:00" },
    }));
    toon();
    expect(await screen.findByText("Actueel.")).toBeInTheDocument();
    expect(apiSend).not.toHaveBeenCalled();
  });

  it("toont de waarschuwing bij een verzonnen getal", async () => {
    vi.mocked(apiGet).mockResolvedValue(antwoord({
      sleutel_ingesteld: true,
      conclusie: { samenvatting: "Tekst.", advies: [], gegenereerd_op: "2026-08-25T10:00:00",
                   waarschuwingen: ["Deze conclusie noemt getallen die niet in de bevindingen staan: € 999.111. Controleer die zelf."] },
    }));
    toon();
    expect(await screen.findByText(/noemt getallen die niet in de bevindingen staan/))
      .toBeInTheDocument();
  });
});
