# Three Way

Een assistent die met je meekijkt: de trends van je aandelen en je watchlist, signalen die aandacht vragen, het nieuws,
je eigen beeld en een klein voorspelmodel. Alles op één pagina in de app.

## Gebruik

1. Start de app vanuit de hoofdmap `apps`: `python app.py`
2. Open http://127.0.0.1:5000, log in en klik op **Three Way**.
3. De pagina laadt alles zelf, ook het model (één keer per dag). Je hoeft niets in te vullen om informatie te zien.
4. Lees de cijferstrook en **Vandaag**. Staat daar niets, dan hoef je niets te doen.
5. Doe je iets in je beleggingsapp, leg het dan vast in het **Logboek** en pas onder **Beheer** de aantallen aan.

Eerste keer op een nieuwe computer: `python -m pip install -r requirements.txt` in de hoofdmap.
Daarna maak je eenmalig een beheerder aan met `flask --app app create-admin`.

## De pagina

| Onderdeel | Wat het doet |
|---|---|
| Cijferstrook | Waarde, verandering over dag, week, maand, 3 maanden en 12 maanden, daling vanaf de top, en het gemiddelde per maand en per kwartaal |
| Monitor | Eén rij per aandeel (portefeuille en watchlist) met gekleurde cellen per periode, trend, gewicht, model, advies, rotatie en signalen. Klik op een aandeel voor de koersgrafiek met de gemiddelden van 50 en 200 dagen, nieuws, achtergrond en je eigen score met notitie |
| Vandaag | De punten die aandacht vragen: signalen, een advies om te verkopen of terug te kopen, en in de eerste week van de maand de rotatie |
| Regels die werken | Vijf controles op je eigen portefeuille, met de les erbij: grootste positie, grootste drie, trend, daling vanaf de top en het aantal handelingen |
| Waarde, Rendement per maand, Verdeling | De grafieken van je portefeuille |
| Logboek | Wat je deed en waarom, met de koers van toen en wat die sindsdien deed |
| Terugblik | Na 3 handelsdagen: had het advies gelijk, en welk onderdeel? |
| Beheer | Je aandelen en je watchlist (ingeklapt onderaan) |

Nieuws en intuïtie (rechtsboven, -5 tot +5) zijn je algemene beeld. Na een wijziging druk je op **Bijwerken**.

## Hoe het werkt

- **Signalen** (`functioning/monitor.py`) zijn gebeurtenissen van de laatste week, geen dagelijkse ruis:
  een positie van 20% of meer van je portefeuille, een val tot 20% onder de top van 3 maanden, een kruising van het
  gemiddelde van 200 dagen, en een volumepiek (2x normaal) met een dagbeweging van 3% of meer. De grenzen staan in
  `constants.py` (`SIGNAL_*`).
- **Jouw beeld.** Nieuws en intuïtie vul je algemeen in, en per aandeel als je daar een eigen mening over hebt
  (met een notitie). De score per aandeel is nieuws 40%, intuïtie 40% en het model 20% (`ADVICE_WEIGHTS`).
  Belegd en -1,5 of lager: verkopen. In cash en +1,5 of hoger: terugkopen. Winnaars (verdubbeld in een jaar) worden
  alleen vastgehouden, en een verkoop die de €3,95 kosten niet dekt, wordt houden.
- **Het model** (`forecast.py`, `forest.py`) is een random forest op zeven facetten van de koers. Het geeft een score
  voor de komende 3 dagen en de kans dat de slotkoers morgen hoger is. Dat is extra informatie, geen reden om te
  handelen: in de toets (november 2026) versloeg geen enkel model, ook geen LSTM, gewoon vasthouden.
- **De rotatie** (`rotation.py`) rangschikt aandelen op de stijging van 12 maanden zonder de laatste maand, gedeeld
  door de beweeglijkheid, en houdt het sterkste derde. In de toets beter dan vasthouden, maar niet bewezen.
  Bekijk hem één keer per maand.
- **Nieuws** (`news.py`) zijn de laatste koppen van Yahoo per aandeel. Jij beoordeelt wat ze betekenen.

## Bestanden

| Bestand | Inhoud |
|---|---|
| `functioning/monitor.py` | De rollende trends en de signalen |
| `functioning/advice.py` | Score, actie en opslaan van het advies |
| `functioning/forecast.py`, `forest.py` | Het model |
| `functioning/rotation.py` | De maandelijkse rotatie |
| `functioning/news.py` | Nieuwskoppen van Yahoo |
| `functioning/overview.py` | De cijfers van de portefeuille, per periode en per maand |
| `functioning/daytrade.py`, `whynow.py`, `players.py` | Laatste handelsdag, waarom nu, wie zit erin |
| `functioning/review.py`, `advice_log.py` | De terugblik |
| `functioning/prices.py`, `market.py` | Koersen van Yahoo, met een cache in `data/prices.json` |
| `functioning/rule.py`, `storage.py`, `constants.py`, `imports.py` | Regel, opslag, instellingen, imports |

Persoonlijke bestanden in `data/` (holdings, watchlist, eigen scores, logboek) komen niet in Git.
