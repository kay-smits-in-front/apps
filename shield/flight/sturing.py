"""Pure rekenfuncties voor de sturing. Geen drone nodig, dus testbaar."""

from typing import NamedTuple

import numpy as np

from shield.vision.markers import Marker

DOEL_Y = 0.35  # Gewenste hoogte van de marker in het beeld (0 = midden, 1 = onderrand).
KP_YAW = 45.0
KP_HOOGTE = 60.0
VOORUIT_SNEL = 15
ZOEK_DAAL = -12
MAX_RC = 100
ZWEEP_PERIODE_S = 6.0
ZWEEP_LR = 20
ZWEEP_FB = 6


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
    """Draai naar de marker, houd hem op DOEL_Y door te stijgen/dalen, vlieg langzaam vooruit."""
    yaw = begrens(KP_YAW * marker.x)
    ud = begrens(-KP_HOOGTE * (marker.y - DOEL_Y))
    fb = VOORUIT_SNEL if abs(marker.x) < 0.4 else 0
    return Rc(0, fb, ud, yaw)


def zoek_dalen() -> Rc:
    """Marker nog niet zichtbaar: langzaam dalen."""
    return Rc(0, 0, ZOEK_DAAL, 0)


def zoek_draaien(snelheid: int = 25) -> Rc:
    """Marker nog niet zichtbaar: langzaam om de eigen as draaien."""
    return Rc(0, 0, 0, snelheid)


def demping(vx: float, vy: float) -> Rc:
    """Tegenstuurcommando om de gemeten snelheid (vx voor/achter, vy zijwaarts) af te remmen."""
    lr = int(np.clip(TEKEN_LR * KP_DEMP * vy, -MAX_DEMP, MAX_DEMP))
    fb = int(np.clip(TEKEN_FB * KP_DEMP * vx, -MAX_DEMP, MAX_DEMP))
    return Rc(lr, fb, 0, 0)


def corrigeer(rc: Rc, vx: float, vy: float) -> Rc:
    """Demp alleen de assen waarop we niets bewust commanderen."""
    d = demping(vx, vy)
    return Rc(rc.lr or d.lr, rc.fb or d.fb, rc.ud, rc.yaw)


def zoek_vegen(t: float) -> Rc:
    """Zoeken: langzaam vooruit en links-rechts zwaaien (sinus over de tijd t in seconden)."""
    lr = int(ZWEEP_LR * np.sin(2 * np.pi * t / ZWEEP_PERIODE_S))
    return Rc(lr, ZWEEP_FB, 0, 0)
