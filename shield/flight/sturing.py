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


class Rc(NamedTuple):
    """Waarden voor send_rc_control: links/rechts, voor/achter, omhoog/omlaag, yaw."""

    lr: int
    fb: int
    ud: int
    yaw: int


STIL = Rc(0, 0, 0, 0)


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
