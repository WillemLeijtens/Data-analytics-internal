-- Winkelaantallen zijn tot nu toe één getal dat je overschrijft: een daling
-- in distributie ("TWEEZERMAN ging van 530 naar 470 winkels") was daardoor
-- nergens te zien. Elke wijziging wordt hier bewaard, zodat het Overzicht
-- een distributiesignaal kan tonen voor retailers die géén winkelniveau
-- aanleveren (Kruidvat, Etos).
CREATE TABLE IF NOT EXISTS winkelaantal_historie (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  merk TEXT,
  land TEXT,
  banner TEXT,
  aantal_winkels INTEGER NOT NULL,
  gemeten_op TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_winkelhist ON winkelaantal_historie(
  retailer_id, merk, land, banner, gemeten_op);
