-- Productcategorie, geleverd door Etos in de Class-kolom van de Data
-- Grid-export ("SHAMPOO - 3", "HAARSTYLING - 186", ...). Zelfde patroon als
-- Brand: het interne nummer wordt gestript, alleen de naam blijft over.
--
-- NIET onderdeel van de natuurlijke dedup-sleutel (engine/importer.py,
-- _FACT_KEY): dezelfde verkoop blijft dezelfde regel, ook als een latere
-- export de categorie wél meebrengt en een eerdere niet. Andere
-- retailers/parsers laten dit veld gewoon NULL.
ALTER TABLE sellout_facts ADD COLUMN categorie TEXT;
