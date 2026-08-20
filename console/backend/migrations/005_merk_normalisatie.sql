-- Merknamen gelijktrekken in wat er al staat.
--
-- Vanaf nu normaliseert engine/importer.py elk feit bij het inlezen (zie
-- engine/merken.py), maar rijen die er al staan houden hun oude schrijfwijze.
-- Zonder deze migratie blijven DEPEND en DEPEND GEL IQ naast elkaar bestaan
-- tot elk bestand opnieuw is ingelezen — twee filterchips, twee regels in de
-- YTD-tabel, en geen vergelijking tussen Kruidvat en ICI.
--
-- Let op de volgorde: eerst de rijen samenvoegen die na het hernoemen op
-- dezelfde sleutel zouden uitkomen, dan pas hernoemen. Andersom loopt de
-- UPDATE op een UNIQUE-constraint, of ontstaan er twee rijen met dezelfde
-- natuurlijke sleutel die het dashboard bij elkaar optelt.

-- 1. Feiten. De sleutel is (merk, land, banner, winkel_id, artikel_ean,
--    periode). Botsen twee rijen na het hernoemen, dan hoort hun omzet bij
--    elkaar opgeteld te worden: het is hetzelfde merk in dezelfde week.
UPDATE sellout_facts
   SET volume = volume + COALESCE((
         SELECT SUM(b.volume) FROM sellout_facts b
          WHERE b.retailer_id = sellout_facts.retailer_id
            AND b.merk = 'DEPEND GEL IQ'
            AND COALESCE(b.land,'') = COALESCE(sellout_facts.land,'')
            AND COALESCE(b.banner,'') = COALESCE(sellout_facts.banner,'')
            AND COALESCE(b.winkel_id,'') = COALESCE(sellout_facts.winkel_id,'')
            AND COALESCE(b.artikel_ean,'') = COALESCE(sellout_facts.artikel_ean,'')
            AND b.periode = sellout_facts.periode), 0),
       omzet = omzet + COALESCE((
         SELECT SUM(b.omzet) FROM sellout_facts b
          WHERE b.retailer_id = sellout_facts.retailer_id
            AND b.merk = 'DEPEND GEL IQ'
            AND COALESCE(b.land,'') = COALESCE(sellout_facts.land,'')
            AND COALESCE(b.banner,'') = COALESCE(sellout_facts.banner,'')
            AND COALESCE(b.winkel_id,'') = COALESCE(sellout_facts.winkel_id,'')
            AND COALESCE(b.artikel_ean,'') = COALESCE(sellout_facts.artikel_ean,'')
            AND b.periode = sellout_facts.periode), 0)
 WHERE merk = 'DEPEND';

DELETE FROM sellout_facts
 WHERE merk = 'DEPEND GEL IQ'
   AND EXISTS (SELECT 1 FROM sellout_facts a
                WHERE a.retailer_id = sellout_facts.retailer_id
                  AND a.merk = 'DEPEND'
                  AND COALESCE(a.land,'') = COALESCE(sellout_facts.land,'')
                  AND COALESCE(a.banner,'') = COALESCE(sellout_facts.banner,'')
                  AND COALESCE(a.winkel_id,'') = COALESCE(sellout_facts.winkel_id,'')
                  AND COALESCE(a.artikel_ean,'') = COALESCE(sellout_facts.artikel_ean,'')
                  AND a.periode = sellout_facts.periode);

UPDATE sellout_facts SET merk = 'DEPEND' WHERE merk = 'DEPEND GEL IQ';

-- 2. Instellingen: UNIQUE (retailer_id, merk, land, banner). Staat er voor
--    dezelfde scope al een DEPEND-rij, dan wint het grootste winkelaantal en
--    het ingevulde target — weggooien wat iemand heeft ingevuld is erger dan
--    een waarde die iets te hoog staat.
UPDATE retailer_settings
   SET aantal_winkels = MAX(COALESCE(aantal_winkels, 0), COALESCE((
         SELECT b.aantal_winkels FROM retailer_settings b
          WHERE b.retailer_id = retailer_settings.retailer_id
            AND b.merk = 'DEPEND GEL IQ'
            AND b.land = retailer_settings.land
            AND COALESCE(b.banner,'') = COALESCE(retailer_settings.banner,'')), 0)),
       target_per_winkel = COALESCE(target_per_winkel, (
         SELECT b.target_per_winkel FROM retailer_settings b
          WHERE b.retailer_id = retailer_settings.retailer_id
            AND b.merk = 'DEPEND GEL IQ'
            AND b.land = retailer_settings.land
            AND COALESCE(b.banner,'') = COALESCE(retailer_settings.banner,'')))
 WHERE merk = 'DEPEND';

DELETE FROM retailer_settings
 WHERE merk = 'DEPEND GEL IQ'
   AND EXISTS (SELECT 1 FROM retailer_settings a
                WHERE a.retailer_id = retailer_settings.retailer_id
                  AND a.merk = 'DEPEND'
                  AND a.land = retailer_settings.land
                  AND COALESCE(a.banner,'') = COALESCE(retailer_settings.banner,''));

UPDATE retailer_settings SET merk = 'DEPEND' WHERE merk = 'DEPEND GEL IQ';

-- 3. Rotatietargets: PRIMARY KEY (retailer_id, merk). Bestaat DEPEND al, dan
--    blijft die staan.
DELETE FROM rotatie_targets
 WHERE merk = 'DEPEND GEL IQ'
   AND EXISTS (SELECT 1 FROM rotatie_targets a
                WHERE a.retailer_id = rotatie_targets.retailer_id
                  AND a.merk = 'DEPEND');

UPDATE rotatie_targets SET merk = 'DEPEND' WHERE merk = 'DEPEND GEL IQ';

-- 4. Bevestigde promoties: UNIQUE (retailer_id, merk, land, banner, periode).
--    Is dezelfde periode al onder DEPEND bevestigd, dan is die bevestiging
--    leidend en vervalt de dubbele.
DELETE FROM promo_confirmations
 WHERE merk = 'DEPEND GEL IQ'
   AND EXISTS (SELECT 1 FROM promo_confirmations a
                WHERE a.retailer_id = promo_confirmations.retailer_id
                  AND a.merk = 'DEPEND'
                  AND a.land = promo_confirmations.land
                  AND COALESCE(a.banner,'') = COALESCE(promo_confirmations.banner,'')
                  AND a.periode = promo_confirmations.periode);

UPDATE promo_confirmations SET merk = 'DEPEND' WHERE merk = 'DEPEND GEL IQ';

-- 5. Winkelaantalhistorie: geen UNIQUE, dus hernoemen volstaat. Twee metingen
--    op dezelfde datum zijn niet erg; de analyse pakt per scope de laatste.
UPDATE winkelaantal_historie SET merk = 'DEPEND' WHERE merk = 'DEPEND GEL IQ';
