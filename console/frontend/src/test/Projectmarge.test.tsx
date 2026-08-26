import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MargeBedrag, bereken } from "../screens/Projecten";

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
  it("de opbouw van de marge klopt: productmarge − kosten, niet omzet − kosten", () => {
    // Het scherm toonde bij de terugkerende tegel "omzet − kosten", maar dat
    // is de marge niet: die is productmarge − kosten (+ bijdrage). Met deze
    // cijfers scheelt dat een factor: omzet 600 − 300 = 300, terwijl de
    // marge 360 − 300 = 60 is.
    const b = bereken(PROJECT, [PRODUCT], KOSTEN);
    expect(b.terugkerend.productmarge).toBeCloseTo(b.terugkerend.weekMarge * b.weken!, 5);
    expect(b.terugkerend.marge).toBeCloseTo(
      b.terugkerend.productmarge! - b.terugkerend.kosten + b.terugkerend.bijdrage, 5);
    expect(b.terugkerend.productmarge).not.toBeCloseTo(b.terugkerend.omzet!, 5);
  });

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
    expect(b.rijen[0].onderDrempel).toEqual([{ soort: "eenmalige marge", drempel: 70 }]);
  });

  it("velt geen oordeel over terugkerend zonder looptijd", () => {
    // Zonder looptijd is er geen terugkerend totaal om tegen te houden.
    const b = bereken({}, [PRODUCT], [], { eenmalig: null, terugkerend: 90 });
    expect(b.terugkerend.marge).toBeNull();
    expect(b.terugkerend.voldoet).toBeNull();
  });
});

// De driehoek hoort bij de kolom waarvan de drempel niet gehaald wordt: de
// eenmalige vulling en de wekelijkse doorverkoop hebben elk hun eigen norm,
// terwijl het percentage (brutomarge per stuk) in beide kolommen gelijk is.
// Een one-shot is één levering: geen doorverkoop per week. De spiegel in het
// scherm moet dat net zo rekenen als de engine (test_projecten.py), anders
// verspringen de cijfers zodra je opslaat.
describe("one-shot", () => {
  const oneShot = { ...PROJECT, soort: "eenmalig" };

  it("rekent geen terugkerende omzet, ook niet met een rotatie ingevuld", () => {
    const b = bereken(oneShot, [PRODUCT], []);
    expect(b.rijen[0].week_omzet).toBe(0);
    expect(b.terugkerend.omzet).toBeNull();
    expect(b.terugkerend.marge).toBeNull();
    // De vulling rekent gewoon door.
    expect(b.eenmalig.omzet).toBe(3000);
    expect(b.totaal.omzet).toBe(3000);
  });

  it("bij een one-shot is het totaal exact de vulling", () => {
    // Daarom toont het scherm de totaaltegel niet bij een one-shot: twee
    // identieke tegels naast elkaar laten twijfelen of je een verschil mist.
    const b = bereken(oneShot, [PRODUCT], KOSTEN);
    expect(b.totaal.marge).toBeCloseTo(b.eenmalig.marge, 5);
    expect(b.totaal.omzet).toBeCloseTo(b.eenmalig.omzet, 5);
  });

  it("zet looptijdkosten op de eenmalige marge", () => {
    // Er is geen looptijdmarge om op te drukken; stil laten vallen zou het
    // project winstgevender laten lijken dan het is.
    const b = bereken(oneShot, [PRODUCT], KOSTEN);
    expect(b.eenmalig.kosten).toBe(800);
    expect(b.eenmalig.marge).toBeCloseTo(1000, 5);
    expect(b.kostenBuitenBeeld).toBe(0);
  });

  it("houdt een one-shot niet aan de terugkerende drempel", () => {
    const b = bereken(oneShot, [PRODUCT], [], { eenmalig: 50, terugkerend: 90 });
    expect(b.terugkerend.voldoet).toBeNull();
    expect(b.rijen[0].onderDrempel).toEqual([]);
  });

  it("doorlopend blijft het oude gedrag", () => {
    expect(bereken(PROJECT, [PRODUCT], KOSTEN))
      .toEqual(bereken({ ...PROJECT, soort: "doorlopend" }, [PRODUCT], KOSTEN));
  });
});

describe("MargeBedrag", () => {
  const rij = (onder: { soort: string; drempel: number }[]) =>
    ({ margePct: 60, onderDrempel: onder });

  it("zet het percentage achter het bedrag", () => {
    render(<MargeBedrag r={rij([])} bedrag={1800} soort="eenmalige marge" />);
    expect(screen.getByText(/60%/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("waarschuwt alleen in de kolom waarvan de drempel niet gehaald wordt", () => {
    const r = rij([{ soort: "terugkerende marge", drempel: 70 }]);
    const { unmount } = render(<MargeBedrag r={r} bedrag={150} soort="eenmalige marge" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    unmount();

    render(<MargeBedrag r={r} bedrag={150} soort="terugkerende marge" />);
    expect(screen.getByRole("img").getAttribute("title")).toMatch(
      /Brutomarge 60% ligt onder de drempel van 70% voor de terugkerende marge/);
  });

  it("zonder percentage staat er alleen een bedrag", () => {
    render(<MargeBedrag r={{ margePct: null, onderDrempel: [] }} bedrag={0}
      soort="eenmalige marge" />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
