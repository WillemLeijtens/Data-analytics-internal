-- Mijlpalen op de trendgrafiek: "hier introduceerden we artikel X",
-- "hier liep de actie". Zonder die context is een piek in de lijn een
-- raadsel dat elk kwartaal opnieuw wordt uitgezocht.
--
-- De x-as van de grafiek is het PERIODENUMMER (week of maand) met de jaren
-- als losse lijnen eroverheen. Een mijlpaal hoort dus bij een jaar én een
-- periodenummer: week 12 van 2025 ligt op dezelfde x als week 12 van 2026,
-- maar op een andere lijn.
CREATE TABLE milestones (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  jaar INTEGER NOT NULL,
  periode_nummer INTEGER NOT NULL,
  tekst TEXT NOT NULL,
  aangemaakt_op TEXT NOT NULL DEFAULT (datetime('now')),
  aangemaakt_door TEXT
);
CREATE INDEX ix_milestones_retailer ON milestones(retailer_id, jaar, periode_nummer);
