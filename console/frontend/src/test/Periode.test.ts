import { describe, expect, it } from "vitest";
import { fmtPeriode } from "../api";

// De korrel komt uit de periodestring zelf: Etos en Kruidvat leveren weken,
// ICI Paris maanden. Gebruikt voor de on-counter-kolom in de artikelanalyse.

describe("fmtPeriode", () => {
  it("leest een week", () => {
    expect(fmtPeriode("2025-W40")).toBe("wk 40 2025");
    expect(fmtPeriode("2026-W01")).toBe("wk 1 2026");
  });

  it("leest een maand", () => {
    expect(fmtPeriode("2026-03")).toBe("mrt 2026");
    expect(fmtPeriode("2025-12")).toBe("dec 2025");
  });

  it("geeft een streepje zonder periode", () => {
    expect(fmtPeriode(null)).toBe("—");
    expect(fmtPeriode(undefined)).toBe("—");
  });

  it("laat onbekende vormen ongemoeid in plaats van te raden", () => {
    expect(fmtPeriode("2026-99")).toBe("2026-99");
    expect(fmtPeriode("rommel")).toBe("rommel");
  });
});
