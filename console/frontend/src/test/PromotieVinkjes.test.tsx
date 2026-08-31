import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import Promoties from "../screens/Promoties";

// Gemeld vanaf het scherm: "als ik een vinkje aan of uit zet, gaan andere
// vinkjes die ik niet heb aangeklikt ineens aan". Deze test bootst na wat er
// dan gebeurt: elke klik doet een PUT en daarna een volledige herlaad, en die
// herlaad overschrijft de vinkjes met een serverstand die de kliks erna nog
// niet kent.

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn(), apiSend: vi.fn() };
});
import { apiGet, apiSend } from "../api";

const ctx: any = { retailer: "etos", card: { naam: "Etos" }, cards: [], go: vi.fn() };

const sug = (periode: string, bevestigd = false) => ({
  sleutel: JSON.stringify(["TWEEZERMAN", "NL", null, periode]),
  merk: "TWEEZERMAN", land: "NL", banner: null, periode, bevestigd,
  suggestie: "prijs -20%", bereik: null, artikelen: [], artikelen_verkocht: 0,
  zekerheid: 4, zekerheid_delen: [], drop_pct: 20, z: 2,
});

/** De server: houdt echt bij wat er bevestigd is, net als de database. */
function nepServer(periodes: string[]) {
  const bevestigd = new Set<string>();
  const zet = (body: any) => {
    // Precies wat de backend doet: per regel aan of uit, en bij de
    // volledige-vervangingsvorm de hele lijst opnieuw.
    if (body.wijzigingen) {
      for (const c of body.wijzigingen) {
        if (c.bevestigd) bevestigd.add(c.periode);
        else bevestigd.delete(c.periode);
      }
      return;
    }
    bevestigd.clear();
    for (const c of body.bevestigd ?? []) bevestigd.add(c.periode);
  };
  const antwoord = () => ({
    available: true, labels: [], periode_type: "week", drempel: 0.1,
    capabilities: { banner: false }, methode: "prijsindex",
    suggesties: periodes.map((p) => sug(p, bevestigd.has(p))),
    uplift: [], basis: [], basis_per_merk: [], onvolledige_periodes: [],
    resolution: {},
  });
  return { bevestigd, antwoord, zet };
}

beforeEach(() => {
  vi.mocked(apiGet).mockReset();
  vi.mocked(apiSend).mockReset();
});

/** Beloftes die de test zelf op het juiste moment lost — anders lopen de PUT
 *  en de herlaad in dezelfde microtask en raak je de race nooit. */
/** Genoeg microtasks laten lopen dat de volgende schakel van de keten écht
 *  bij zijn poort aankomt. Zonder dit staat er na een klik nog niets in de
 *  poort en test je niets. */
const tik = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

function poort() {
  const open: (() => void)[] = [];
  return {
    wacht: () => new Promise<void>((r) => open.push(r)),
    los: async () => { open.shift()?.(); await tik(); },
    aantal: () => open.length,
  };
}

/** Alles wat nog in de poorten hangt afwerken, tot de keten leeg is. */
async function leeg(getPoort: any, putPoort: any) {
  for (let i = 0; i < 20 && (getPoort.aantal() || putPoort.aantal()); i++) {
    await putPoort.los();
    await getPoort.los();
  }
}

