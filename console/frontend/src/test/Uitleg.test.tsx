import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Uitleg } from "../components/shared";

// Deze sessie eerder gebouwd na een gemelde bug (klik-na-hover sloot de
// popover meteen weer, doordat een muisklik altijd een mouseenter triggert
// vóór de click). Nog nergens geautomatiseerd getest — deze test borgt het
// klik-om-vast-te-pinnen-gedrag tegen die regressie.

describe("Uitleg", () => {
  it("toont niets totdat er gehoverd of geklikt wordt", () => {
    render(<Uitleg tekst="Een uitleg." />);
    expect(screen.queryByText("Een uitleg.")).not.toBeInTheDocument();
  });

  it("toont de tekst bij hover en verbergt hem weer bij mouseleave", () => {
    render(<Uitleg tekst="Een uitleg." />);
    const knop = screen.getByRole("button", { name: "Uitleg: Een uitleg." });
    fireEvent.mouseEnter(knop);
    expect(screen.getByText("Een uitleg.")).toBeInTheDocument();
    fireEvent.mouseLeave(knop);
    expect(screen.queryByText("Een uitleg.")).not.toBeInTheDocument();
  });

  it("blijft open na een klik, ook nadat de muis weggaat (vastgepind)", () => {
    render(<Uitleg tekst="Een uitleg." />);
    const knop = screen.getByRole("button", { name: "Uitleg: Een uitleg." });
    // Een echte klik triggert altijd eerst mouseenter, dan click.
    fireEvent.mouseEnter(knop);
    fireEvent.click(knop);
    fireEvent.mouseLeave(knop);
    expect(screen.getByText("Een uitleg.")).toBeInTheDocument();
  });

  it("een tweede klik unpint 'm, maar hij blijft zichtbaar zolang de muis er nog op staat", () => {
    // hover en vast zijn bewust losse vlaggen (open = hover || vast): een
    // muisklik impliceert altijd dat de muis er al op staat, dus unpinnen
    // via een toggle mag de popover niet meteen sluiten zolang er nog
    // gehoverd wordt — pas wanneer de muis ook echt weggaat, sluit hij.
    render(<Uitleg tekst="Een uitleg." />);
    const knop = screen.getByRole("button", { name: "Uitleg: Een uitleg." });
    fireEvent.mouseEnter(knop);
    fireEvent.click(knop);
    fireEvent.click(knop);
    expect(screen.getByText("Een uitleg.")).toBeInTheDocument();
    fireEvent.mouseLeave(knop);
    expect(screen.queryByText("Een uitleg.")).not.toBeInTheDocument();
  });

  it("sluit op Escape", () => {
    render(<Uitleg tekst="Een uitleg." />);
    const knop = screen.getByRole("button", { name: "Uitleg: Een uitleg." });
    fireEvent.mouseEnter(knop);
    fireEvent.click(knop);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Een uitleg.")).not.toBeInTheDocument();
  });

  it("sluit bij een klik buiten de knop en de popover", () => {
    render(<Uitleg tekst="Een uitleg." />);
    const knop = screen.getByRole("button", { name: "Uitleg: Een uitleg." });
    fireEvent.mouseEnter(knop);
    fireEvent.click(knop);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText("Een uitleg.")).not.toBeInTheDocument();
  });
});
