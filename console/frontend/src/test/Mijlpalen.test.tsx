import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Milestone, PromoMarker } from "../api";
import { TrendChart } from "../components/shared";

// De grafiek is de enige plek waar je een mijlpaal zet: je klikt op de week
// waar iets gebeurde. Die klik moet dus de júiste week voorstellen, en het
// formulier moet die week ook echt meesturen.

const series = { 2025: { 10: 100, 11: 120, 12: 90 }, 2026: { 10: 130, 11: 140, 12: 150 } };
const jaren = [2025, 2026];
const MERKEN = ["ALESSANDRO", "TWEEZERMAN"];

function mijlpaal(over: Partial<Milestone> = {}): Milestone {
  return {
    id: 1, jaar: 2025, periode_nummer: 11, tekst: "introductie nieuw item",
    merk: "TWEEZERMAN", aangemaakt_op: "2026-01-01 10:00:00",
    aangemaakt_door: "Willem", ...over,
  };
}

/** De regels onder de grafiek. Niet screen.getByText: de <title> van de svg
 *  bevat dezelfde tekst (voor de browsertooltip), dus die matcht ook. */
const lijst = () => screen.queryAllByRole("listitem").map((li) => li.textContent ?? "");

/** jsdom geeft SVG's een lege bounding box; zonder deze stub is elke
 *  x-berekening NaN en zegt een kliktest niets. */
function stubBreedte() {
  vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockReturnValue(
    { left: 0, top: 0, width: 860, height: 260, right: 860, bottom: 260, x: 0, y: 0,
      toJSON: () => ({}) } as DOMRect);
}

describe("TrendChart — mijlpalen", () => {
  it("zonder handler blijft de grafiek precies wat hij was", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week" />);
    fireEvent.click(screen.getByRole("img"));
    expect(screen.queryByRole("button", { name: /plaatsen/i })).not.toBeInTheDocument();
  });

  it("een klik opent het formulier op de aangeklikte week en stuurt die mee", async () => {
    stubBreedte();
    const onMijlpaal = vi.fn().mockResolvedValue(undefined);
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} merken={MERKEN} onMijlpaal={onMijlpaal} />);

    // Uiterst rechts in de grafiek: dat is week 12, de laatste periode.
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    expect(screen.getByText(/mijlpaal op week 12/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Merk"), { target: { value: "TWEEZERMAN" } });
    fireEvent.change(screen.getByLabelText("Wat gebeurde er?"),
      { target: { value: "introductie nieuw item" } });
    fireEvent.click(screen.getByRole("button", { name: "Plaatsen" }));

    await waitFor(() => expect(onMijlpaal).toHaveBeenCalledWith({
      // Standaard het laatste jaar van de grafiek; de select laat 'm wijzigen.
      jaar: 2026, periode_nummer: 12, tekst: "introductie nieuw item",
      merk: "TWEEZERMAN",
    }));
  });

  it("het jaar is te kiezen — week 12 van 2025 is een ander punt dan van 2026", async () => {
    stubBreedte();
    const onMijlpaal = vi.fn().mockResolvedValue(undefined);
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} merken={MERKEN} onMijlpaal={onMijlpaal} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    fireEvent.change(screen.getByLabelText("Jaar"), { target: { value: "2025" } });
    fireEvent.change(screen.getByLabelText("Merk"), { target: { value: "ALESSANDRO" } });
    fireEvent.change(screen.getByLabelText("Wat gebeurde er?"), { target: { value: "folder" } });
    fireEvent.click(screen.getByRole("button", { name: "Plaatsen" }));
    await waitFor(() => expect(onMijlpaal.mock.calls[0][0].jaar).toBe(2025));
  });

  it("het formulier is klikbaar — niet de .tooltip-klasse, die laat kliks erdoor", () => {
    // Gemelde bug: het jaarveld was niet aan te klikken, elke klik opende de
    // grafiek eronder opnieuw. Oorzaak: het formulier hergebruikte .tooltip,
    // en die heeft pointer-events:none (nodig, anders blokkeert een
    // hover-tooltip de grafiek). jsdom rekent geen stylesheets door, dus de
    // klik zelf is hier niet na te spelen — de klasse wél.
    stubBreedte();
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} merken={MERKEN} onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    const formulier = screen.getByRole("dialog", { name: "Mijlpaal plaatsen" });
    expect(formulier).toHaveClass("chart-popover");
    expect(formulier).not.toHaveClass("tooltip");
  });

  it("een lege omschrijving is niet te plaatsen", () => {
    stubBreedte();
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} merken={MERKEN} onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    fireEvent.change(screen.getByLabelText("Merk"), { target: { value: "TWEEZERMAN" } });
    expect(screen.getByRole("button", { name: "Plaatsen" })).toBeDisabled();
  });

  it("zonder merk is een mijlpaal niet te plaatsen", () => {
    // Een mijlpaal zonder merk staat op elke grafiek, ook op die van een merk
    // waar niets gebeurde.
    stubBreedte();
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} merken={MERKEN} onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    fireEvent.change(screen.getByLabelText("Wat gebeurde er?"), { target: { value: "iets" } });
    expect(screen.getByLabelText("Merk")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Plaatsen" })).toBeDisabled();
  });

  it("is er maar één merk in beeld, dan is de keuze al gemaakt", () => {
    stubBreedte();
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} merken={["TWEEZERMAN"]} onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    expect(screen.getByLabelText("Merk")).toHaveValue("TWEEZERMAN");
  });

  it("het schuifje zet de mijlpalen uit en weer aan", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal()]} onMijlpaal={vi.fn()} />);
    expect(lijst()).toHaveLength(1);
    fireEvent.click(screen.getByRole("switch"));
    expect(lijst()).toEqual([]);
    fireEvent.click(screen.getByRole("switch"));
    expect(lijst()).toHaveLength(1);
  });

  it("filteren op jaar laat alleen dat jaar staan", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal(), mijlpaal({ id: 2, jaar: 2026, tekst: "prijsverhoging" })]}
      onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    expect(lijst().join()).toMatch(/prijsverhoging/);
    expect(lijst().join()).not.toMatch(/introductie nieuw item/);
    // Nog eens klikken haalt het filter er weer af.
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    expect(lijst()).toHaveLength(2);
  });

  it("een mijlpaal buiten de getoonde weken verdwijnt niet, maar wordt gemeld", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal({ periode_nummer: 45 })]} onMijlpaal={vi.fn()} />);
    expect(lijst()[0]).toMatch(/introductie nieuw item/);
    expect(lijst()[0]).toMatch(/buiten de getoonde periodes/i);
  });

  it("de lijst noemt het merk waar de mijlpaal bij hoort", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal()]} merken={MERKEN} onMijlpaal={vi.fn()} />);
    expect(lijst()[0]).toMatch(/TWEEZERMAN — introductie nieuw item/);
  });

  it("verwijderen gaat via de lijst", () => {
    const weg = vi.fn().mockResolvedValue(undefined);
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal()]} onMijlpaal={vi.fn()} onMijlpaalWeg={weg} />);
    fireEvent.click(screen.getByRole("button", { name: /introductie nieuw item verwijderen/i }));
    expect(weg).toHaveBeenCalledWith(1);
  });
});