describe("promotievinkjes", () => {
  /** Server + scherm, met een poort op de GET en op de PUT. */
  function opzet(start: string[] = []) {
    const server = nepServer(["2026-W10", "2026-W11", "2026-W12"]);
    for (const p of start) server.bevestigd.add(p);
    const getPoort = poort();
    const putPoort = poort();
    vi.mocked(apiGet).mockImplementation(async () => {
      await getPoort.wacht();
      return server.antwoord();
    });
    vi.mocked(apiSend).mockImplementation(async (_url: string, _m: string, body: any) => {
      await putPoort.wacht();
      server.zet(body);
      return { ok: true };
    });
    return { server, getPoort, putPoort };
  }

  it("een herlaad onderweg wist een vinkje niet dat nog niet opgeslagen is", async () => {
    // Dit is de kern van de melding. Elke klik doet een PUT en daarna een
    // volledige herlaad. Die herlaad zet de vinkjes terug naar de serverstand
    // van dát moment — waarin de klik erna nog niet verwerkt is. Het vinkje
    // klapte dus vanzelf om, en de volgende klik stuurde die achterhaalde
    // stand terug als waarheid.
    const { server, getPoort, putPoort } = opzet();
    render(<Promoties ctx={ctx} />);
    await getPoort.los();
    const vakjes = await screen.findAllByRole("checkbox");

    fireEvent.click(vakjes[0]);        // W10 aan — save hangt in de poort
    await tik();
    fireEvent.click(vakjes[1]);        // W11 aan — nog niet opgeslagen
    await tik();
    await putPoort.los();              // de save van W10 landt
    await getPoort.los();              // en de herlaad erna, die W11 nog niet kent

    // Dit is de regressie: het vinkje van W11 stond nog in de wachtrij en
    // mag door die herlaad niet omklappen.
    let nu = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect([nu[0].checked, nu[1].checked]).toEqual([true, true]);

    await leeg(getPoort, putPoort);
    expect([...server.bevestigd].sort()).toEqual(["2026-W10", "2026-W11"]);
    nu = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect([nu[0].checked, nu[1].checked, nu[2].checked]).toEqual([true, true, false]);
  });

  it("een uitgezet vinkje komt niet terug door een herlaad onderweg", async () => {
    const { server, getPoort, putPoort } = opzet(["2026-W10", "2026-W11"]);
    render(<Promoties ctx={ctx} />);
    await getPoort.los();
    const vakjes = await screen.findAllByRole("checkbox");

    fireEvent.click(vakjes[0]);        // W10 UIT
    await tik();
    fireEvent.click(vakjes[1]);        // W11 UIT — nog niet opgeslagen
    await tik();
    await putPoort.los();
    await getPoort.los();

    let nu = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect([nu[0].checked, nu[1].checked]).toEqual([false, false]);

    await leeg(getPoort, putPoort);
    expect([...server.bevestigd]).toEqual([]);
    nu = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect([nu[0].checked, nu[1].checked]).toEqual([false, false]);
  });

  it("een klik ná een herlaad gooit een nog niet opgeslagen vinkje niet weg", async () => {
    // Dit is de melding zelf, in volgorde:
    //   1. W10 aan, 2. W11 aan (nog in de wachtrij),
    //   3. de herlaad van W10 landt en zet W11 in het scherm weer uit,
    //   4. de gebruiker klikt W12 aan.
    // Met een klik die de HELE lijst terugstuurt, verdween W11 daarmee uit de
    // database — zonder dat de gebruiker hem had aangeraakt.
    const { server, getPoort, putPoort } = opzet();
    render(<Promoties ctx={ctx} />);
    await getPoort.los();
    const vakjes = await screen.findAllByRole("checkbox");

    fireEvent.click(vakjes[0]);
    await tik();
    fireEvent.click(vakjes[1]);
    await tik();
    await putPoort.los();
    await getPoort.los();
    fireEvent.click(screen.getAllByRole("checkbox")[2]);
    await tik();
    await leeg(getPoort, putPoort);

    expect([...server.bevestigd].sort())
      .toEqual(["2026-W10", "2026-W11", "2026-W12"]);
  });

  it("stuurt per klik één wijziging, niet de hele lijst", async () => {
    // De kern van de fix: ook een scherm dat achterloopt kan met één klik
    // geen andere regel meer omzetten.
    const { getPoort, putPoort } = opzet(["2026-W10"]);
    render(<Promoties ctx={ctx} />);
    await getPoort.los();
    fireEvent.click((await screen.findAllByRole("checkbox"))[2]);
    await tik();
    await leeg(getPoort, putPoort);

    expect(apiSend).toHaveBeenCalledTimes(1);
    expect(vi.mocked(apiSend).mock.calls[0][2]).toEqual({
      wijzigingen: [{ merk: "TWEEZERMAN", land: "NL", banner: null,
                      periode: "2026-W12", bevestigd: true }],
    });
  });
});
