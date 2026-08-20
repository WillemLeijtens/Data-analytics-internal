-- Een nieuwe contract-upload vervangt het actuele contract, maar het vorige
-- gaat niet verloren: een verkeerde LLM-extractie (bv. een gehallucineerde
-- datum of conditie) was tot nu toe onherstelbaar, want de vervanging was
-- destructief. Deze tabel is puur een archief — de app leest 'm alleen om
-- te tonen, nooit om het huidige signaal op te baseren.
CREATE TABLE contract_documenten_historie (
  id INTEGER PRIMARY KEY,
  retailer_id TEXT NOT NULL REFERENCES retailers(id),
  naam TEXT,
  type TEXT,
  geldig_tot TEXT,
  signaal TEXT,
  conclusie TEXT,
  condities TEXT,
  bestandsnaam TEXT,
  geupload_op TEXT,
  geupload_door TEXT,
  vervangen_op TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_contract_historie_retailer ON contract_documenten_historie(retailer_id, vervangen_op);
