"""Hoeveel van het beeld lijkt op een muur? Een muur is vlak: bijna geen randen of textuur."""

import cv2
import numpy as np

from shield.vision.markers import verklein

RAND_DREMPEL = 6  # Grijswaarde-verschil tussen buurpixels dat nog als 'vlak' telt.
MUUR_STOP = 1.0  # Alleen bij een volledig vlak beeld (100%) stoppen we met vooruit vliegen.
ONTRUIS = (5, 5)  # Blur tegen sensorruis, zodat een echte muur ook echt 100% kan halen.


def muur_aandeel(frame_rgb: np.ndarray) -> float:
    """Aandeel (0..1) van het beeld zonder randen. 1.0 = alleen nog een egale muur."""
    grijs = cv2.blur(cv2.cvtColor(verklein(frame_rgb), cv2.COLOR_RGB2GRAY), ONTRUIS).astype(np.int16)
    dx = np.abs(np.diff(grijs, axis=1))[:-1]
    dy = np.abs(np.diff(grijs, axis=0))[:, :-1]
    return float(((dx < RAND_DREMPEL) & (dy < RAND_DREMPEL)).mean())
