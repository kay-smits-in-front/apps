# three-way
Beheer aandelen.


# "All good things come in three and there are always three ways out"
## Financial system

### The never zero project. 

Predicting, stearing and enumariting information
of financial instruments to maximize returns within a certian amount of time.
The window is not focused on short term profit but the focus is increasing rendement 
over a long time window by calling either , daily, weekly or monthly to. Buy, sell or hold.
Based on three information streems news, financial indicators, and intuiton.
#### news - daily, weekly monthly -- general, financial, socila media -- 40%
#### financial indicators -- monthly, yearly, overall -- 40%
#### intuition -- gut feeling, observations, financial situation -- 20% 

### Gebruik
**Maandag en woensdag: `python advice.py`.** Het vraagt nieuws en intuïtie (Enter = zelfde als vorige keer),
ververst de koersen, draait het AI-lab en print per aandeel de actie voor de komende 2,5 dag. Dat is alles.
Het advies staat daarna ook op de pagina "Simpel advies" in het portaal en onderaan het uitgebreide dashboard.

Vier onderdelen wegen elk 25% mee, elk van -5 tot +5: de LSTM (de laatste 93 dagen van het aandeel), de forest
(de twee zwaarste facetten uit alle koersfacetten), jouw nieuws en jouw intuïtie. Het gemiddelde is de score.
Belegd en score tot -1,5: verkopen. In cash en score vanaf +1,5: terugkopen. Anders houden. Winnaars worden alleen
vastgehouden en verkopen die de kosten niet dekken worden HOUDEN (`ADVICE_*` in `constants.py`).

Eens per maand (of als main zegt dat de regel oud is): `python walkforward.py`. Dat zoekt de beste regel
(`functioning/search.py`): per procentparameter van 0,5% tot 40% in stappen van 1%, stop na 5 stappen zonder
verbetering, plus grove sprongen om een ander dal te testen. Daarna toetst het de gevonden regel op het laatste jaar
dat de zoekactie niet zag. Kijk daar naar, niet alleen naar de score op de zoekperiode.
Eens per maand ook: `python experiments/three_way_advice/run.py train` in `ai-lab` (toets en train opnieuw).

`main.py` (elke ma, wo, vr) blijft bestaan als de uitgebreide check.

| Bestand | Vraag die het beantwoordt | Wanneer |
|---|---|---|
| `main.py` | Wat doe ik nu met elk aandeel? | ma, wo, vr |
| `advice.py` | Wat doe ik de komende 2,5 dag met elk aandeel? | ma, wo |
| `walkforward.py` | Welke instelling van de regel werkte het beste de afgelopen 5 jaar? Slaat die op in `data/rule.json`. | maandelijks |
| `backcasting.py` | Hoe had de regel de laatste 3 maanden gedaan, en wat is het maximum? | als je wilt kijken |

De instelling wordt gekozen op het aandeel van periodes van twee maanden waarin de regel beter was dan
vasthouden. Recente periodes tellen zwaarder: een periode telt half zo zwaar voor elke 6 periodes (ongeveer een jaar)
die hij verder terug ligt (`RECENCY_HALF_LIFE_WINDOWS` in `constants.py`).

Alle drie gebruiken dezelfde regel (`rule.py`) met dezelfde instelling (`data/rule.json`),
dus main toont zelf ook het bewijs van de regel. Nieuws en intuitie (en analyse) zitten alleen in main,
want daar bestaat geen historie van. Tot er een maand checks in `data/checks.json` staan.

### Bestanden
| Bestand | Inhoud |
|---|---|
| `main.py`, `advice.py`, `walkforward.py`, `backcasting.py` | De scripts |
| `search.py` | De zoekactie naar de beste regel en de hold-out toets |
| `advice.py` (in `functioning`) | Score, actie en uitvoer van het advies |
| `constants.py`, `imports.py` | Alle constanten, alle imports |
| `market.py` | Yahoo, koersen, holdings |
| `rule.py` | De regel en de beslissing |
| `testing.py` | De rollende test van de regel |
| `analysis.py` | Fundamentals, analistenverwachting, ingevoerde scores |
| `storage.py` | Opgeslagen checks, cash-status, snapshots en regel |
| `report.py` | Overzicht van main en portefeuilletabel |

## Integratie in kay.apps
Deze map volgt de actuele code uit de aparte repository `kay-smits-in-front/three-way`.
Persoonlijke portefeuille- en statusbestanden worden niet gekopieerd. Maak lokaal `data/holdings.json` aan op basis van `data/holdings.example.json`; deel het echte bestand niet en commit het niet.
