"""Pure rekenfuncties voor de sturing. Geen drone nodig, dus testbaar."""

from typing import NamedTuple

import numpy as np

from shield.vision.markers import Marker

DOEL_Y = 0.5  # Gewenste hoogte van het kruis in beeld (0 = midden, 1 = onderrand).
KP_YAW = 45.0
KP_HOOGTE = 40.0
VOORUIT_SNEL = 15
MAX_DAAL = -20
MAX_STIJG = 20
CENTREER_X = 0.25  # Alleen vooruit vliegen als het kruis minstens zo dicht bij het midden staat.
ROND_RC = 30  # Draaisnelheid bij rondkijken (ongeveer graden per seconde).
MAX_RC = 100

# Standpunten voor het rondkijken, na het eerste rondje: stijgen, dalen, rechts, stijgen, links, dalen.
# Samen een raster van 2 hoogtes x 3 plekken rond het startpunt. Move-commando's: minimaal 20 cm.
UITKIJKPUNTEN = (("up", 20), ("down", 40), ("right", 30), ("up", 40), ("left", 60), ("down", 40))


class Rc(NamedTuple):
    """Waarden voor send_rc_control: links/rechts, voor/achter, omhoog/omlaag, yaw."""

    lr: int
    fb: int
    ud: int
    yaw: int


STIL = Rc(0, 0, 0, 0)

# Drift-demping: tegenstuur op de gemeten snelheid. Het teken hangt af van de assen van de
# Tello; klopt het niet (drone drijft harder weg), draai dan TEKEN_FB of TEKEN_LR om.
KP_DEMP = 5.0
MAX_DEMP = 25
TEKEN_FB = -1
TEKEN_LR = 1


def begrens(waarde: float) -> int:
    return int(np.clip(waarde, -MAX_RC, MAX_RC))


def naar_marker(marker: Marker) -> Rc:
    """Draai naar het kruis, vlieg vooruit als het in het midden staat, houd het op DOEL_Y."""
    yaw = begrens(KP_YAW * marker.x)
    ud = int(np.clip(-KP_HOOGTE * (marker.y - DOEL_Y), MAX_DAAL, MAX_STIJG))
    fb = VOORUIT_SNEL if abs(marker.x) < CENTREER_X else 0
    return Rc(0, fb, ud, yaw)


def demping(vx: float, vy: float) -> Rc:
    """Tegenstuurcommando om de gemeten snelheid (vx voor/achter, vy zijwaarts) af te remmen."""
    lr = int(np.clip(TEKEN_LR * KP_DEMP * vy, -MAX_DEMP, MAX_DEMP))
    fb = int(np.clip(TEKEN_FB * KP_DEMP * vx, -MAX_DEMP, MAX_DEMP))
    return Rc(lr, fb, 0, 0)


def corrigeer(rc: Rc, vx: float, vy: float) -> Rc:
    """Demp alleen de assen waarop we niets bewust commanderen."""
    d = demping(vx, vy)
    return Rc(rc.lr or d.lr, rc.fb or d.fb, rc.ud, rc.yaw)


def uitkijkpunten() -> list[tuple[str, int]]:
    """Volgorde van (richting, cm) voor het wisselen van standpunt; richting = move_<richting>."""
    return list(UITKIJKPUNTEN)
