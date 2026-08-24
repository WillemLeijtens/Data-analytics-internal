import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DeltaTag } from "../components/shared";

// Gebruikt op de KPI-kaarten bovenaan het dashboard (Omzet/Volume/Omzet per
// winkel) voor de week-op-week-vergelijking: positief groen, negatief rood,
// en zonder vorige periode (gat, of de allereerste levering) geen cijfer.

describe("DeltaTag", () => {
  it("toont een positief percentage groen, met plusteken", () => {
    render(<DeltaTag pct={20} />);
    const el = screen.getByText("+20%");
    expect(el.className).toContain("pos");
  });

  it("toont een negatief percentage rood, zonder extra minteken", () => {
    render(<DeltaTag pct={-8.3} />);
    const el = screen.getByText("-8,3%");
    expect(el.className).toContain("neg");
  });

  it("toont een streepje zonder kleur wanneer er niets te vergelijken valt", () => {
    render(<DeltaTag pct={null} />);
    const el = screen.getByText("—");
    expect(el.className).not.toContain("pos");
    expect(el.className).not.toContain("neg");
  });

  it("geeft de vergeleken periode mee als title", () => {
    render(<DeltaTag pct={5} titel="Vs. week 2026-W31" />);
    expect(screen.getByText("+5%")).toHaveAttribute("title", "Vs. week 2026-W31");
  });
});
