-- Vanaf hoeveel lege periodes een winkel "let op" is en vanaf hoeveel
-- "gestopt" — per retailer instelbaar.
--
-- Deze twee getallen stonden vast op 1 en 2. Die keuze is geredeneerd in
-- MAANDEN (ICI: één lege maand bij een langzaamloper is ruis, twee is een
-- signaal), maar geprogrammeerd in PERIODES. Etos levert weken, en daar is
-- twee lege weken helemaal niets: op de echte Etos-export leverde dat 363
-- "gestopte" winkel/merk-regels op — een lijst die je aanleert het scherm te
-- negeren.
--
-- Geen standaard per periodetype in het schema: de retailer bepaalt zelf wat
-- bij zijn ritme past, en een verzonnen getal zou als norm gaan gelden.
-- Zonder rij geldt de oude vaste waarde, zodat bestaande installaties
-- ongewijzigd blijven rekenen totdat iemand het bewust instelt.
CREATE TABLE winkelsignaal_drempels (
  retailer_id TEXT PRIMARY KEY REFERENCES retailers(id),
  letop_vanaf INTEGER NOT NULL,
  gestopt_vanaf INTEGER NOT NULL,
  bijgewerkt_op TEXT,
  bijgewerkt_door TEXT,
  CHECK (letop_vanaf >= 1),
  CHECK (gestopt_vanaf >= letop_vanaf)
);
