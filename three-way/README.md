# Three Way

Advies per aandeel voor de komende 2,5 handelsdag, plus het overzicht van je portefeuille. Alles gaat via één pagina
in de app.

## Gebruik

1. Start de app vanuit de hoofdmap `apps`: `python app.py`
2. Open http://127.0.0.1:5000, log in en klik op **Three Way**.
3. Vul **Nieuws** en **Intuïtie** in (-5 slecht, +5 goed) en druk op **Bereken advies** (ongeveer een halve minuut).
4. Voer de acties (VERKOPEN / KOPEN) zelf uit in je beleggingsapp. Pas daarna bij **Mijn aandelen** de aantallen aan.

Doe dit op maandag en woensdag, of elke dag als je wilt.

Eerste keer op een nieuwe computer: `python -m pip install -r requirements.txt` in de hoofdmap.
Daarna maak je eenmalig een beheerder aan met `flask --app app create-admin`.
De melding "Could not find platform independent libraries" in PyCharm is onschuldig.

## De pagina

| Onderdeel | Wat het doet |
|---|---|
| 1. Advies | Per aandeel de score, de actie en de reden |
| 2. Kandidaten | Je watchlist (aandelen die je interessant vindt), gescoord door het model. +1,5 of hoger is een kandidaat om naar te wisselen |
| 3. Portefeuille | Waarde als je had vastgehouden, tegenover de uitgevoerde adviezen; per aandeel en per verkoop |
| 4. Mijn aandelen | Toevoegen, aanpassen, weghalen (gelijk houden aan je beleggingsapp) |
| 5. Waarom nu | Welke factoren vandaag positief of negatief zijn |
| 6. Daghandel | Volume, gap, dagrange en RSI van de laatste dag |
| 7. Wie zit erin | Institutionelen, insiders, short interest, analisten |
| 8. Terugblik | Na 3 handelsdagen: had het advies gelijk, en welk onderdeel? |

## Hoe het advies werkt

- **Het model.** Een random forest (`functioning/forecast.py` en `forest.py`, alleen numpy) leert bij elke run opnieuw op
  de koershistorie van je aandelen en je watchlist. Het kijkt naar zeven facetten: regel, trend, cumulatief, RSI,
  volume, week en diepte. Het voorspelt of de koers binnen 3 handelsdagen minstens 3% daalt, stijgt of geen van beide.
- **De score.** Elk onderdeel heeft een score van -5 tot +5. Ze wegen zo mee: forest 55%, nieuws 25%, intuïtie 20%
  (`ADVICE_WEIGHTS` in `functioning/constants.py`).
- **De actie.** Ben je belegd en is de score -1,5 of lager, dan verkopen. Zit je in cash en is de score +1,5 of hoger,
  dan terugkopen. Anders houden.
- **Uitzonderingen.** Winnaars (verdubbeld in een jaar) worden alleen vastgehouden. Een verkoop die de €3,95 kosten niet
  dekt, wordt houden.

**Waarom alleen de forest:** in een toets op 5 jaar koersen (november 2026) deed de forest alleen het beter dan een
logistisch model, boosted bomen, een GAM, een LSTM en elk mengsel daarvan. Geen enkel model versloeg gewoon
vasthouden. Gebruik je nieuws en intuïtie dus serieus, en kijk in de Terugblik of het advies je helpt.

## Bestanden

| Bestand | Inhoud |
|---|---|
| `functioning/advice.py` | Score, actie, kandidaten en opslaan van het advies |
| `functioning/forecast.py`, `forest.py` | Het voorspelmodel |
| `functioning/overview.py` | De cijfers van de portefeuille |
| `functioning/daytrade.py`, `whynow.py`, `players.py` | Daghandel, waarom nu, wie zit erin |
| `functioning/review.py`, `advice_log.py` | De terugblik |
| `functioning/prices.py`, `market.py` | Koersen van Yahoo, met een cache in `data/prices.json` |
| `functioning/rule.py`, `storage.py`, `constants.py`, `imports.py` | Regel, opslag, instellingen, imports |

Persoonlijke bestanden in `data/` (holdings, watchlist, logboek) komen niet in Git.
