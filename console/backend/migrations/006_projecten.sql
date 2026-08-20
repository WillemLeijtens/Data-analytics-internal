-- Projectcalculator: listings en acties vooraf doorrekenen.
--
-- Een project is een opgeslagen berekening: producten (de eerste vulling en
-- de verwachte rotatie), kosten, en een looptijd. De rekenkundige uitkomsten
-- staan bewust NIET in de database — die worden altijd vers afgeleid uit de
-- invoer (engine/projecten.py), zodat een formule-correctie ook oude
-- projecten meteen goed toont.

CREATE TABLE projecten (
  id INTEGER PRIMARY KEY,
  naam TEXT NOT NULL,
  retailer_id TEXT REFERENCES retailers(id),   -- NULL = geen retailer
  omschrijving TEXT,
  start_datum TEXT,                            -- YYYY-MM-DD
  eind_datum TEXT,
  aangemaakt_op TEXT NOT NULL DEFAULT (datetime('now')),
  aangemaakt_door TEXT,
  gewijzigd_op TEXT,
  gewijzigd_door TEXT
);

CREATE TABLE project_producten (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projecten(id) ON DELETE CASCADE,
  volgorde INTEGER NOT NULL DEFAULT 0,
  naam TEXT NOT NULL,
  kostprijs REAL,
  verkoopprijs REAL,
  aantal_winkels INTEGER,
  stuks_per_winkel REAL,                       -- de eerste vulling
  rotatie_per_winkel_per_week REAL,            -- verwachte doorverkoop
  verpakking_per_stuk REAL
);
CREATE INDEX ix_project_producten ON project_producten(project_id, volgorde);

CREATE TABLE project_kosten (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projecten(id) ON DELETE CASCADE,
  volgorde INTEGER NOT NULL DEFAULT 0,
  soort TEXT NOT NULL,        -- listing_fee|coop|marketing|display|logistiek|verpakking|overig
  label TEXT NOT NULL,
  bedrag REAL,
  terugkerend INTEGER NOT NULL DEFAULT 0       -- 0 = eenmalig, 1 = over de looptijd
);
CREATE INDEX ix_project_kosten ON project_kosten(project_id, volgorde);

CREATE TABLE project_log (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projecten(id) ON DELETE CASCADE,
  op TEXT NOT NULL DEFAULT (datetime('now')),
  door TEXT,
  actie TEXT NOT NULL
);
CREATE INDEX ix_project_log ON project_log(project_id, op);
