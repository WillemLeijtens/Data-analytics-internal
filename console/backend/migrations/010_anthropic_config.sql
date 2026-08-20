-- Eén rij: de Anthropic-sleutel voor contractanalyse kan voortaan direct in
-- de app gezet worden (met live statustest), i.p.v. alleen via .env op de
-- droplet. DB-waarde wint van de omgevingsvariabele; leeg = terugval op env.
CREATE TABLE anthropic_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  api_key TEXT,
  bijgewerkt_op TEXT,
  bijgewerkt_door TEXT,
  laatst_getest_op TEXT,
  laatst_status TEXT CHECK (laatst_status IN ('ok','fout')),
  laatst_melding TEXT
);
INSERT INTO anthropic_config (id) VALUES (1);
