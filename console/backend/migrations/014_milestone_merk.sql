-- Een mijlpaal hoort bij een merk: "introductie nieuw item" gaat over één
-- merk, niet over de hele retailer. Zonder merk staat dezelfde markering op
-- elke grafiek, ook als je op een ander merk filtert — en dan verklaart hij
-- een piek die er in die selectie niet is.
--
-- Nullable, want mijlpalen die vóór deze kolom zijn gezet hebben geen merk.
-- Die gelden retailer-breed en blijven dus altijd zichtbaar; nieuwe mijlpalen
-- moeten wél een merk kiezen (afgedwongen in de API, niet hier: SQLite kan
-- geen NOT NULL toevoegen aan een tabel met bestaande NULL-rijen).
ALTER TABLE milestones ADD COLUMN merk TEXT;
