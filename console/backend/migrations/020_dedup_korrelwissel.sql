-- Dubbeltellingen opruimen die ontstonden bij een KORRELWISSEL.
--
-- Etos stapte over van de artikelniveau-export naar dezelfde Data
-- Grid-widget mét Store-kolommen. De dedup-sleutel van de importer bevat
-- winkel_id, dus dezelfde week van hetzelfde artikel kwam er twee keer in te
-- staan: één regel met winkel_id NULL (oude export) en één per winkel
-- (nieuwe export). Die sleutels botsen nooit, dus niets werd vervangen en
-- elke week die in BEIDE bestanden zat telde dubbel.
--
-- Gemeten op de echte Etos-data: week 32 stond op EUR 52.200 in plaats van
-- EUR 26.100 en week 33 op EUR 22.865, waardoor het dashboard -56,2% meldde
-- terwijl de werkelijke daling -12,4% was. Alles wat op die feiten rust —
-- YTD, trends, omzet per winkel, promotiedetectie — telde even hard mee.
--
-- engine/importer.py voorkomt het voortaan bij het inlezen; deze migratie
-- ruimt op wat er al staat. Weg gaat alleen de GROVE regel (winkel_id NULL)
-- waarvoor dezelfde verkoop óók per winkel bestaat: zelfde retailer, merk,
-- land, banner, artikel en periode. Dat is per definitie dezelfde verkoop,
-- anders geteld — nooit twee echte regels. De winkelregels blijven staan,
-- want die dragen de meeste informatie; artikelniveau-historie van periodes
-- die nooit op winkelniveau geleverd zijn, blijft onaangeroerd.
DELETE FROM sellout_facts
WHERE winkel_id IS NULL
  AND EXISTS (
    SELECT 1 FROM sellout_facts w
    WHERE w.winkel_id IS NOT NULL
      AND w.retailer_id = sellout_facts.retailer_id
      AND w.periode = sellout_facts.periode
      AND COALESCE(w.merk, '') = COALESCE(sellout_facts.merk, '')
      AND COALESCE(w.land, '') = COALESCE(sellout_facts.land, '')
      AND COALESCE(w.banner, '') = COALESCE(sellout_facts.banner, '')
      AND COALESCE(w.artikel_ean, '') = COALESCE(sellout_facts.artikel_ean, '')
  );
