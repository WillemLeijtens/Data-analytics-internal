import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Changelog from "../screens/Changelog";
import { CHANGELOG } from "../changelog";

describe("Changelog", () => {
  it("toont elke entry met titel en datum", () => {
    render(<Changelog />);
    for (const e of CHANGELOG) {
      // getAllByText: sommige entrytitels ("Changelog") komen ook voor als
      // paginakop — het gaat erom dat de entry ÉRGENS gerenderd wordt.
      expect(screen.getAllByText(e.titel).length).toBeGreaterThan(0);
    }
  });

  it("staat niet leeg — er is releasehistorie om te tonen", () => {
    expect(CHANGELOG.length).toBeGreaterThan(0);
  });

  it("elke entry heeft een geldige ISO-datum, nieuwste bovenaan", () => {
    const datums = CHANGELOG.map((e) => e.datum);
    for (const d of datums) expect(d).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const gesorteerd = [...datums].sort().reverse();
    expect(datums).toEqual(gesorteerd);
  });
});
