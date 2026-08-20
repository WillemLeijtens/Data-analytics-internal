// Thema-instelling: systeem, licht of donker.
//
// De keuze staat in localStorage onder `bl-theme` en overleeft dus het
// sluiten van de browser en een volgende inlog. Er is bewust GEEN
// serverkant: het is een voorkeur van dit apparaat, niet van de data — en
// een voorkeur die pas na een API-antwoord toegepast wordt, laat de pagina
// eerst in het verkeerde thema opflitsen.
//
// Het opstartscript in index.html doet exact hetzelfde als `pasToe()`
// hieronder, maar dan vóór de eerste verf. Wijzig je hier iets, wijzig het
// daar dan mee.

export type ThemaModus = "system" | "light" | "dark";
export type Thema = "light" | "dark";

export const THEMA_SLEUTEL = "bl-theme";

const DONKER = "(prefers-color-scheme: dark)";

export function leesModus(): ThemaModus {
  try {
    const opgeslagen = localStorage.getItem(THEMA_SLEUTEL);
    if (opgeslagen === "light" || opgeslagen === "dark" || opgeslagen === "system") {
      return opgeslagen;
    }
  } catch {
    // localStorage kan geblokkeerd zijn (privémodus, strenge instelling).
    // Dan werkt het thema gewoon per sessie in plaats van te breken.
  }
  return "system";
}

export function bepaalThema(modus: ThemaModus): Thema {
  if (modus === "system") {
    return window.matchMedia?.(DONKER).matches ? "dark" : "light";
  }
  return modus;
}

export function pasToe(modus: ThemaModus): Thema {
  const thema = bepaalThema(modus);
  document.documentElement.dataset.theme = thema;
  return thema;
}

export function bewaarModus(modus: ThemaModus) {
  try {
    localStorage.setItem(THEMA_SLEUTEL, modus);
  } catch {
    /* zie leesModus */
  }
}

/** Roep de callback aan als het SYSTEEM van licht naar donker wisselt.
 *  Geeft een opruimfunctie terug. Alleen zinvol in modus 'system'. */
export function volgSysteem(bij: () => void): () => void {
  const mq = window.matchMedia?.(DONKER);
  if (!mq) return () => {};
  mq.addEventListener("change", bij);
  return () => mq.removeEventListener("change", bij);
}
