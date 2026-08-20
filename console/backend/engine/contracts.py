"""Contractanalyse: een geüploade PDF wordt uitgelezen en door Claude
samengevat tot looptijd, conclusie en afgesproken condities.

Het signaal (groen/oranje/rood) wordt NIET door het model geraden — dat
blijft, net als voorheen, live herberekend uit `geldig_tot` door
`signals.contract_signal()`. Claude levert alleen de datum, een conclusie-
tekst en de condities; het rekenwerk voor "loopt dit nog" blijft
deterministisch.

Een nieuwe upload vervangt het actuele contract van die retailer, maar het
vorige contract wordt niet weggegooid: het gaat naar
`contract_documenten_historie`, zodat een verkeerde extractie (bv. een
gehallucineerde datum) terug te draaien is en niet stilzwijgend de enige
vastlegging van de vorige, mogelijk correcte afspraken wist.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os

MAX_PDF_PAGINAS = 15
MAX_PROMPT_TEKENS = 40_000
STANDAARD_MODEL = "claude-sonnet-4-5"
# Een retailcontract dat meer dan 15 jaar terug inging of pas over 15 jaar
# afloopt, is voor deze context vrijwel zeker een fout gelezen (of
# gehallucineerde) datum, niet een echte looptijd. Zo'n datum mag dan niet
# ongezien het rode/oranje/groene signaal aansturen.
MAX_JAREN_PLAUSIBEL = 15


def haal_api_key(conn) -> tuple[str | None, str]:
    """DB-sleutel wint van de omgevingsvariabele: zo kan de sleutel via de
    app gezet worden zonder herstart, terwijl .env als terugval blijft
    werken (bv. vlak na een verse deploy, vóórdat iemand inlogt)."""
    row = conn.execute("SELECT api_key FROM anthropic_config WHERE id=1").fetchone()
    db_key = (row["api_key"] or "").strip() if row else ""
    if db_key:
        return db_key, "database"
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key, "omgeving"
    return None, "geen"


def test_sleutel(api_key: str) -> tuple[bool, str]:
    """Een goedkope, niet-tokenverbruikende call om te controleren of de
    sleutel werkt — geen gok op basis van het formaat."""
    import anthropic

    try:
        anthropic.Anthropic(api_key=api_key).models.list(limit=1)
    except anthropic.AuthenticationError:
        return False, "Ongeldige sleutel (authenticatie mislukt)"
    except anthropic.APIError as e:
        return False, f"Test mislukt: {e}"
    return True, "Werkt"


def pdf_tekst(content: bytes) -> str:
    """Tekst uit de eerste pagina's van een PDF. Geen tekst gevonden (bv.
    een gescande, niet-doorzoekbare PDF) levert een lege string — de
    aanroeper meldt dat expliciet in plaats van een lege analyse te
    versturen."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(content))
    except PdfReadError as e:
        raise ValueError(f"kon de PDF niet lezen: {e}") from e
    stukken = []
    for pagina in reader.pages[:MAX_PDF_PAGINAS]:
        stukken.append(pagina.extract_text() or "")
    return "\n".join(stukken).strip()[:MAX_PROMPT_TEKENS]


_PROMPT = """Je krijgt de tekst van een retailcontract. Geef UITSLUITEND \
geldig JSON terug (geen uitleg, geen markdown-hekjes) met exact deze vorm:

{{
  "naam": "korte naam van het document, bv. 'Jaarcontract 2026'",
  "type": "contract | prijslijst | bonusafspraak | overig",
  "geldig_tot": "YYYY-MM-DD of null als er geen einddatum in staat",
  "conclusie": "één zin: loopt dit contract nog of is het verlopen, en \
sinds/tot wanneer",
  "condities": [
    {{"onderwerp": "bv. Betalingstermijn", "afspraak": "wat er precies is \
afgesproken"}}
  ]
}}

Condities zijn afspraken zoals betalingstermijnen, kortingen, COOP- of \
marketinginvesteringen, bonussen, leveringsvoorwaarden — alles wat concreet \
is toegezegd. Laat "condities" leeg ([]) als je niets concreets vindt. \
Vandaag is {vandaag}.

Contracttekst:
---
{tekst}
---"""


