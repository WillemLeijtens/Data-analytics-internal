-- ICI Paris XL België als eigen retailer.
--
-- Een aparte aanlevering met een eigen winkelbestand (Belgische filialen,
-- eigen winkelnummers) en eigen cijfers. Als één retailer met de Nederlandse
-- data zouden de winkelaantallen en de omzet per winkel over twee landen
-- opgeteld worden — precies het soort optelling waar de rest van de app zich
-- juist tegen verzet.
--
-- aangesloten blijft 0 tot het profiel geladen is; seed.bootstrap() zet de
-- vlag zodra de parser er staat.
INSERT OR IGNORE INTO retailers (id, naam, aangesloten)
VALUES ('ici-paris-be', 'ICI Paris XL BE', 0);
