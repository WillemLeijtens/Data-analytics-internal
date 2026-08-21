import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Milestone } from "../api";
import { TrendChart } from "../components/shared";

// De grafiek is de enige plek waar je een mijlpaal zet: je klikt op de week
// waar iets gebeurde. Die klik moet dus de júiste week voorstellen, en het
// formulier moet die week ook echt meesturen.

const series = { 2025: { 10: 100, 11: 120, 12: 90 }, 2026: { 10: 130, 11: 140, 12: 150 } };
const jaren = [2025, 2026];

function mijlpaal(over: Partial<Milestone> = {}): Milestone {
  return {
    id: 1, jaar: 2025, periode_nummer: 11, tekst: "introductie nieuw item",
    aangemaakt_op: "2026-01-01 10:00:00", aangemaakt_door: "Willem", ...over,
  };
}

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
      mijlpalen={[]} onMijlpaal={onMijlpaal} />);

    // Uiterst rechts in de grafiek: dat is week 12, de laatste periode.
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    expect(screen.getByText(/mijlpaal op week 12/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Wat gebeurde er?"),
      { target: { value: "introductie nieuw item" } });
    fireEvent.click(screen.getByRole("button", { name: "Plaatsen" }));

    await waitFor(() => expect(onMijlpaal).toHaveBeenCalledWith({
      // Standaard het laatste jaar van de grafiek; de select laat 'm wijzigen.
      jaar: 2026, periode_nummer: 12, tekst: "introductie nieuw item",
    }));
  });

  it("het jaar is te kiezen — week 12 van 2025 is een ander punt dan van 2026", async () => {
    stubBreedte();
    const onMijlpaal = vi.fn().mockResolvedValue(undefined);
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} onMijlpaal={onMijlpaal} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    fireEvent.change(screen.getByLabelText("Jaar"), { target: { value: "2025" } });
    fireEvent.change(screen.getByLabelText("Wat gebeurde er?"), { target: { value: "folder" } });
    fireEvent.click(screen.getByRole("button", { name: "Plaatsen" }));
    await waitFor(() => expect(onMijlpaal.mock.calls[0][0].jaar).toBe(2025));
  });

  it("een lege omschrijving is niet te plaatsen", () => {
    stubBreedte();
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[]} onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("img"), { clientX: 830 });
    expect(screen.getByRole("button", { name: "Plaatsen" })).toBeDisabled();
  });

  it("het schuifje zet de mijlpalen uit en weer aan", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal()]} onMijlpaal={vi.fn()} />);
    expect(screen.getByText("introductie nieuw item")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.queryByText("introductie nieuw item")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByText("introductie nieuw item")).toBeInTheDocument();
  });

  it("filteren op jaar laat alleen dat jaar staan", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal(), mijlpaal({ id: 2, jaar: 2026, tekst: "prijsverhoging" })]}
      onMijlpaal={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    expect(screen.getByText("prijsverhoging")).toBeInTheDocument();
    expect(screen.queryByText("introductie nieuw item")).not.toBeInTheDocument();
    // Nog eens klikken haalt het filter er weer af.
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    expect(screen.getByText("introductie nieuw item")).toBeInTheDocument();
  });

  it("een mijlpaal buiten de getoonde weken verdwijnt niet, maar wordt gemeld", () => {
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal({ periode_nummer: 45 })]} onMijlpaal={vi.fn()} />);
    expect(screen.getByText("introductie nieuw item")).toBeInTheDocument();
    expect(screen.getByText(/buiten de getoonde periodes/i)).toBeInTheDocument();
  });

  it("verwijderen gaat via de lijst", () => {
    const weg = vi.fn().mockResolvedValue(undefined);
    render(<TrendChart series={series} years={jaren} isEuro periodWord="Week"
      mijlpalen={[mijlpaal()]} onMijlpaal={vi.fn()} onMijlpaalWeg={weg} />);
    fireEvent.click(screen.getByRole("button", { name: /introductie nieuw item verwijderen/i }));
    expect(weg).toHaveBeenCalledWith(1);
  });
});