def analyseer(conn, tekst: str, vandaag: dt.date | None = None) -> dict:
    """Belt de Claude API en parseert het antwoord. Raise ValueError met een
    Nederlandse melding bij een ontbrekende sleutel, een API-fout of
    onbruikbaar JSON — nooit halve of verzonnen data opslaan."""
    if not tekst.strip():
        raise ValueError(
            "geen tekst gevonden in de PDF — is het een gescand document "
            "zonder doorzoekbare tekst?")
    api_key, _ = haal_api_key(conn)
    if not api_key:
        raise ValueError("contractanalyse is niet geconfigureerd (geen Anthropic API-sleutel)")

    import anthropic

    vandaag = vandaag or dt.date.today()
    client = anthropic.Anthropic(api_key=api_key)
    model = os.environ.get("CONSOLE_CONTRACT_MODEL", "").strip() or STANDAARD_MODEL
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": _PROMPT.format(
                vandaag=vandaag.isoformat(), tekst=tekst)}],
        )
    except anthropic.APIError as e:
        raise ValueError(f"contractanalyse is mislukt: {e}") from e

    ruw = "".join(b.text for b in response.content if b.type == "text").strip()
    ruw = ruw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(ruw)
    except json.JSONDecodeError as e:
        raise ValueError("contractanalyse leverde geen bruikbaar antwoord op") from e

    geldig_tot = data.get("geldig_tot")
    conclusie = str(data.get("conclusie") or "").strip() or None
    if geldig_tot:
        try:
            geldig_tot_datum = dt.date.fromisoformat(geldig_tot)
        except (TypeError, ValueError):
            geldig_tot = None
        else:
            jaren_verschil = abs((geldig_tot_datum - vandaag).days) / 365.25
            if jaren_verschil > MAX_JAREN_PLAUSIBEL:
                # Niet zomaar weggooien: de ruwe waarde blijft zichtbaar in de
                # conclusie zodat een mens 'm kan beoordelen, maar hij mag het
                # automatische signaal niet aansturen — vandaar geldig_tot=None.
                waarschuwing = (f"Let op: de geëxtraheerde einddatum ({geldig_tot}) "
                                f"leek onwaarschijnlijk (meer dan {MAX_JAREN_PLAUSIBEL} "
                                "jaar van vandaag) en is genegeerd voor het signaal — "
                                "controleer het brondocument handmatig.")
                conclusie = f"{conclusie} {waarschuwing}" if conclusie else waarschuwing
                geldig_tot = None

    return {
        "naam": str(data.get("naam") or "Contract")[:200],
        "type": (str(data.get("type")).strip() or None) if data.get("type") else None,
        "geldig_tot": geldig_tot,
        "conclusie": conclusie,
        "condities": [
            {"onderwerp": str(c.get("onderwerp") or "").strip(),
             "afspraak": str(c.get("afspraak") or "").strip()}
            for c in (data.get("condities") or [])
            if isinstance(c, dict) and (c.get("onderwerp") or c.get("afspraak"))
        ],
    }


def verwerk_upload(conn, retailer_id: str, bestandsnaam: str, content: bytes,
                    door: str | None, analyseer_fn=None) -> dict:
    """Tekst → analyse → vervangt het bestaande contract van deze retailer.
    `analyseer_fn` is injecteerbaar zodat tests geen echte API-call doen.
    Standaard wordt de module-functie `analyseer` gebruikt — pas bij het
    aanroepen opgezocht, zodat tests hem via monkeypatch kunnen vervangen."""
    tekst = pdf_tekst(content)
    gevonden = (analyseer_fn or analyseer)(conn, tekst)
    nu = dt.datetime.now().isoformat(timespec="seconds")

    conn.execute(
        "INSERT INTO contract_documenten_historie (retailer_id, naam, type, geldig_tot, "
        "signaal, conclusie, condities, bestandsnaam, geupload_op, geupload_door) "
        "SELECT retailer_id, naam, type, geldig_tot, signaal, conclusie, condities, "
        "bestandsnaam, geupload_op, geupload_door FROM contract_documents WHERE retailer_id=?",
        (retailer_id,))
    conn.execute("DELETE FROM contract_documents WHERE retailer_id=?", (retailer_id,))
    cursor = conn.execute(
        "INSERT INTO contract_documents (retailer_id, naam, type, geldig_tot, signaal, "
        "conclusie, condities, bestandsnaam, geupload_op, geupload_door) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (retailer_id, gevonden["naam"], gevonden["type"], gevonden["geldig_tot"], "grey",
         gevonden["conclusie"], json.dumps(gevonden["condities"]), bestandsnaam, nu, door))
    row = conn.execute(
        "SELECT * FROM contract_documents WHERE id=?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def historie(conn, retailer_id: str) -> list[dict]:
    """Eerder vervangen contracten van deze retailer, nieuwste eerst — puur
    ter inzage/rollback, stuurt nooit het actuele signaal aan."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM contract_documenten_historie WHERE retailer_id=? "
        "ORDER BY vervangen_op DESC", (retailer_id,))]
