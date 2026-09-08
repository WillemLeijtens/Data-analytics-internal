-- Niveau van een feitregel, voor retailers die dezelfde omzet in TWEE
-- decomposities aanleveren. Douglas stuurt per maand een rapport per artikel
-- (zonder winkel) en een rapport per winkel (zonder artikel); beide tellen
-- op tot precies hetzelfde totaal. Naast elkaar in deze tabel zou de omzet
-- verdubbelen, en de korrelwissel-regel van de importer grijpt niet in omdat
-- de sleutels (EAN gevuld tegen winkel_id gevuld) elkaar nooit raken.
--
--   NULL       de ene decompositie die alle bestaande retailers hebben
--   'artikel'  de artikelverdeling van een gesplitste feed
--   'winkel'   de winkelverdeling van een gesplitste feed
--
-- analytics.load_facts leest standaard NULL + 'artikel' (de omzetwaarheid
-- voor artikelen, promoties en assortiment); het dashboard en het
-- winkelsignaal vragen om NULL + 'winkel', omdat daar teller en noemer uit
-- dezelfde rijen moeten komen. NIET onderdeel van de dedup-sleutel
-- (engine/importer.py, _FACT_KEY): de sleutels verschillen al.
ALTER TABLE sellout_facts ADD COLUMN niveau TEXT;

-- Partieel: alleen de gesplitste retailers hebben rijen met een niveau, en
-- de EXISTS-toets "heeft deze retailer een winkelslice?" hoort niet elke
-- dashboardcall van Kruidvat of Etos over honderdduizend rijen te laten
-- scannen.
CREATE INDEX ix_facts_niveau ON sellout_facts(retailer_id, niveau)
  WHERE niveau IS NOT NULL;
