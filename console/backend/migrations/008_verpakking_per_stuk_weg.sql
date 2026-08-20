-- Verpakkingskosten per stuk verwarde de eenmalige/terugkerende marge
-- (kostprijs + verpakking konden samen de verkoopprijs opeten zonder dat
-- dat ergens zichtbaar werd). Verpakking loopt voortaan uitsluitend via de
-- kostenregel "Verpakkingskosten (totaal)".
ALTER TABLE project_producten DROP COLUMN verpakking_per_stuk;
