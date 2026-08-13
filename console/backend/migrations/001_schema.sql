-- Migratie 001: canoniek model + operationele tabellen (SQLite-dialect)

CREATE TABLE retailers (
  id TEXT PRIMARY KEY,              -- 'kruidvat' | 'etos' | 'ici-paris-xl' | 'douglas'
  naam TEXT NOT NULL,
  aangesloten INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE parser_profiles (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('concept','test','live')),
  definition TEXT NOT NULL,         -- JSON, schema: PROMPT.md par.3 / profiles/*.json
  published_at TEXT,
  UNIQUE (retailer_id, version)
);

CREATE TABLE imports (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT REFERENCES retailers(id),   -- NULL zolang niet herkend
  profile_id INTEGER REFERENCES parser_profiles(id),
  filename TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  periode_type TEXT,                -- 'week' | 'maand'
  periode TEXT,                     -- '2026-W32' | '2026-07'
  row_count INTEGER,
  status TEXT NOT NULL CHECK (status IN ('ingelezen','test','profiel_nodig','error')),
  error_detail TEXT,                -- JSON: rijniveau-fouten
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX ux_imports_hash ON imports(file_hash);

CREATE TABLE sellout_facts (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  import_id INTEGER NOT NULL REFERENCES imports(id),
  periode_type TEXT NOT NULL CHECK (periode_type IN ('week','maand')),
  periode TEXT NOT NULL,
  land TEXT,
  banner TEXT,
  winkel_id TEXT,
  winkel_naam TEXT,
  merk TEXT,
  artikel_ean TEXT,
  artikel_naam TEXT,
  volume INTEGER NOT NULL,
  omzet REAL NOT NULL               -- excl. btw, EUR
);
CREATE INDEX ix_facts_query ON sellout_facts(retailer_id, periode_type, periode, merk);
CREATE INDEX ix_facts_artikel ON sellout_facts(retailer_id, artikel_ean);

CREATE TABLE retailer_settings (   -- winkelaantallen + omzettargets
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  merk TEXT NOT NULL,
  land TEXT NOT NULL,
  banner TEXT,                      -- NULL als retailer geen banner kent
  aantal_winkels INTEGER,           -- NULL = komt uit de feiten (ICI)
  target_per_winkel REAL,           -- EUR per winkel per periode
  UNIQUE (retailer_id, merk, land, banner)
);

CREATE TABLE rotatie_targets (
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  merk TEXT NOT NULL,
  stuks_per_winkel_per_week REAL NOT NULL,
  PRIMARY KEY (retailer_id, merk)
);

CREATE TABLE promo_confirmations (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  merk TEXT NOT NULL,
  land TEXT NOT NULL,
  banner TEXT,
  periode TEXT NOT NULL,            -- week of maand, volgt retailer-graan
  confirmed_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (retailer_id, merk, land, banner, periode)
);

CREATE TABLE mail_rules (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  naam TEXT NOT NULL,
  afzender TEXT,
  bijlage_glob TEXT,
  actief INTEGER NOT NULL DEFAULT 1,
  laatste_run TEXT
);

CREATE TABLE sharepoint_links (
  retailer_id TEXT PRIMARY KEY REFERENCES retailers(id),
  map_url TEXT NOT NULL,
  gekoppeld_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE contract_documents (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  naam TEXT NOT NULL,
  type TEXT,                        -- 'contract' | 'prijslijst' | 'bonusafspraak' | ...
  geldig_tot TEXT,                  -- ISO-datum
  signaal TEXT NOT NULL CHECK (signaal IN ('green','orange','red','grey'))
);

INSERT INTO retailers (id, naam, aangesloten) VALUES
  ('kruidvat','Kruidvat',1), ('etos','Etos',1),
  ('ici-paris-xl','ICI Paris XL',1), ('douglas','Douglas',0);
