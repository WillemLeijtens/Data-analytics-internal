-- Conclusie per retailer: één opgeslagen tekst, geschreven door Claude op
-- basis van de bevindingen die engine/conclusie.py deterministisch uit de
-- vier analyses haalt (dashboard, assortiment, winkelontwikkeling,
-- promoties).
--
-- `bevindingen` bewaart de JSON-momentopname WAAROP de tekst rust. Zonder die
-- momentopname staat er straks een conclusie zonder bewijs: de data verandert
-- bij elke import, en dan is niet meer na te gaan uit welk cijfer een zin
-- volgde. Met de momentopname blijft elke zin narekenbaar, ook maanden later.
--
-- `vingerafdruk` is de datum-ONAFHANKELIJKE staat van de data van déze
-- retailer op het moment van genereren (zie conclusie.vingerafdruk()). Wijkt
-- de huidige vingerafdruk daarvan af, dan is de tekst verouderd en werkt het
-- scherm hem bij. Bewust niet de analysecache-versie uit main.py: die bevat
-- de datum van vandaag, en dan zou élke nacht elke conclusie herschreven
-- worden — een API-call per retailer per dag zonder dat er iets veranderd is.
--
-- LET OP: deze tabel hoort in _NIET_HASHEN (main.py). Tabellen onder 200
-- rijen gaan op INHOUD mee in de globale dataversie; een opgeslagen conclusie
-- zou anders de cache van álle analyses van álle retailers leegtrekken.
CREATE TABLE retailer_conclusies (
  retailer_id TEXT PRIMARY KEY REFERENCES retailers(id),
  samenvatting TEXT NOT NULL,
  advies TEXT,
  bevindingen TEXT NOT NULL,
  vingerafdruk TEXT NOT NULL,
  model TEXT,
  waarschuwingen TEXT,
  gegenereerd_op TEXT NOT NULL DEFAULT (datetime('now')),
  gegenereerd_door TEXT
);
