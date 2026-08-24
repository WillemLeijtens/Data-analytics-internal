import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PromoMarker } from "../api";
import { OmzeteffectKaart } from "../components/shared";

// De kaart is verhuisd van de Promoties-pagina naar het dashboard; deze
// tests pinnen dat er onderweg niets van de inhoud verloren ging.

function rij(over: Partial<PromoMarker & { basisperiodes: number }> = {}) {
  return {
    merk: "TWEEZERMAN", land: "NL", banner: null, jaar: 2026,
    periode_nummer: 5, periode: "2026-W05", omzet: 4730.82,
    basislijn: 2950.62, uplift_pct: 60.3, basisperiodes: 18, reden: null, ...over,
  };
}

describe("OmzeteffectKaart", () => {
  it("rendert niets zonder bevestigde acties", () => {
    const { container } = render(<OmzeteffectKaart rijen={[]} periodWord="Week" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("toont de samenvatting en het percentage met de twee bedragen bij hover", () => {
    render(<OmzeteffectKaart rijen={[rij()]} periodWord="Week" />);
    expect(screen.getByText(/1 promoties gemeten/)).toBeInTheDocument();
    // "+60.3%" staat ook in de samenvatting (beste); de regelversie is de
    // enige met een hovertekst.
    const pct = screen.getAllByText("+60.3%").find((el) => el.getAttribute("title"))!;
    // Zonder de actie-omzet en de basislijn is het percentage niet na te
    // rekenen — die horen in de hovertekst te staan.
    // fmtEur rondt op hele euro's — de bedragen zelf, niet de centen, maken
    // het percentage narekenbaar.
    expect(pct.getAttribute("title")).toMatch(/4\.731.*basislijn.*2\.951/s);
    expect(pct.getAttribute("title")).toMatch(/mediaan van 18 week\(en\)/);
  });

  it("filtert op jaar", () => {
    render(<OmzeteffectKaart periodWord="Week" rijen={[
      rij(), rij({ jaar: 2025, periode: "2025-W40", uplift_pct: 12.0 })]} />);
    expect(screen.getByText(/2 promoties gemeten/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2025" }));
    expect(screen.getByText(/1 promoties gemeten/)).toBeInTheDocument();
    expect(screen.queryByText("+60.3%")).not.toBeInTheDocument();
  });

  it("een actie zonder uplift toont de reden en telt niet mee in het gemiddelde", () => {
    render(<OmzeteffectKaart periodWord="Week" rijen={[
      rij(), rij({ periode: "2026-W33", uplift_pct: null, basislijn: null,
                   reden: "periode loopt nog" })]} />);
    expect(screen.getByText("periode loopt nog")).toBeInTheDocument();
    // Gemiddelde alleen over de gemeten actie: +60,3%, niet gehalveerd.
    expect(screen.getByText(/gem\./).textContent).toMatch(/\+60\.3%/);
  });
});
