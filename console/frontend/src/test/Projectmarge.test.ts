import { describe, expect, it } from "vitest";
import { bereken } from "../screens/Projecten";

// Dit is de berekening die tijdens het typen meeloopt; de backend rekent
// hetzelfde bij het opslaan (engine/projecten.py, test_projecten.py). Twee
// implementaties van één som is een risico, dus deze test spiegelt bewust
// dezelfde getallen als de backendtest: 100 winkels x 6 stuks, €5 verkoop,
// €2 kostprijs, 4 weken looptijd, €500 listing fee en €300 marketing.

const PRODUCT = {
  naam: "Nagellak rood", kostprijs: 2, verkoopprijs: 5,
  aantal_winkels: 100, stuks_per_winkel: 6, rotatie_per_winkel_per_week: 0.5,
};
const PROJECT = { start_datum: "2026-09-01", eind_datum: "2026-09-28" };
const KOSTEN = [
  { soort: "listing_fee", bedrag: 500, terugkerend: 0 },
  { soort: "marketing", bedrag: 300, terugkerend: 1 },
];

describe("projectmarge", () => {
  it("rekent de brutomarge per product", () => {
    // (5 - 2) / 5 = 60%, hetzelfde voor de vulling als voor de doorverkoop.
    const b = bereken({}, [PRODUCT], []);
    expect(b.rijen[0].margePct).toBeCloseTo(60, 5);
  });

  it("zonder verkoopprijs is er geen percentage", () => {
    // Niet 0%: dat zou lezen als een product zonder marge.
    const b = bereken({}, [{ naam: "Leeg" }], []);
    expect(b.rijen[0].margePct).toBeNull();
    expect(b.rijen[0].onderDrempel).toEqual([]);
  });

  it("zonder drempel wordt er niets geoordeeld", () => {
    const b = bereken(PROJECT, [PRODUCT], KOSTEN);
    expect(b.eenmalig.voldoet).toBeNull();
    expect(b.terugkerend.voldoet).toBeNull();
  });

  it("toetst de nettomarge aan de drempel", () => {
    // 43,3% eenmalig haalt 40 wel; 30,0% terugkerend niet.
    const b = bereken(PROJECT, [PRODUCT], KOSTEN, { eenmalig: 40, terugkerend: 40 });
    expect(b.eenmalig.pct).toBeCloseTo(43.3, 1);
    expect(b.eenmalig.voldoet).toBe(true);
    expect(b.terugkerend.pct).toBeCloseTo(30.0, 1);
    expect(b.terugkerend.voldoet).toBe(false);
  });

  it("precies op de drempel telt als gehaald", () => {
    const b = bereken({}, [PRODUCT], [], { eenmalig: 60, terugkerend: null });
    expect(b.eenmalig.voldoet).toBe(true);
  });

  it("meldt een product dat de drempel op zijn brutomarge al niet haalt", () => {
    // Dan haalt het project hem zeker niet: de kosten komen er nog af.
    const b = bereken(PROJECT, [PRODUCT], KOSTEN, { eenmalig: 70, terugkerend: 50 });
    expect(b.rijen[0].onderDrempel).toEqual([{ soort: "eenmalige omzet", drempel: 70 }]);
  });

  it("velt geen oordeel over terugkerend zonder looptijd", () => {
    // Zonder looptijd is er geen terugkerend totaal om tegen te houden.
    const b = bereken({}, [PRODUCT], [], { eenmalig: null, terugkerend: 90 });
    expect(b.terugkerend.marge).toBeNull();
    expect(b.terugkerend.voldoet).toBeNull();
  });
});
