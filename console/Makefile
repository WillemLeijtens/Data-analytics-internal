.PHONY: dev api web seed test build

# Backend + frontend samen (twee processen; stop met Ctrl+C)
dev:
	$(MAKE) -j2 api web

api:
	cd backend && pip install -q -r requirements.txt && \
	python -m uvicorn main:app --reload --port 8000

web:
	cd frontend && npm install --silent && npm run dev

# Voorbeelddata via de ECHTE import-pipeline (bewijst de parsers).
seed:
	cd backend && python seed.py

test:
	cd backend && python -m pytest tests/ -q

build:
	cd frontend && npm install --silent && npm run build
