import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TijdlijnBlok } from "../screens/Dashboard";

// Targets uit Instellingen zichtbaar maken: als streepjeslijn over de omzet
// per winkel, en opgeteld over de merken die de filters overlaten — één
// filiaal voert die merken immers naast elkaar. Een lat die maar de helft
// van het assortiment dekt hoort als zodanig gemeld te worden.

vi.mock("../api", async (importActual) => {
  const echt = await importActual<typeof import("../api")>();
  return { ...echt, apiGet: vi.fn() };
});

const reeks = (merk: string, extra: any = {}) => ({
  merk, omzet: [10, 20], winkels: [1, 2], per_winkel: [10, 30],
  bron: ["feiten", "feiten"], ...extra,
});

const t = (totaalExtra: any = {}, perMerk = [reeks("TWEEZERMAN")]) => ({
  periodes: ["2026-W01", "2026-W02"],
  venster: 1,
  per_merk: perMerk,
  totaal: reeks("TOTAAL", totaalExtra),
  decompositie: {},
  vergelijking: {},
});

const toon = (tt: any) => render(
  <TijdlijnBlok t={tt} pWord="Week" retailer="etos" merk={[]} land={[]} banner={[]}
    categorieOpties={[]} />);

beforeEach(() => vi.clearAllMocks());

describe("Target in de grafiek", () => {
  const metTarget = {
    target: 130,
    target_merken: [{ merk: "DEPEND", target: 45 }, { merk: "TWEEZERMAN", target: 85 }],
    target_zonder: [],
  };

  it("tekent de opgetelde lat op Totaal", () => {
    toon(t(metTarget));
    fireEvent.click(screen.getByRole("button", { name: "Totaal" }));
    expect(screen.getByText(/TARGET € 130/)).toBeInTheDocument();
  });

  it("laat de lat weg zolang er geen target is ingesteld", () => {
    toon(t());
    fireEvent.click(screen.getByRole("button", { name: "Totaal" }));
    expect(screen.queryByText(/TARGET/)).not.toBeInTheDocument();
  });

  it("meldt onder de grafiek welke merken buiten de lat vallen", () => {
    // Een som over de helft van het assortiment ziet eruit als een harde lat
    // en is het niet — dat mag niet alleen in de tooltip staan.
    toon(t({ ...metTarget, target: 85, target_zonder: ["DEPEND"] }));
    fireEvent.click(screen.getByRole("button", { name: "Totaal" }));
    expect(screen.getByText(/Niet in het opgetelde target voor DEPEND/)).toBeInTheDocument();
  });

  it("tekent bij meerdere merken naast elkaar geen latten", () => {
    // Acht streepjeslijnen leggen het paneel dicht en zijn niet meer aan een
    // lijn te koppelen; de Totaal-stand is daarvoor de plek.
    toon(t(metTarget, [reeks("TWEEZERMAN", { target: 85 }), reeks("DEPEND", { target: 45 })]));
    expect(screen.queryByText(/TARGET/)).not.toBeInTheDocument();
  });

  it("tekent de lat wél als er op één merk gefilterd is", () => {
    toon(t(metTarget, [reeks("TWEEZERMAN", { target: 85 })]));
    expect(screen.getByText(/TARGET € 85/)).toBeInTheDocument();
  });
});

import { KpiCard } from "../screens/Dashboard";

// De "Tel op"-stand op de kaart Omzet per winkel. Het grote getal is de omzet
// van álle merken door het hele winkelbestand; de optelsom van de merkregels
// is een ander getal zodra een merk in minder winkels ligt. Allebei kloppen —
// daarom staan ze naast elkaar en niet in plaats van elkaar.

const kaart = (optellen: any) => render(
  <KpiCard label="Omzet per winkel" tag="SCHATTING" value="€ 94" isEuro
    breakdown={[
      { label: "ALESSANDRO", waarde: 49, winkels: 464, target: 85 },
      { label: "DEPEND", waarde: 48, winkels: 495, target: 85 },
    ]}
    optellen={optellen} />);

describe("Tel op", () => {
  it("staat standaard aan en telt omzetten en targets bij elkaar op", () => {
    kaart({ target: 170, zonder: [] });
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Opgeteld")).toBeInTheDocument();
    expect(screen.getByText("€ 97")).toBeInTheDocument();     // 49 + 48
    expect(screen.getByText("/ € 170")).toBeInTheDocument();  // 85 + 85
  });

  it("kleurt de som groen zodra het opgetelde target gehaald wordt", () => {
    kaart({ target: 90, zonder: [] });
    expect(screen.getByText("/ € 90").className).toBe("sig-green");
  });

  it("kleurt rood onder het target", () => {
    kaart({ target: 170, zonder: [] });
    expect(screen.getByText("/ € 170").className).toBe("sig-red");
  });

  it("uitzetten laat alleen de merkregels staan", () => {
    kaart({ target: 170, zonder: [] });
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.queryByText("Opgeteld")).not.toBeInTheDocument();
    expect(screen.getByText(/ALESSANDRO/)).toBeInTheDocument();
  });

  it("meldt merken zonder ingesteld target", () => {
    kaart({ target: 85, zonder: ["DEPEND"] });
    expect(screen.getByText(/Zonder target: DEPEND/)).toBeInTheDocument();
  });

  it("zonder targets blijft de optelsom staan, zonder lat", () => {
    kaart({ target: null, zonder: ["ALESSANDRO", "DEPEND"] });
    expect(screen.getByText("€ 97")).toBeInTheDocument();
    expect(screen.getByText(/Nog geen target ingesteld voor ALESSANDRO, DEPEND/))
      .toBeInTheDocument();
  });
});
