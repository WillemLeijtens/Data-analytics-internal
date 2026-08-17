// Thin API client + shared types for the Retailer Console backend.

export type Capabilities = {
  periode: "week" | "maand";
  merk: boolean; artikel: boolean; winkel: boolean; banner: boolean; land: boolean;
};

export type Resolution = { level_used: Record<string, string>; labels: string[] };

export type Signaal = "green" | "orange" | "red" | "grey";

export type RetailerCard = {
  id: string; naam: string; aangesloten: boolean;
  profiel: { versie: number; status: string } | null;
  capabilities: Capabilities | null;
  signalen: {
    assortiment: { signaal: Signaal; tekst: string };
    distributie: { signaal: Signaal; tekst: string };
    contract: { signaal: Signaal; tekst: string };
    data: { signaal: Signaal; tekst: string };
    composiet: Signaal; context: string;
  };
};

export const BRAND_COLORS: Record<string, string> = {
  TWEEZERMAN: "oklch(0.45 0.1 285)",
  ALESSANDRO: "oklch(0.58 0.13 27)",
  "DEPEND GEL IQ": "oklch(0.66 0.12 80)",
  "OLIVIA GARDEN": "oklch(0.52 0.1 160)",
};
export const YEAR_COLORS = ["#0E323B", "#7E8D92", "#BAC3C8"]; // current, -1, -2

export const fmtEur = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : "€ " + v.toLocaleString("nl-NL", { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const fmtNum = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("nl-NL");

export async function apiGet<T = any>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function apiSend<T = any>(path: string, method: string, body?: any): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
