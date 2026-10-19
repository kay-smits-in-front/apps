# AI-Lab

Een lab om modellen vanaf nul te bouwen en streng te toetsen. De kern (`lab/`) kent three-way niet.

```
lab/            kern: Dataset, features, labels, modellen, walk-forward toets, handel met kosten, runs
  models/       elk model is een klasse met fit() en predict_proba() (zie base.py)
  providers/    (leeg) plek voor API's om mee te spelen
adapters/       de brug naar een onderwerp; three_way.py leest data/prices.json van three-way
experiments/    een map per onderzoeksvraag, gewoon scripts voor PyCharm
runs/           resultaten per run (JSON, niet in Git)
tests/
```

Installeren in PyCharm: `pip install -e .[dev]` in deze map.

Eerste experiment: `python experiments/three_way_turns/run.py [pad/naar/prices.json]`.
Het leert op het verleden, test op de periode erna (met €3,95 per koop en verkoop) en vergelijkt met vasthouden.

Een nieuw onderwerp: nieuwe adapter plus nieuwe map onder `experiments/`. Een nieuw model: nieuwe klasse in `lab/models/`.
