# Retailer Console — één image dat zowel de API als de gebouwde frontend
# serveert. De frontend wordt in een aparte stage gebouwd zodat Node niet
# in het runtime-image belandt.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /srv

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY profiles/ profiles/
COPY seed/ seed/
COPY --from=web /web/dist backend/static

ENV CONSOLE_DB=/srv/data/console.db
EXPOSE 8000

# Docker/compose zien zelf wanneer de app echt stuk is (database incluis).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD \
  python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:8000/healthz', timeout=4); sys.exit(0 if r.status==200 else 1)"

WORKDIR /srv/backend
# --proxy-headers: achter de gateway kloppen scheme/host/client-ip in logs.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
