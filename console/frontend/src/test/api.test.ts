import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiSend, fmtEur, fmtNum } from "../api";

// apiGet/apiSend zijn het enige kanaal waardoor elke foutmelding in de app
// loopt (upload-fouten, opslaan mislukt, etc.) — een regressie hier breekt
// stil elk foutpad tegelijk, dus dit is de hoogste-waarde plek om te
// borgen dat een niet-ok respons altijd een leesbare Error oplevert.

describe("apiGet", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("geeft de JSON-body terug bij een geslaagde respons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ hallo: "wereld" }),
    }));
    await expect(apiGet("/iets")).resolves.toEqual({ hallo: "wereld" });
  });

  it("gooit een Error met status en body-tekst bij een niet-ok respons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 422, text: async () => "geen geldig XLSX-bestand",
    }));
    await expect(apiGet("/import")).rejects.toThrow("422 geen geldig XLSX-bestand");
  });

  it("roept het juiste pad aan onder /api", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    await apiGet("/kruidvat/dashboard");
    expect(fetchMock).toHaveBeenCalledWith("/api/kruidvat/dashboard");
  });
});

describe("apiSend", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("stuurt JSON mee met het juiste Content-Type bij een gewoon object", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetchMock);
    await apiSend("/projecten/1", "PUT", { naam: "Test" });
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers).toEqual({ "Content-Type": "application/json" });
    expect(opts.body).toBe(JSON.stringify({ naam: "Test" }));
  });

  it("stuurt FormData zonder Content-Type-header (de browser zet de multipart-boundary zelf)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetchMock);
    const fd = new FormData();
    fd.append("file", new Blob(["x"]), "contract.pdf");
    await apiSend("/ici-paris-xl/contract", "POST", fd);
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers).toBeUndefined();
    expect(opts.body).toBe(fd);
  });

  it("gooit een leesbare fout bij een mislukte upload (422)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 422, text: async () => "bestand is groter dan 200 MB",
    }));
    await expect(apiSend("/import", "POST", new FormData()))
      .rejects.toThrow("422 bestand is groter dan 200 MB");
  });
});

describe("fmtEur / fmtNum", () => {
  it("toont een streepje voor null/undefined i.p.v. '€ NaN' of leeg", () => {
    expect(fmtEur(null)).toBe("—");
    expect(fmtEur(undefined)).toBe("—");
    expect(fmtNum(null)).toBe("—");
  });

  it("formatteert bedragen in nl-NL-notatie", () => {
    expect(fmtEur(1234)).toBe("€ 1.234");
    expect(fmtEur(0)).toBe("€ 0");
  });
});
