import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Promoties from "../screens/Promoties";

// Een vinkje is een beslissing; die hoort niet verloren te gaan omdat iemand
// de Opslaan-knop vergat. De vinkjes slaan zichzelf op en de knop is weg.

const ctx = {
  retailer: "kruidvat",
  card: { id: "kruidvat", naam: "Kruidvat" } as any,
  cards: [],
  go: vi.fn(),
} as any;

const SUGGESTIE = {
  sleutel: JSON.stringify(["TWEEZERMAN", "NL", "KV", "2026-W05"]),
  merk: "TWEEZERMAN", land: "NL", banner: "KV", periode: "2026-W05",
  suggestie: "afgeprijsd, -20,0%", bevestigd: false,
  drop_pct: 20, z: 6.1, volume_respons_pct: 80, bereik: "assortiment",
  artikelen: [], artikelen_verkocht: 1, kwaliteit: "volledig",
  zekerheid: 5, zekerheid_delen: [], referentieperiodes: 10,
};

function mockData() {
  return {
    available: true, methode: "prijsindex", drempel: 0.05, periode_type: "week",
    labels: [], capabilities: { banner: true, volume: true },
    suggesties: [SUGGESTIE], uplift: [], basis: [], basis_per_merk: [],
    onvolledige_periodes: [],
  };
}

function mockFetch() {
  const puts: any[] = [];
  const fetchMock = vi.fn(async (url: string, opts?: any) => {
    if (opts?.method === "PUT") {
      puts.push(JSON.parse(opts.body));
      return { ok: true, json: async () => ({ ok: true }) };
    }
    return { ok: true, json: async () => mockData() };
  });
  vi.stubGlobal("fetch", fetchMock);
  return puts;
}

afterEach(() => vi.unstubAllGlobals());

describe("Promoties — automatisch opslaan", () => {
  it("de Opslaan-knop bestaat niet meer", async () => {
    mockFetch();
    render(<Promoties ctx={ctx} />);
    await screen.findByText(/TWEEZERMAN/);
    expect(screen.queryByRole("button", { name: "Opslaan" })).not.toBeInTheDocument();
    expect(screen.getByText(/direct opgeslagen/)).toBeInTheDocument();
  });

  it("een vinkje stuurt direct één wijziging met de volledige scope", async () => {
    // Per klik één regel, niet de hele lijst opnieuw: zo kan een klik geen
    // regel raken die de gebruiker niet heeft aangeraakt.
    const puts = mockFetch();
    render(<Promoties ctx={ctx} />);
    await screen.findByText(/TWEEZERMAN/);
    fireEvent.click(screen.getByRole("checkbox",
      { name: "Markeer TWEEZERMAN 2026-W05 als promotie" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ wijzigingen: [
      { merk: "TWEEZERMAN", land: "NL", banner: "KV", periode: "2026-W05",
        bevestigd: true }] });
  });

  it("uitvinken stuurt dezelfde regel met bevestigd=false", async () => {
    const puts = mockFetch();
    render(<Promoties ctx={ctx} />);
    await screen.findByText(/TWEEZERMAN/);
    const box = screen.getByRole("checkbox",
      { name: "Markeer TWEEZERMAN 2026-W05 als promotie" });
    fireEvent.click(box);
    fireEvent.click(box);
    // Twee PUTs, in volgorde: eerst aan, dan uit. De keten garandeert dat de
    // laatste klik ook de laatste serverstaat is.
    await waitFor(() => expect(puts).toHaveLength(2));
    expect(puts[0].wijzigingen[0].bevestigd).toBe(true);
    expect(puts[1].wijzigingen[0].bevestigd).toBe(false);
    expect(puts[1].wijzigingen[0].periode).toBe("2026-W05");
  });
});
