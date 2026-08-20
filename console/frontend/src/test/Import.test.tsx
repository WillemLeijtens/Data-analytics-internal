import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import ImportScreen from "../screens/Import";

// Het importscherm is de plek waar een gebruiker echte bestanden aanbiedt en
// waar een fout het duurst is: een onbegrepen melding leidt tot een import
// die niet gebeurt, of erger, tot vertrouwen in cijfers die er niet zijn.
// Tot deze tests had het scherm geen enkele geautomatiseerde dekking.

const ctx = {
  retailer: "kruidvat",
  card: { id: "kruidvat", naam: "Kruidvat" } as any,
  cards: [],
  go: vi.fn(),
};

function mockFetch(handlers: Record<string, any>) {
  const fetchMock = vi.fn(async (url: string, opts?: any) => {
    const sleutel = `${opts?.method ?? "GET"} ${url}`;
    const h = handlers[sleutel];
    if (!h) return { ok: true, json: async () => [] };
    if (h.status && h.status >= 400) {
      return { ok: false, status: h.status, text: async () => h.body };
    }
    return { ok: true, json: async () => h.body };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const bestand = () =>
  new File(["x"], "Kruidvat_wk32.xlsx", { type: "application/vnd.ms-excel" });

describe("Importscherm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("toont de tweestapsflow: eerst controleren, pas daarna importeren", async () => {
    mockFetch({
      "GET /api/imports?retailer_id=kruidvat": { body: [] },
      "POST /api/import/controle": {
        body: { results: [{ filename: "Kruidvat_wk32.xlsx", herkend: true,
                            retailer_id: "kruidvat", retailer_naam: "Kruidvat",
                            profiel_versie: 3, detail: null }] },
      },
    });
    const { container } = render(<ImportScreen ctx={ctx} />);
    await waitFor(() => expect(screen.getByText(/Nog geen imports/)).toBeInTheDocument());
    const invoer = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(invoer, { target: { files: [bestand()] } });

    // Na de controle staat het bestand klaar, maar is er nog NIETS ingelezen.
    await waitFor(() => expect(screen.getByText(/Kruidvat_wk32\.xlsx/)).toBeInTheDocument());
    expect(screen.queryByText(/ingelezen/i)).not.toBeInTheDocument();
  });

  it("meldt een niet-herkend bestand met de reden erbij", async () => {
    mockFetch({
      "GET /api/imports?retailer_id=kruidvat": { body: [] },
      "POST /api/import/controle": {
        body: { results: [{ filename: "raar.xlsx", herkend: false, retailer_id: null,
                            retailer_naam: null, profiel_versie: null,
                            detail: "Geen parser herkent dit bestandsformaat." }] },
      },
    });
    const { container } = render(<ImportScreen ctx={ctx} />);
    await waitFor(() => expect(screen.getByText(/Nog geen imports/)).toBeInTheDocument());
    fireEvent.change(container.querySelector('input[type="file"]')!,
                     { target: { files: [bestand()] } });
    await waitFor(() =>
      expect(screen.getByText(/Geen parser herkent dit bestandsformaat/)).toBeInTheDocument());
  });

  it("toont een serverfout tijdens het controleren als leesbare melding", async () => {
    mockFetch({
      "GET /api/imports?retailer_id=kruidvat": { body: [] },
      "POST /api/import/controle": { status: 422, body: "bestand is groter dan 200 MB" },
    });
    const { container } = render(<ImportScreen ctx={ctx} />);
    await waitFor(() => expect(screen.getByText(/Nog geen imports/)).toBeInTheDocument());
    fireEvent.change(container.querySelector('input[type="file"]')!,
                     { target: { files: [bestand()] } });
    await waitFor(() =>
      expect(screen.getByText(/groter dan 200 MB/)).toBeInTheDocument());
  });

  it("toont een fout bij het ophalen van de importlijst i.p.v. een leeg scherm", async () => {
    mockFetch({
      "GET /api/imports?retailer_id=kruidvat": { status: 500, body: "database weg" },
    });
    render(<ImportScreen ctx={ctx} />);
    await waitFor(() => expect(screen.getByText(/database weg/)).toBeInTheDocument());
  });
});
