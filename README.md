# Checkboodschappen 🇳🇱

Vergelijk een boodschappenlijst bij Nederlandse supermarkten. De app berekent benodigde verpakkingen en acties, en vergelijkt één winkel met een combinatie van maximaal twee winkels.

**Taal: Nederlands · Regio: Nederland**

[Website](https://checkboodschappen.thenorthsolution-b.workers.dev) · [Roadmap](https://checkboodschappen.thenorthsolution-b.workers.dev/roadmap)

Dutch grocery price comparison for supermarkets in the Netherlands.

## Website ontwikkelen

Vereist Node.js 22.13+ en Python 3.11+. Maak eerst het winkelbestand zoals hieronder beschreven.

```sh
cd public-site
npm ci
npm run build:assets
npm run dev
```

Open http://127.0.0.1:8787. De lokale preview schakelt PrijsProfeet uit; Checkjebon en postcodezoekopdrachten gebruiken wel het netwerk.

## Lokale macOS-app

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
python3 run.py
```

De app opent op een lokale poort en bewaart gegevens in `~/Library/Application Support/BoodschappenWijzer`. Stel deze single-user server niet publiek beschikbaar. Een macOS-bundle bouwen kan met `./scripts/build_macos.sh`.

Ollama kan optioneel zoeknamen voorstellen via `127.0.0.1:11434` en staat standaard uit. Productmatching en hoeveelheidsberekeningen gebruiken vaste regels. De website heeft geen modelafhankelijkheid.

## Vergelijken

- Expliciete hoeveelheden blijven behouden. Zonder hoeveelheid betekent een regel standaard één verpakking; voorstellen voor personen zijn aanpasbaar.
- Stuks en verpakkingen zijn verschillende eenheden. Omrekenen naar gewicht of volume vereist bekende verpakkingsinhoud.
- Onzekere matches en ontbrekende producten blijven zichtbaar. Een onvolledig mandje krijgt een subtotaal.
- Actievoorwaarden en klantenkaartprijzen staan bij de resultaten. Prijzen en voorraad zijn indicatief.
- Winkellocaties komen uit OpenStreetMap. Afstanden en reiskosten zijn schattingen op basis van rechte lijnen.
- Bonnen worden lokaal geëxporteerd naar PDF of PNG. Lange PNG-bonnen worden opgesplitst in een ZIP.

## Tests

```sh
pytest -q
npm --prefix public-site test
```

De tests gebruiken fixtures en onderschepte providerantwoorden. Voor een code-only distributie:

```sh
python3 scripts/build_source_release.py --output output/releases/source
```

De expliciete bestandslijst sluit lokale gegevens, credentials, dependencies en onderzoeksoutput uit.

## Data en licenties

Lijsten worden in de browser opgeslagen; productzoekwoorden worden verwerkt door de prijsbronnen. Zie de privacyverklaring op de website voor opslag en externe diensten.

Applicatiecode: [MIT](LICENSE). Prijsgegevens van Checkjebon en PrijsProfeet behouden hun eigen gebruiksvoorwaarden. Winkellocaties vallen onder OpenStreetMap ODbL. Builds bevatten de toepasselijke third-party notices; runtime-bronverwijzingen staan in `public-site/licenses/`.

## Winkelbestand

Maak een snapshot vanuit een bestaand Overpass-bestand:

```sh
python3 public-site/scripts/build-locations.py --input /pad/naar/winkels.json
```

Met `--fetch` haalt het script eenmalig een landelijke snapshot op. Dit gebeurt niet tijdens bezoekersverzoeken. Het gegenereerde `public-site/generated/stores.json` bevat ODbL-bronvermelding en datum. De app waarschuwt na 30 dagen en weigert snapshots ouder dan 90 dagen.

## Hosting

De webapp gebruikt React, Tailwind CSS en Pyodide voor lokale matching. Een Cloudflare Worker verzorgt de PrijsProfeet-API met gedeelde budgetten en een tijdelijke SQLite Durable Object-cache.

Vanuit `public-site`:

```sh
npx wrangler deploy --dry-run
npx wrangler deploy
```

Configureer voor een eigen installatie de workernaam en `PUBLIC_APP_URL` in `wrangler.jsonc`. Stel een willekeurige `VISITOR_HASH_SECRET` in via `wrangler secret put`; zet secrets nooit in broncode. `PRIJSPROFEET_ENABLED=false` stopt nieuwe providerverzoeken. Bewaar de coordinator-binding en migratiegeschiedenis bij updates.

De Node-adapter (`npm start`) gebruikt één proces en één SQLite-database. Houd deze achter een vertrouwde HTTPS-proxy; configureer `TRUSTED_PROXY_IPS` expliciet en laat de proxy `X-Real-IP` overschrijven. Bewaar de database buiten de assets. Verwijder deze niet om limieten te resetten.

## Status

De checker is bruikbaar als testversie. Brondata is niet volledig en garandeert geen winkelvoorraad. Onbekende producten kunnen handmatige controle vragen. Kortingen worden per lijstregel berekend; acties over meerdere regels worden niet gecombineerd. PDF-pagina's zijn gerasterd.

Vóór een brede publieke lancering blijven metingen op tragere apparaten, hostingcapaciteit en operationele controle van bewaartermijnen nodig. De ingestelde limieten zijn geen garantie voor onbeperkt gratis gebruik.