// Promotiemarkers staan naast de mijlpalen in dezelfde grafiek. Ze moeten
// zonder kleur uit elkaar te houden zijn (andere vorm) en hun eigen schuifje
// en filters hebben — een actie is iets anders dan een mijlpaal.

function promo(over: Partial<PromoMarker> = {}): PromoMarker {
  return {
    merk: "TWEEZERMAN", land: "NL", banner: null, jaar: 2026,
    periode_nummer: 11, periode: "2026-W11", omzet: 1200, basislijn: 1000,
    uplift_pct: 20, ...over,
  };
}

describe("TrendChart — promoties", () => {
  it("zonder acties verandert er niets aan de grafiek", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      promoties={[]} />);
    expect(screen.queryByLabelText("Promoties tonen")).not.toBeInTheDocument();
  });

  it("een actie krijgt een eigen kleur en een andere vorm dan een mijlpaal", () => {
    const { container } = render(<TrendChart series={series} years={jaren} isEuro
      periodWord="Week" mijlpalen={[mijlpaal()]} promoties={[promo()]} />);
    const kleuren = Array.from(container.querySelectorAll("path"))
      .map((el) => el.getAttribute("fill")).filter(Boolean);
    expect(kleuren).toContain("var(--promo)");
    // De mijlpaal gebruikt een jaarkleur, de actie niet — anders lijkt hij bij
    // een van de lijnen te horen.
    expect(kleuren.filter((k) => k === "var(--promo)")).toHaveLength(1);
    const vormen = Array.from(container.querySelectorAll("path"))
      .map((el) => el.getAttribute("d"));
    // Ruit (vier zijden) voor de mijlpaal, driehoek (drie punten) voor de actie.
    expect(vormen.some((d) => d?.includes("l4,4 l-4,4 l-4,-4 z"))).toBe(true);
    expect(vormen.some((d) => d?.includes("l5,7 l-10,0 z"))).toBe(true);
  });

  it("de hovertekst noemt de uplift met de twee bedragen", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      promoties={[promo()]} />);
    // getByTitle kijkt alleen naar een <title> direct onder de <svg>; die van
    // een marker zit in een groep, dus zoeken op de tekst zelf.
    const titel = screen.getByText(/Actie week 11 2026/);
    expect(titel.textContent).toMatch(/\+20%/);
    expect(titel.textContent).toMatch(/tegen een basislijn van/);
  });

  it("het eigen schuifje zet alleen de acties uit", () => {
    const { container } = render(<TrendChart series={series} years={jaren} isEuro
      periodWord="Week" mijlpalen={[mijlpaal()]} promoties={[promo()]} />);
    const promoKleuren = () => Array.from(container.querySelectorAll("path"))
      .filter((el) => el.getAttribute("fill") === "var(--promo)").length;
    expect(promoKleuren()).toBe(1);
    fireEvent.click(screen.getByLabelText("Promoties tonen"));
    expect(promoKleuren()).toBe(0);
    // De mijlpaal staat er nog: twee soorten, twee schuifjes.
    expect(lijst()).toHaveLength(1);
  });

  it("filteren op merk raakt alleen de promotiemarkers", () => {
    const { container } = render(<TrendChart series={series} years={jaren} isEuro
      periodWord="Week" mijlpalen={[mijlpaal()]}
      promoties={[promo(), promo({ merk: "ALESSANDRO", periode: "2026-W12",
                                   periode_nummer: 12 })]} />);
    const promoKleuren = () => Array.from(container.querySelectorAll("path"))
      .filter((el) => el.getAttribute("fill") === "var(--promo)").length;
    expect(promoKleuren()).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "ALESSANDRO" }));
    expect(promoKleuren()).toBe(1);
    expect(lijst()).toHaveLength(1);   // de mijlpaal blijft staan
  });

  it("zonder uplift zegt de hovertekst waarom", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      promoties={[promo({ uplift_pct: null, basislijn: null,
                          reden: "te weinig basisperiodes" })]} />);
    expect(screen.getByText(/geen uplift: te weinig basisperiodes/)).toBeInTheDocument();
  });
});
