-- Een winkelaantal heeft twee datums: wanneer je het invoerde (gemeten_op,
-- audit-spoor) en vanaf wanneer het gold (geldig_vanaf, de inhoudelijke
-- datum). Alleen met die tweede is de omzet per winkel over de historie
-- eerlijk te berekenen: anders wordt 2024 gedeeld door het winkelaantal van
-- vandaag en verdwijnt juist het effect dat zichtbaar moet worden.
ALTER TABLE winkelaantal_historie ADD COLUMN geldig_vanaf TEXT;

UPDATE winkelaantal_historie
   SET geldig_vanaf = date(gemeten_op)
 WHERE geldig_vanaf IS NULL;

CREATE INDEX IF NOT EXISTS ix_winkelhist_geldig ON winkelaantal_historie(
  retailer_id, merk, land, banner, geldig_vanaf);
