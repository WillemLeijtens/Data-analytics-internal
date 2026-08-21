-- One-shot of doorlopend.
--
-- Een one-shot is één levering: een kerstactie, een eenmalige display. Daar
-- bestaat geen doorverkoop-per-week bij, en elk veld daarover is dan een
-- vraag zonder antwoord — en erger, een getal dat meetelt in een totaal dat
-- niet klopt. Bij een doorlopend project is die doorverkoop juist de kern.
--
-- Standaard 'doorlopend': dat is wat de calculator tot nu toe rekende, dus
-- bestaande projecten blijven precies hetzelfde uitkomen.
ALTER TABLE projecten ADD COLUMN soort TEXT NOT NULL DEFAULT 'doorlopend';
