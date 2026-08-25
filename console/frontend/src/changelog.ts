/** Releasenotes: wat er is toegevoegd of veranderd, in mensentaal — niet de
 *  commitgeschiedenis. Nieuwste bovenaan. Voeg bij een nieuwe, voor de
 *  gebruiker merkbare wijziging een entry toe; kleine interne opruimacties
 *  of testwerk horen hier niet in. */
export type ChangelogEntry = { datum: string; titel: string; tekst: string };

export const CHANGELOG: ChangelogEntry[] = [
  { datum: "2026-08-25", titel: "Categorieën combineren in \"Omzet per winkel over tijd\"",
    tekst: "Levert Etos een Class-kolom in de export, dan is er nu een "
      + "\"Categorie\"-stand in de grafiek \"Omzet per winkel over tijd\": "
      + "kies zelf welke categorieën samen één lijn vormen (bijv. Shampoo + "
      + "Conditioners tot \"Wash & Care\") en zie het winkelaantal — het "
      + "aantal unieke winkels met omzet — voor die combinatie over tijd. "
      + "De merk/land/formule-filters bovenaan blijven gewoon van "
      + "toepassing; categorie is puur lokaal in deze ene grafiek." },
  { datum: "2026-08-24", titel: "Changelog",
    tekst: "Dit overzicht, onderaan het menu — zodat nieuwe functies en fixes "
      + "terug te vinden zijn zonder in de code te hoeven kijken." },
  { datum: "2026-08-24", titel: "On counter-moment per artikel",
    tekst: "Nieuwe kolom in de artikelanalyse: de eerste periode waarin voor "
      + "dat artikel omzet gemeten is. Staat er \"≤\" bij, dan valt die eerste "
      + "meting samen met de start van de aanlevering van het merk — dan is "
      + "het een ondergrens, geen introductiedatum." },
  { datum: "2026-08-24", titel: "Fix: dubbele omzet bij Etos na de overstap naar winkelniveau",
    tekst: "Weken die zowel in de oude (artikelniveau) als de nieuwe "
      + "(winkelniveau) Etos-export zaten, telden dubbel — tot ruim 56% "
      + "verschil op de KPI-kaarten. Hersteld, met een opruimstap voor wat "
      + "al in de database stond." },
  { datum: "2026-08-24", titel: "Fix: Etos-import weigerde bij een vergelijkende Time-scope",
    tekst: "Een export met een Time-scope die twee losse periodes vergelijkt "
      + "gebruikt de kolomnamen \"Sales € Focus\"/\"Units Focus\" in plaats "
      + "van \"TY\" — de import accepteert dat nu ook." },
  { datum: "2026-08-24", titel: "Fix: artikel niet meer onterecht als NIEUW gemarkeerd",
    tekst: "Een artikel dat vorig jaar pas later op gang kwam (bijv. vanaf "
      + "week 40) kreeg het label NIEUW, omdat alleen naar hetzelfde venster "
      + "als dit jaar gekeken werd. De toets kijkt nu naar het hele vorige jaar." },
  { datum: "2026-08-24", titel: "Week-op-week ontwikkeling op de KPI-kaarten",
    tekst: "Omzet, Volume en Omzet per winkel tonen nu de ontwikkeling t.o.v. "
      + "de vorige periode — groen bij stijging, rood bij daling." },
  { datum: "2026-08-24", titel: "Uitleg bij niveau-labels als SCHATTING",
    tekst: "Labels als SCHATTING, OP MAANDNIVEAU en OP MERKNIVEAU hebben nu "
      + "een info-icoon dat uitlegt wat ze betekenen en waar het cijfer "
      + "vandaan komt." },
  { datum: "2026-08-24", titel: "Ritme-uitleg bij stille winkels",
    tekst: "Bij \"ritme N\" in de stille-winkels-tabel staat nu een "
      + "info-icoon met uitleg: hoe vaak deze winkel normaal verkoopt, en "
      + "hoe dat de stilte-drempel meebepaalt." },
  { datum: "2026-08-24", titel: "Ritme-bewuste detectie van stille winkels",
    tekst: "Een winkel telt pas als gestopt of \"let op\" als de stilte ook "
      + "afwijkt van zijn eigen verkoopritme — een winkel die om de drie "
      + "weken verkoopt is na zes stille weken niet gestopt. Gemist bedrag "
      + "wordt geschat als vorig jaar ontbreekt, met een sparkline per rij." },
  { datum: "2026-08-23", titel: "Vinkjes bij promotiesuggesties slaan zichzelf op",
    tekst: "Geen aparte opslaanknop meer nodig. Het omzeteffect-overzicht "
      + "staat voortaan op het dashboard in plaats van de promotiepagina." },
  { datum: "2026-08-23", titel: "Promotiedetectie grondig herzien",
    tekst: "Vijf statistische gebreken hersteld in de actiedetectie: een "
      + "eerlijkere referentieperiode, artikelniveau-detectie naast "
      + "assortimentsniveau, een zekerheidsscore (1/5 t/m 5/5) en één "
      + "definitie van \"normale\" omzet voor zowel de basislijn als de "
      + "getoonde gemiddelden." },
  { datum: "2026-08-21", titel: "Drempels voor stille winkels instelbaar",
    tekst: "Per retailer in te stellen wanneer een winkel \"let op\" of "
      + "\"gestopt\" wordt gemeld (Instellingen → Stille winkels)." },
  { datum: "2026-08-21", titel: "Etos op winkelniveau",
    tekst: "De Etos-parser leest nu ook de winkelniveau-export, met "
      + "dezelfde winkelanalyse als bij ICI Paris. Winkelaantallen in "
      + "Instellingen vullen zich automatisch uit de import." },
  { datum: "2026-08-21", titel: "ICI Paris XL BE als eigen retailer",
    tekst: "België krijgt een eigen tab, met automatische routering tussen "
      + "NL en BE op basis van het winkelnummer." },
  { datum: "2026-08-21", titel: "Doelstellingen: winkelaantallen per artikel",
    tekst: "Winkelaantallen instelbaar per merk óf per artikel, voor "
      + "retailers die dat detailniveau leveren." },
  { datum: "2026-08-21", titel: "Drempelmarges en marge% per product",
    tekst: "In de projectcalculator: winstmarge% per product, met een rode "
      + "waarschuwing zodra de marge onder de ingestelde drempel "
      + "(Instellingen → Bedrijfsnormen) zakt. Projecten zijn nu ook aan te "
      + "merken als one-shot of doorlopend." },
  { datum: "2026-08-21", titel: "Datagaten en mijlpalen op de trendgrafiek",
    tekst: "Ontbrekende aanlevering wordt gemeld bij het betrokken merk. "
      + "Mijlpalen (bijv. een listing-start) zijn te plaatsen door op de "
      + "trendgrafiek te klikken." },
];
