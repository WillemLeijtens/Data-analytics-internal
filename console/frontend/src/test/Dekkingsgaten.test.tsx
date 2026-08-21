import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DekkingsgatenKaart } from "../components/shared";

// "vanaf week 3 geen data voor België" stond alleen als driehoekje per
// artikel in de artikelanalyse. De totalen op het dashboard worden er net zo
// goed door vertekend — en daar is het aan de cijfers niet af te lezen.

describe("DekkingsgatenKaart", () => {
  const regels = () => screen.queryAllByRole("listitem").map((li) => li.textContent);

  it("toont niets als de aanlevering compleet is", () => {
    const { container } = render(<DekkingsgatenKaart gaten={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("noemt elk gat en zegt wat het met de cijfers doet", () => {
    render(<DekkingsgatenKaart gaten={[
      { soort: "stopt", tekst: "vanaf week 3 geen data voor België" }]} />);
    expect(regels()).toEqual(["vanaf week 3 geen data voor België"]);
    // Zonder deze zin is een waarschuwing een weetje in plaats van een reden
    // om het getal met een korrel zout te nemen.
    expect(screen.getByText(/lager cijfer dan de werkelijkheid/)).toBeInTheDocument();
  });

  it("een stilgevallen feed staat bovenaan", () => {
    // Die vertekent het meest recente cijfer — het getal waar je nú naar kijkt.
    render(<DekkingsgatenKaart gaten={[
      { soort: "begint_later", tekst: "geen data voor België vóór week 5" },
      { soort: "onderbroken", tekst: "geen data voor Nederland in week 7" },
      { soort: "stopt", tekst: "vanaf week 3 geen data voor Luxemburg" },
    ]} />);
    expect(regels()).toEqual([
      "vanaf week 3 geen data voor Luxemburg",
      "geen data voor Nederland in week 7",
      "geen data voor België vóór week 5",
    ]);
  });
});
