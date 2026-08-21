-- Winkelaantallen per artikel, naast het bestaande merkniveau.
--
-- Niet elk artikel van een merk ligt in evenveel winkels: een basisitem in
-- 800 filialen, een nieuwe kleur in 120. Eén getal voor het hele merk maakt
-- van de omzet per winkel van dat nieuwe item een fractie van wat het echt
-- is.
--
-- LET OP bij het merkgemiddelde. Uit losse artikelaantallen is het aantal
-- winkels van het MERK niet exact af te leiden: dat is de vereniging van de
-- winkels per artikel, en uit alleen aantallen weet je daarvan alleen de
-- grenzen — minimaal het grootste artikel, maximaal de som. De app rekent
-- met het grootste artikel. Dat klopt zolang het smallere assortiment in
-- dezelfde winkels ligt als het brede (de normale situatie: een filiaal met
-- de nieuwe kleur voert vrijwel altijd ook het basisitem). Liggen twee
-- artikelen in verschillende winkels, dan is het echte aantal hoger en valt
-- de omzet per winkel op merkniveau te hoog uit. Het scherm meldt daarom
-- waar het merkgetal vandaan komt.
ALTER TABLE retailer_settings ADD COLUMN niveau TEXT NOT NULL DEFAULT 'merk';

CREATE TABLE artikel_winkelaantallen (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  merk TEXT NOT NULL,
  land TEXT NOT NULL,
  banner TEXT,
  artikel_ean TEXT NOT NULL,
  aantal_winkels INTEGER
);

-- COALESCE, want banner mag NULL zijn en SQLite ziet losse NULLs in een
-- UNIQUE index elk als uniek.
CREATE UNIQUE INDEX ux_artikel_winkels ON artikel_winkelaantallen(
  retailer_id, merk, land, COALESCE(banner, ''), artikel_ean
);
