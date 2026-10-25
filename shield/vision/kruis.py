"""Het roze kruis vinden met twee onafhankelijke methoden die elkaar bevestigen.

Kleurvlek-methode (markers.py): vlek + vormregels. Lijnen-methode (lijnen.py): lijnen die samenkomen.
Zien beide hetzelfde kruis, dan is de score 100%. Ziet er één een kruis (score >= SCORE_GEVONDEN), dan telt dat ook.
"""

import numpy as np

from shield.vision.lijnen import vind_kruis_lijnen
from shield.vision.markers import SCORE_GEVONDEN, Marker, vind_roze

MAX_VERSCHIL = 0.15  # Zo dicht (schermbreedte -1..1) moeten twee detecties bij elkaar liggen.


def zelfde_plek(a: Marker, b: Marker) -> bool:
    return bool(np.hypot(a.x - b.x, a.y - b.y) <= MAX_VERSCHIL)


def vind_roze_kruis(frame_rgb: np.ndarray) -> Marker | None:
    """Beste roze kruis in een RGB-frame, of None."""
    vlek, lijnen = vind_roze(frame_rgb), vind_kruis_lijnen(frame_rgb)
    if vlek and lijnen and vlek.score >= SCORE_GEVONDEN and zelfde_plek(vlek, lijnen):
        return lijnen._replace(oppervlak=vlek.oppervlak, score=1.0)  # Lijnen geven het nauwkeurigste midden.
    kandidaten = [m for m in (vlek, lijnen) if m is not None]
    return max(kandidaten, key=lambda m: m.score, default=None)
