import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TijdlijnBlok } from "../screens/Dashboard";

// De Categorie-stand combineert zelfgekozen categorieën tot ÉÉN lijn via een
// EIGEN fetch — nooit door twee losse categoriereeksen client-side op te
// tellen (een winkel die beide categorieën verkocht zou dan dubbel tellen).

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn() };
});
import { apiGet } from "../api";

const reeks = (merk: string) => ({
  merk, omzet: [10, 20], winkels: [1, 2], per_winkel: [10, 10], bron: ["feiten", "feiten"],
});

const t = {
  periodes: ["2026-W01", "2026-W02"],
  venster: 1,
  per_merk: [reeks("TWEEZERMAN")],
  totaal: reeks("TOTAAL"),
  decompositie: {},
  vergelijking: {},
};

beforeEach(() => { vi.mocked(apiGet).mockReset(); });

describe("TijdlijnBlok — categorie-stand", () => {
  it("toont de Categorie-knop alleen als de retailer categorieën heeft", () => {
    render(<TijdlijnBlok t={t} pWord="Week" retailer="etos" merk={[]} land={[]} banner={[]}
      categorieOpties={[]} />);
    expect(screen.queryByRole("button", { name: "Categorie" })).not.toBeInTheDocument();
  });

  it("fetcht niets zolang er geen categorie gekozen is", () => {
    render(<TijdlijnBlok t={t} pWord="Week" retailer="etos" merk={[]} land={[]} banner={[]}
      categorieOpties={["SHAMPOO", "CONDITIONERS", "HAARSTYLING"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Categorie" }));
    expect(screen.getByText(/Kies één of meer categorieën/)).toBeInTheDocument();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("combineert de gekozen categorieën in één fetch, met het merkfilter mee", async () => {
    vi.mocked(apiGet).mockResolvedValue({
      tijdlijn: { periodes: ["2026-W01", "2026-W02"], totaal: reeks("SHAMPOO + CONDITIONERS") },
    });
    render(<TijdlijnBlok t={t} pWord="Week" retailer="etos" merk={["BJÖRN AXÉN"]} land={[]} banner={[]}
      categorieOpties={["SHAMPOO", "CONDITIONERS", "HAARSTYLING"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Categorie" }));
    fireEvent.click(screen.getByRole("button", { name: "SHAMPOO" }));
    fireEvent.click(screen.getByRole("button", { name: "CONDITIONERS" }));

    // Elke chip-klik is een losse statuswijziging (en dus een losse fetch);
    // de LAATSTE fetch hoort beide gekozen categorieën samen te bevatten.
    const laatsteAanroep = () => {
      const calls = vi.mocked(apiGet).mock.calls;
      return calls[calls.length - 1]?.[0] as string;
    };
    await waitFor(() => {
      expect(laatsteAanroep()).toContain("categorie=SHAMPOO%2CCONDITIONERS");
    });
    const pad = laatsteAanroep();
    expect(pad).toContain("/etos/dashboard?");
    expect(pad).toContain("merk=BJ%C3%96RN+AX%C3%89N");
  });
});
