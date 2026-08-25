// Contrast van het palet meten — geen schatting, gewoon de WCAG-formule.
//
// Draai: node contrast.mjs
// Leest src/ds/theme.css, dus na een kleurwijziging klopt de uitkomst
// vanzelf. Alles onder 4,5 is te licht voor kleine tekst; voor vlakken,
// stippen en grafieklijnen is 3,0 genoeg.

import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./src/ds/theme.css", import.meta.url), "utf8");

/** Alle `--naam: #RRGGBB` binnen één selectorblok. */
function tokens(selector) {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`selector niet gevonden: ${selector}`);
  const blok = css.slice(css.indexOf("{", start), css.indexOf("}", start));
  const uit = {};
  for (const m of blok.matchAll(/--([\w-]+):\s*(#[0-9A-Fa-f]{6})/g)) uit[m[1]] = m[2];
  return uit;
}

function lum(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

// Drie soorten gebruik, drie normen.
//
//   TEKST   kleine tekst -> 4,5:1 tegen de ondergrond (WCAG 1.4.3).
//   UI      stippen, randen, iconen -> 3,0:1 (WCAG 1.4.11).
//   REEKS   grafieklijnen en -balken. Die moeten vooral van ELKAAR te
//           onderscheiden zijn; ze staan met een legenda en waardelabels in
//           beeld. De achtergrondverhouding wordt gemeld, niet afgekeurd —
//           anders zou het merkpalet uit de handoff hier "zakken" terwijl
//           het precies doet waarvoor het gekozen is.
const TEKST = ["t-fg", "t-fg2", "t-meta", "pos-text", "neg-text", "warn-text"];
const UI = ["t-fg3", "pos", "neg", "warn"];
const REEKS = ["c-y1", "c-y2", "c-y3", "cat1", "cat2", "cat3", "cat4", "cat5",
  "cat6", "cat7", "cat8", "cat9", "cat10", "accent"];

const cat = tokens(":root {\n  --cat1");
let gezakt = 0;

for (const [naam, sel] of [["licht", 'html[data-theme="light"]'], ["donker", 'html[data-theme="dark"]']]) {
  const t = { ...cat, ...tokens(sel) };
  const kaart = t["t-card"], pagina = t["t-bg"];
  console.log(`\n${naam.toUpperCase()} — op kaart ${kaart} / pagina ${pagina}`);
  // De sidebar is een EIGEN ondergrond, niet de kaart of de pagina. Die
  // stond hier eerst niet in, en zo kon de menutekst maandenlang op 2,78:1
  // staan zonder dat deze tool iets meldde: het menu-item erfde de
  // metadata-kleur, die alleen tegen de lichte pagina getoetst werd.
  const zijbalk = t["t-sidebar"];
  for (const sleutel of ["t-sidebar-fg", "t-sidebar-fg2"]) {
    const kleur = t[sleutel];
    if (!kleur) continue;
    const a = ratio(kleur, zijbalk);
    if (a < 4.5) gezakt++;
    console.log(`  ${a >= 4.5 ? "ok  " : "ZAKT"} --${sleutel.padEnd(9)} ${kleur}  ` +
      `${a.toFixed(2)} op sidebar ${zijbalk}  (tekst, norm 4.5)`);
  }
  for (const [groep, norm, label] of [[TEKST, 4.5, "tekst"], [UI, 3.0, "ui"], [REEKS, 0, "reeks"]]) {
    for (const sleutel of groep) {
      const kleur = t[sleutel];
      if (!kleur) continue;
      const a = ratio(kleur, kaart), b = ratio(kleur, pagina);
      const ok = norm === 0 || Math.min(a, b) >= norm;
      if (!ok) gezakt++;
      const merk = norm === 0 ? "    " : ok ? "ok  " : "ZAKT";
      console.log(`  ${merk} --${sleutel.padEnd(9)} ${kleur}  ${a.toFixed(2)} / ${b.toFixed(2)}` +
        (norm ? `  (${label}, norm ${norm.toFixed(1)})` : "  (reeks — informatief)"));
    }
  }
}

// Reekskleuren onderling. NIET met de contrastverhouding: die kijkt alleen
// naar helderheid, en blauw en oranje van gelijke helderheid zijn prima uit
// elkaar te houden. Perceptuele afstand in OKLab is wat hier telt.
function oklab(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const f = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const [R, G, B] = [f(r), f(g), f(b)];
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s2 = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [
    0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s2,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s2,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s2,
  ];
}
const afstand = (a, b) => {
  const [x, y] = [oklab(a), oklab(b)];
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
};

const alle = { ...cat, ...tokens('html[data-theme="dark"]') };
const JAREN = REEKS.filter((k) => k.startsWith("c-y"));
const CATS = REEKS.filter((k) => k.startsWith("cat"));

// Alleen kleuren die in DEZELFDE grafiek naast elkaar staan vergelijken:
// jaren onderling, categorieen onderling, en het accent tegen allebei —
// die targetlijn ligt over de reeksen heen.
function dichtbij(groep, label) {
  const uit = [];
  for (const a of groep) for (const b of groep) {
    if (a >= b || !alle[a] || !alle[b]) continue;
    const d = afstand(alle[a], alle[b]);
    if (d < 0.1) uit.push(`${a}/${b} ${d.toFixed(3)}`);
  }
  console.log(uit.length
    ? `  ${label}: ${uit.join(", ")}`
    : `  ${label}: alle paren >= 0,10 — goed uit elkaar te houden`);
}
console.log("\nOnderling verschil van reekskleuren (OKLab, <0,10 is lastig)");
dichtbij(JAREN, "jaren      ");
dichtbij(CATS, "categorieen");
// Het accent ligt als targetlijn over de reeksen heen, dus alleen dat paar
// telt hier — niet de reeksen onderling nog een keer.
{
  const bij = [...JAREN, ...CATS]
    .map((k) => [k, afstand(alle["accent"], alle[k])])
    .filter(([, d]) => d < 0.1)
    .map(([k, d]) => `accent/${k} ${d.toFixed(3)}`);
  console.log(bij.length
    ? `  accent     : ${bij.join(", ")}`
    : "  accent     : ligt ver genoeg van elke reeks");
}

console.log(gezakt ? `\n${gezakt} token(s) onder de norm.` : "\nTekst en UI halen de norm.");
process.exit(gezakt ? 1 : 0);
