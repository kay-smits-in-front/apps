"""Live RGB-beeld op de laptop, met een markering waar geel en groen worden herkend."""

import threading

import cv2
import numpy as np

from shield.vision.markers import score, vind_geel, vind_groen
from shield.vision.muur import muur_aandeel

VENSTER = "SHIELD live (q = sluiten)"
KLEUREN = (("GEEL", vind_geel, (0, 255, 255)), ("GROEN", vind_groen, (0, 255, 0)))  # BGR


def teken(frame_rgb: np.ndarray) -> np.ndarray:
    """Zet het RGB-frame om naar BGR en teken een cirkel + oppervlak op elke herkende marker."""
    scherm = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    hoogte, breedte = scherm.shape[:2]
    for naam, zoeker, kleur in KLEUREN:
        if (marker := zoeker(frame_rgb)) is not None:
            punt = (int((marker.x + 1) / 2 * breedte), int((marker.y + 1) / 2 * hoogte))
            cv2.circle(scherm, punt, 25, kleur, 3)
            tekst = f"{naam} score {score(marker):.0%} ({marker.oppervlak:.2%} van beeld)"
            cv2.putText(scherm, tekst, (punt[0] + 30, punt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, kleur, 2)
    return scherm


class LiveBeeld:
    """Live beeld in de hoofdthread (dat is de betrouwbare plek voor OpenCV-vensters).

    Toetsen: SPATIE zet `start`, q zet `stop` (en `start`, zodat wachtende code vrijkomt).
    """

    HINT = "SPATIE = opstijgen | q = stoppen en landen"

    def __init__(self, camera) -> None:
        self.camera = camera
        self.start = threading.Event()
        self.stop = threading.Event()

    def toon(self, werker: threading.Thread) -> None:
        """Toon beeld tot de werker-thread klaar is of q wordt ingedrukt."""
        while werker.is_alive() and not self.stop.is_set():
            if (frame := self.camera.frame) is not None:
                scherm = teken(frame)
                cv2.putText(scherm, self.HINT, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                cv2.putText(scherm, f"MUUR {muur_aandeel(frame):.0%}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                cv2.imshow(VENSTER, scherm)
            toets = cv2.waitKey(30) & 0xFF
            if toets == ord(" "):
                self.start.set()
            elif toets == ord("q"):
                self.stop.set()
                self.start.set()
        cv2.destroyAllWindows()
