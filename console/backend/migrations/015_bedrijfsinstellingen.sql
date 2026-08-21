-- Drempelmarges: onder welk percentage een project niet meer de moeite is.
--
-- Twee drempels, want het zijn twee verschillende beslissingen. De eenmalige
-- vulling is een investering die je één keer doet (listing fee, display) en
-- mag krapper; de terugkerende omzet moet het jaar rond dragen. Eén getal
-- voor allebei zou de ene beslissing altijd verkeerd normeren.
--
-- Bedrijfsbreed, niet per retailer: het is een norm van ons, niet van hen.
-- Eén rij (id=1), zoals anthropic_config.
CREATE TABLE bedrijfsinstellingen (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  -- NULL = geen drempel ingesteld; dan meet het scherm niets en meldt het
  -- ook niets. Beter dan een verzonnen standaard die als norm gaat gelden.
  drempel_eenmalig_pct REAL,
  drempel_terugkerend_pct REAL,
  bijgewerkt_op TEXT,
  bijgewerkt_door TEXT
);
INSERT INTO bedrijfsinstellingen (id) VALUES (1);
