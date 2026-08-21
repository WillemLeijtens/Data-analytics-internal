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

// Kleuren komen uit het palet in ds/theme.css, niet uit losse hexwaarden:
// zo blijft er één plek waar het beheerd wordt, en volgt een grafiek vanzelf
// het thema. `var(--catN)` werkt ook in SVG-attributen (fill/stroke).
//
// Merken houden hun kleur in beide thema's — de categoriekleuren zijn
// bewust thema-onafhankelijk, anders "verspringt" een merk bij het wisselen.
export const BRAND_COLORS: Record<string, string> = {
  TWEEZERMAN: "var(--cat1)",
  ALESSANDRO: "var(--cat5)",
  DEPEND: "var(--cat6)",
  "OLIVIA GARDEN": "var(--cat2)",
};

// Jaren: apart van de categoriekleuren en WEL per thema, want ze moeten
// onderling contrasteren op een lichte én een donkere ondergrond.
// Volgorde: huidig jaar, -1, -2.
export const YEAR_COLORS = ["var(--c-y3)", "var(--c-y2)", "var(--c-y1)"];

// Merken die niet vast toegewezen zijn, krijgen een stabiele kleur uit de
// rest van het palet: dezelfde naam geeft altijd dezelfde kleur, over
// schermen en sessies heen.
const RESERVE_COLORS = [
  "var(--cat3)", "var(--cat4)", "var(--cat7)",
  "var(--cat8)", "var(--cat10)", "var(--cat9)",
];

export function merkKleur(merk: string | null | undefined): string {
  if (!merk) return "var(--t-fg3)";
  if (BRAND_COLORS[merk]) return BRAND_COLORS[merk];
  let h = 0;
  for (const teken of merk) h = (h * 31 + teken.charCodeAt(0)) >>> 0;
  return RESERVE_COLORS[h % RESERVE_COLORS.length];
}

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

// Een meerjarig gat in de aanlevering: een jaar dat tussen twee leveringen
// helemaal ontbreekt. Of dat klopt (het merk lag er dat jaar niet) of niet
// (een bestand is nooit ingelezen) staat niet in de data — dat oordeel komt
// van een mens, en daarom hoort het bij het gat.
export type Datagat = {
  merk: string | null; land: string | null; banner: string | null;
  van_jaar: number; tot_jaar: number; jaren_met_data: number[]; tekst: string;
  oordeel: "klopt" | "klopt_niet" | null;
  toelichting: string | null;
  beoordeeld_door: string | null; beoordeeld_op: string | null;
};

export type Milestone = {
  id: number; jaar: number; periode_nummer: number; tekst: string;
  aangemaakt_op: string; aangemaakt_door: string | null;
};
