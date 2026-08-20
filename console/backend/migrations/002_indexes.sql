-- Herimport verwijdert de feiten van de vorige versie van hetzelfde bestand
-- op import_id; zonder index scant SQLite daarvoor de hele feitentabel.
CREATE INDEX IF NOT EXISTS ix_facts_import ON sellout_facts(import_id);

-- De winkelanalyse en het winkelaantal per merk tellen winkels per retailer.
CREATE INDEX IF NOT EXISTS ix_facts_winkel ON sellout_facts(retailer_id, winkel_id);
