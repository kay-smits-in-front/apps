# AI-Lab

Een lab om modellen vanaf nul te bouwen en streng te toetsen. De kern (`lab/`) kent three-way niet.

```
lab/            kern: Dataset, features, labels, modellen, walk-forward toets, handel met kosten, runs
  models/       elk model is een klasse met fit() en predict_proba() (zie base.py); logistic, forest, lstm
  providers/    (leeg) plek voor API's om mee te spelen
adapters/       de brug naar een onderwerp; three_way.py leest data/prices.json van three-way
experiments/    een map per onderzoeksvraag, gewoon scripts voor PyCharm
runs/           resultaten per run (JSON, niet in Git)
tests/
```

Installeren in PyCharm: `pip install -e .[dev]` in deze map.

Eerste experiment: `python experiments/three_way_turns/run.py [pad/naar/prices.json]`.
Het leert op het verleden, test op de periode erna (met €3,95 per koop en verkoop) en vergelijkt met vasthouden.

Advies voor three-way: `python experiments/three_way_advice/run.py score` (of `train`: eerst toetsen op onbekende dagen).
Vier modellen kijken naar dezelfde facetten (-5 tot +5) en voorspellen daling, niets of stijging van minstens 3% binnen
3 handelsdagen: een random forest (`lab/models/forest.py`, de geleerde gewichten bepalen wat zwaar telt), een logistische
regressie (`logit.py`), boosted bomen in XGBoost-stijl en een GAM (`boosted.py`, het GAM is hetzelfde met stompjes van
diepte 1). Alles is eigen numpy-code: geen torch, scikit-learn of xgboost nodig. `train` print of ze beter zijn dan de
basiskans (verlies, accuracy en MSE in scores); kijk daar eerst naar. De LSTM (`lab/models/lstm.py`) blijft beschikbaar
maar zit niet meer in het advies.
Alleen het oudere experiment `three_way_turns` gebruikt scikit-learn: `python -m pip install scikit-learn`
(let op: de naam is `scikit-learn`, niet `sklearn`).

Een nieuw onderwerp: nieuwe adapter plus nieuwe map onder `experiments/`. Een nieuw model: nieuwe klasse in `lab/models/`.
