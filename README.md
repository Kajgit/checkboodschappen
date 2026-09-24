# Checkboodschappen 🇳🇱

Plak je boodschappenlijst, vul je postcode in en vergelijk winkels in de buurt. Je ziet wat je nodig hebt, hoeveel verpakkingen je moet kopen en wat het kost bij één of twee winkels.

Gemaakt voor Nederlandse supermarkten.

[Probeer de site](https://checkboodschappen.thenorthsolution-b.workers.dev) · [Roadmap](https://checkboodschappen.thenorthsolution-b.workers.dev/roadmap)

## Wat kan het?

- Boodschappen vergelijken op postcode
- Hoeveelheden aanpassen, ook voor meerdere personen
- Producten en winkels openen
- Je bon downloaden als PDF of PNG
- Je lijst bewaren in je browser

Het is nog een testversie. Niet elk product staat in de bronnen en prijzen kunnen afwijken van de winkel. Check je lijst dus even voordat je gaat.

## Zelf draaien

Je hebt Node.js 22.13+ en Python 3.11+ nodig.

```sh
cd public-site
npm ci
cd ..
python3 public-site/scripts/build-locations.py --fetch
cd public-site
npm run build:assets
npm run dev
```

Open http://127.0.0.1:8787. Het winkelbestand komt van OpenStreetMap. PrijsProfeet staat lokaal uit; Checkjebon en postcodezoeken gebruiken wel internet.

Liever de lokale Python-app?

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
python3 run.py
```

Die app draait alleen lokaal. Ollama is optioneel en staat standaard uit.

## Tests

```sh
.venv/bin/python -m pytest -q
npm --prefix public-site test
```

## Gebruik van de code

De code is openbaar om te bekijken, zelf te gebruiken en aan bij te dragen. Er een eigen product of dienst van maken, verkopen of onder een ander merk aanbieden mag alleen met schriftelijke toestemming. Zie [LICENSE](LICENSE). Dit is source-available, geen open-source licentie.

De eerdere versie tot en met commit `1d59f6d` is onder MIT gepubliceerd. Die rechten blijven gelden voor die versie. De nieuwe voorwaarden gelden voor latere wijzigingen, voor zover de rechthebbenden die kunnen licentiëren.

Libraries houden hun eigen licenties. Dat geldt ook voor de prijsbronnen en OpenStreetMap-data. De bijbehorende teksten staan in `public-site/licenses/` en worden met de site meegeleverd.

Privacyvragen of commercieel gebruik: [info@thenorthsolution.com](mailto:info@thenorthsolution.com).
