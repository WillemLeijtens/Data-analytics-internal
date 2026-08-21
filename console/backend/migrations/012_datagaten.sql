-- Oordeel over een meerjarig gat in de aanlevering.
--
-- engine/dekking.py vindt gaten BINNEN het laatste jaar. Een merk dat in
-- 2024 doorverkoop had, in 2025 niets, en in 2026 weer wel, valt daar
-- structureel buiten: dekking.py filtert eerst op het laatste jaar. Zo'n
-- gat is precies het geval waarbij je wilt weten of het klopt (het merk lag
-- dat jaar niet bij deze retailer) of niet (een bestand is nooit ingelezen)
-- — en dat verschil kan alleen een mens vaststellen.
--
-- Het oordeel hangt aan de SCOPE plus het jaarbereik van het gat, niet aan
-- een id van een bevinding: de detectie draait elke keer opnieuw en zou
-- anders bij elke import een "nieuw" gat opleveren dat al beoordeeld was.
CREATE TABLE datagat_oordelen (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  merk TEXT,
  land TEXT,
  banner TEXT,
  van_jaar INTEGER NOT NULL,
  tot_jaar INTEGER NOT NULL,
  oordeel TEXT NOT NULL CHECK (oordeel IN ('klopt', 'klopt_niet')),
  toelichting TEXT,
  door TEXT,
  op TEXT NOT NULL DEFAULT (datetime('now'))
);

-- COALESCE, want merk/land/banner mogen NULL zijn en SQLite ziet losse
-- NULLs in een UNIQUE index elk als uniek — precies de rijen die hier vaak
-- NULL zijn zouden dan dubbel beoordeeld kunnen worden.
CREATE UNIQUE INDEX ux_datagat_scope ON datagat_oordelen(
  retailer_id, COALESCE(merk, ''), COALESCE(land, ''), COALESCE(banner, ''),
  van_jaar, tot_jaar
);
