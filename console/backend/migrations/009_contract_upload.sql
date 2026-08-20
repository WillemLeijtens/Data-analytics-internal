-- SharePoint-koppeling vervalt: contracten worden voortaan als PDF
-- geüpload en door Claude geanalyseerd in plaats van uit een gekoppelde
-- map gesynchroniseerd.
DROP TABLE sharepoint_links;

ALTER TABLE contract_documents ADD COLUMN conclusie TEXT;
ALTER TABLE contract_documents ADD COLUMN condities TEXT;
ALTER TABLE contract_documents ADD COLUMN bestandsnaam TEXT;
ALTER TABLE contract_documents ADD COLUMN geupload_op TEXT;
ALTER TABLE contract_documents ADD COLUMN geupload_door TEXT;
