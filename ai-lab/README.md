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

Advies voor three-way: `python experiments/three_way_advice/run.py score` (of `train`: toetsen op onbekende dagen en opnieuw trainen).
Een LSTM (93 dagen, alle facetten op -5 tot +5) en een random forest op alle facetten (de geleerde gewichten bepalen wat zwaar telt)
voorspellen daling, niets of stijging van minstens 3% binnen 3 handelsdagen. `train` print of ze beter zijn dan de
basiskans; kijk daar eerst naar. Beide modellen zijn eigen numpy-code (`lab/models/forest.py`, `lab/models/lstm.py`): geen torch en geen scikit-learn nodig.
Alleen het oudere experiment `three_way_turns` gebruikt scikit-learn: `python -m pip install scikit-learn`
(let op: de naam is `scikit-learn`, niet `sklearn`).

Een nieuw onderwerp: nieuwe adapter plus nieuwe map onder `experiments/`. Een nieuw model: nieuwe klasse in `lab/models/`.
