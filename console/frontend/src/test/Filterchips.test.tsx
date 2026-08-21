import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MultiChips } from "../components/shared";

// "vanaf week 4 geen data voor DEPEND (KV in België)" stond eerst als losse
// kaart boven het dashboard. Die melding hoort bij het merk zelf: dan zie je
// meteen wie het betreft, zonder een naam op te zoeken in een aparte tekst.

describe("MultiChips", () => {
  const merken = ["ALESSANDRO", "DEPEND", "TWEEZERMAN"];

  it("zonder waarschuwing is een chip gewoon een chip", () => {
    render(<MultiChips all={merken} sel={[]} onChange={vi.fn()} />);
    expect(screen.queryAllByRole("img")).toEqual([]);
  });

  it("de driehoek staat bij het merk waar hij over gaat, met de uitleg bij hover", () => {
    render(<MultiChips all={merken} sel={[]} onChange={vi.fn()}
      waarschuwing={{ DEPEND: "vanaf week 4 geen data voor DEPEND (KV in België)" }} />);
    const teken = screen.getByRole("img",
      { name: "Let op: vanaf week 4 geen data voor DEPEND (KV in België)" });
    // De hovertekst zit op hetzelfde element als het icoon.
    expect(teken).toHaveAttribute("title", "vanaf week 4 geen data voor DEPEND (KV in België)");
    // En het icoon zit ín de chip van DEPEND, niet ergens los ernaast.
    expect(teken.closest("button")).toHaveTextContent("DEPEND");
    expect(screen.queryAllByRole("img")).toHaveLength(1);
  });

  it("meerdere meldingen voor één merk worden regels in dezelfde tekst", () => {
    render(<MultiChips all={merken} sel={[]} onChange={vi.fn()}
      waarschuwing={{ DEPEND: "vanaf week 4 geen data voor België\nvanaf week 6 geen data voor Nederland" }} />);
    expect(screen.getByRole("img", { name: /België/ })).toHaveAttribute(
      "title", "vanaf week 4 geen data voor België\nvanaf week 6 geen data voor Nederland");
  });

  it("de chip blijft gewoon een filterknop", () => {
    const onChange = vi.fn();
    render(<MultiChips all={merken} sel={[]} onChange={onChange}
      waarschuwing={{ DEPEND: "geen data" }} />);
    fireEvent.click(screen.getByRole("button", { name: /DEPEND/ }));
    expect(onChange).toHaveBeenCalledWith(["DEPEND"]);
  });
});
