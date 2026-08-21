import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Datagat } from "../api";
import { DatagatMelding, DatagatenPaneel } from "../components/shared";

// Een meerjarig gat ("2024 wel, 2025 niet, 2026 weer wel") kan twee dingen
// betekenen: het merk lag er dat jaar niet, of een bestand is nooit
// ingelezen. Het scherm mag dat verschil niet zelf invullen — het vraagt het,
// en onthoudt het antwoord.

const gat: Datagat = {
  merk: "TWEEZERMAN", land: "NL", banner: "KV",
  van_jaar: 2025, tot_jaar: 2025, jaren_met_data: [2024, 2026],
  tekst: "geen data voor TWEEZERMAN in Nederland in 2025, terwijl er vóór én ná dat jaar wél data is",
  oordeel: null, toelichting: null, beoordeeld_door: null, beoordeeld_op: null,
};

function mockFetch(gaten: Datagat[]) {
  const fetchMock = vi.fn(async (_url: string, opts?: any) => ({
    ok: true,
    json: async () => (opts?.method === "PUT" ? { ok: true } : { beschikbaar: true, gaten }),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("Datagaten", () => {
  it("meldt het gat en laat het oordeel vastleggen inclusief scope", async () => {
    const fetchMock = mockFetch([gat]);
    render(<DatagatenPaneel retailer="kruidvat" />);
    await screen.findByText(gat.tekst);
    expect(screen.getByText(/wel data in 2024, 2026/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Toelichting"),
      { target: { value: "merk lag dat jaar niet bij Kruidvat" } });
    fireEvent.click(screen.getByRole("button", { name: "Klopt" }));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find((c) => (c[1] as any)?.method === "PUT");
      expect(put).toBeTruthy();
      expect(put![0]).toBe("/api/kruidvat/datagaten");
      // De volledige scope terugsturen, anders beoordeel je een ander gat.
      expect(JSON.parse((put![1] as any).body)).toEqual({
        merk: "TWEEZERMAN", land: "NL", banner: "KV", van_jaar: 2025, tot_jaar: 2025,
        oordeel: "klopt", toelichting: "merk lag dat jaar niet bij Kruidvat",
      });
    });
  });

  it("een beoordeeld gat toont het oordeel en is te wijzigen", async () => {
    mockFetch([{ ...gat, oordeel: "klopt_niet", toelichting: "bestand ontbreekt",
                 beoordeeld_door: "Willem" }]);
    render(<DatagatenPaneel retailer="kruidvat" />);
    expect(await screen.findByText("Klopt niet")).toBeInTheDocument();
    expect(screen.getByText(/bestand ontbreekt — Willem/)).toBeInTheDocument();
    // Dicht tot je 'm openklapt: een beoordeeld gat vraagt niets meer.
    expect(screen.queryByLabelText("Toelichting")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Wijzigen" }));
    expect(screen.getByLabelText("Toelichting")).toHaveValue("bestand ontbreekt");
  });

  it("geen gaten, geen paneel", async () => {
    mockFetch([]);
    const { container } = render(<DatagatenPaneel retailer="kruidvat" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("de melding op het dashboard verwijst door naar Import status", async () => {
    mockFetch([gat]);
    const go = vi.fn();
    render(<DatagatMelding retailer="kruidvat" go={go} />);
    expect(await screen.findByText("1 datagat zonder oordeel.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Beoordelen" }));
    expect(go).toHaveBeenCalledWith("kruidvat", "import-status");
  });

  it("een beoordeeld gat is geen melding meer", async () => {
    mockFetch([{ ...gat, oordeel: "klopt" }]);
    const { container } = render(<DatagatMelding retailer="kruidvat" go={vi.fn()} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
