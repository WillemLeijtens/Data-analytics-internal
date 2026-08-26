/** Releasenotes: wat er is toegevoegd of veranderd, in mensentaal — niet de
 *  commitgeschiedenis. Nieuwste bovenaan. Voeg bij een nieuwe, voor de
 *  gebruiker merkbare wijziging een entry toe; kleine interne opruimacties
 *  of testwerk horen hier niet in. */
export type ChangelogEntry = { datum: string; titel: string; tekst: string };

export const CHANGELOG: ChangelogEntry[] = [
  { datum: "2026-08-26", titel: "Targets ook op de land- en formule-uitsplitsing",
    tekst: "Zet je de KPI-kaarten op \"Per land\" of \"Per formule\", dan staat "
      + "het target nu ook achter die regels — opgeteld uit de merken die daar "
      + "liggen, met de targets van dát land uit Instellingen (BE € 120 + € 70 "
      + "= € 190). Hover over het bedrag voor de opbouw. Op de merkregel wordt "
      + "een target dat per land verschilt voortaan naar winkelaantal gewogen: "
      + "1205 NL-winkels à € 50 en 187 BE-winkels à € 120 geeft € 59,40, want "
      + "die regel deelt de omzet van beide landen door alle 1392 winkels. "
      + "Daarvoor gold het hoogste getal, waarmee 87% van het winkelbestand "
      + "langs de Belgische lat lag." },
  { datum: "2026-08-26", titel: "Winkeltargets zichtbaar: opgeteld en in de grafiek",
    tekst: "De targets uit Instellingen → Doelstellingen stonden alleen per merk "
      + "achter een regel. Nu ligt het target ook als streepjeslijn over "
      + "\"Omzet per winkel over tijd\" — op Totaal opgeteld over de merken die "
      + "de filters overlaten, want één filiaal voert die merken naast elkaar. "
      + "Per week zie je in de tooltip of de lat gehaald is. Op de kaart "
      + "\"Omzet per winkel\" staat een schuifje \"Tel op\" (standaard aan) dat de "
      + "getoonde omzetten en targets bij elkaar optelt. Merken zonder "
      + "ingesteld target worden erbij gemeld: een som over de helft van het "
      + "assortiment is geen norm om aan af te meten." },
  { datum: "2026-08-26", titel: "Rotatie rekent over de huidige maand",
    tekst: "De rotatie in de assortimentsanalyse middelde over het hele jaar. "
      + "Een artikel dat in het voorjaar goed liep en sinds de zomer stilstaat, "
      + "hield daardoor een net gemiddelde en viel nergens op. De kolom heet nu "
      + "\"Rotatie (huidige maand)\" en rekent met de weken die van die maand "
      + "geleverd zijn — twee geleverde weken betekent delen door twee, niet "
      + "door 4,33. Onder elke rotatie staat waar hij op rust: hoeveel stuks in "
      + "hoeveel weken, door hoeveel winkels, en of dat winkelaantal per artikel "
      + "is ingesteld, het merkaantal is, of uit de data geteld. Nul verkoop in "
      + "de maand heet voortaan \"Geen verkoop deze maand\"; bij minder dan twee "
      + "geleverde weken wordt het oordeel uitgesteld." },
  { datum: "2026-08-26", titel: "Projectcalculator: geen dubbele tegel, en marge én omzet uit elkaar",
    tekst: "Bij een one-shot toonde de tegel \"Totaal project\" exact hetzelfde "
      + "bedrag en percentage als de tegel ernaast — er komt immers geen "
      + "doorverkoop bij. Die tegel is nu weg bij een one-shot. Daarnaast stond "
      + "in de opbouw onder de terugkerende tegel \"omzet − kosten\", maar dat "
      + "is de marge niet: die is productmarge − kosten (+ bijdrage). Alle "
      + "regels volgen nu één schrijfwijze: omzet staat als \"op € X omzet\", "
      + "en de marge-opbouw altijd als productmarge − kosten." },
  { datum: "2026-08-25", titel: "Menu weer leesbaar, Conclusie bovenaan",
    tekst: "Elk ingesprongen menu-item kreeg per ongeluk de grijstint van "
      + "gedempte tekst — 2,78:1 in het lichte thema, ver onder de norm — "
      + "waardoor het hele menu eruitzag alsof er niets te klikken viel. "
      + "Werkende items zijn nu duidelijk leesbaar en uitgeschakelde items "
      + "duidelijk zwakker, zodat je het verschil ziet. \"Conclusie\" staat "
      + "nu bovenaan bij Analyses, en de knop \"Opnieuw schrijven\" is "
      + "vervangen door een vraagteken dat uitlegt wanneer de tekst "
      + "vanzelf opnieuw geschreven wordt." },
  { datum: "2026-08-25", titel: "Conclusie per retailer",
    tekst: "Nieuw scherm onder Analyses: wat de cijfers van deze retailer "
      + "zeggen over omzet, assortiment, winkelontwikkeling en promoties, plus "
      + "concrete adviezen. De app berekent eerst zelf de bevindingen — die "
      + "staan onder de tekst, zodat elke zin te herleiden is tot een cijfer — "
      + "en laat Claude daar de samenvatting op schrijven. Noemt de tekst een "
      + "getal dat niet uit de bevindingen komt, dan wordt dat gemeld. Zonder "
      + "Anthropic-sleutel werkt het scherm ook: dan zie je alleen de "
      + "bevindingen. De conclusie werkt zichzelf bij zodra er nieuwe data is." },
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
