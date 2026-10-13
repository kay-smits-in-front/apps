# Three Way and Thinkwave integration

## Folder layout

- `three-way/`: bundled Three Way Python source, including `main.py`, `backcasting.py`, `walkforward.py`, `signals/` and `tracker/`.
- `three-way/data/`: runtime portfolio and state files. Personal portfolio data is intentionally not committed.
- `thinkwave/`: Thinkwave-specific notes; the PlayCanvas project remains hosted separately.

## Local Three Way setup

1. Install the app dependencies from the repository root: `pip install -r requirements.txt`.
2. Copy `three-way/data/holdings.example.json` to `three-way/data/holdings.json`.
3. Replace the example entry with your own holdings. The format is `{"holdings": [{"ticker": "NVDA", "quantity": 1, "cost_eur": 100.0}]}`. Use Yahoo Finance ticker symbols and your actual quantity/cost values.
4. Keep `three-way/data/holdings.json` private. It is ignored by Git.
5. Start the Flask app and open Dashboard → Three Way. The runner allows only the three known scripts and uses a timeout and one-at-a-time lock.

`main.py` updates local check/cash state, so it requires an explicit confirmation in the portal. Backcasting and walk-forward can take a while because they query Yahoo Finance.

## Render

The web runner intentionally refuses to execute Three Way scripts in production. Render containers are ephemeral and the personal portfolio/check files need private persistent storage; running them directly in a web worker could lose state or block requests. Thinkwave can be viewed in the portal, but Three Way execution needs a separate isolated worker plus a persistent private volume/database before it is enabled.

## Thinkwave

The authenticated `/apps/thinkwave` route embeds `https://playcanv.as/p/f8c12796/`. The original PlayCanvas project is not copied into this repository; this folder keeps the integration boundary clear.
