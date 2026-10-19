"""Every run is written down: what was tried and what came out. One JSON file per run."""

import json
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def save_run(experiment: str, config: dict, result: dict, folder: Path = RUNS_DIR) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}-{experiment}.json"
    path.write_text(json.dumps({"experiment": experiment, "time": stamp, "config": config, "result": result}, indent=2))
    return path


def latest_run(experiment: str, folder: Path = RUNS_DIR) -> dict | None:
    files = sorted(folder.glob(f"*-{experiment}.json"))
    return json.loads(files[-1].read_text()) if files else None
