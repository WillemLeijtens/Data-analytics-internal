import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LevelStrip } from "../components/shared";

// SCHATTING en OP MERKNIVEAU stonden als kale chip zonder duiding — deze
// test borgt dat elk bekend niveau-label een info-icoon met uitleg krijgt.

describe("LevelStrip", () => {
  it("toont een info-icoon met uitleg bij SCHATTING", () => {
    render(<MemoryRouter><LevelStrip labels={["SCHATTING"]} retailer="kruidvat" /></MemoryRouter>);
    const knop = screen.getByRole("button", { name: /Uitleg: Deze retailer levert geen winkel-ID/ });
    fireEvent.mouseEnter(knop);
    expect(screen.getByText(/handmatig ingestelde/)).toBeInTheDocument();
  });

  it("toont een info-icoon met uitleg bij OP MAANDNIVEAU", () => {
    render(<MemoryRouter><LevelStrip labels={["OP MAANDNIVEAU"]} retailer="kruidvat" /></MemoryRouter>);
    const knop = screen.getByRole("button", { name: /Uitleg: Deze retailer levert per maand/ });
    fireEvent.mouseEnter(knop);
    expect(screen.getByText(/rekenen met maanden/)).toBeInTheDocument();
  });

  it("geen icoon bij een onbekend label — geen kapotte lookup", () => {
    render(<MemoryRouter><LevelStrip labels={["IETS NIEUWS"]} retailer="kruidvat" /></MemoryRouter>);
    expect(screen.getByText("IETS NIEUWS")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
