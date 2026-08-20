-- Projecten kunnen concept of definitief zijn — een label, geen slot: het
-- verandert niets aan wat bewerkbaar is, het maakt in de lijst alleen
-- zichtbaar welke doorrekening nog rijpt en welke rond is.
ALTER TABLE projecten ADD COLUMN status TEXT NOT NULL DEFAULT 'concept';
