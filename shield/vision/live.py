"""Live RGB-beeld op de laptop, met een markering waar geel en groen worden herkend."""

import threading

import cv2
import numpy as np

from shield.vision.markers import vind_geel, vind_groen

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
            tekst = f"{naam} {marker.oppervlak * 100:.1f}%"
            cv2.putText(scherm, tekst, (punt[0] + 30, punt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, kleur, 2)
    return scherm


class LiveBeeld:
    """Toont het camerabeeld in een eigen thread, zodat de vluchtlus er niet door vertraagt."""

    def __init__(self, camera) -> None:
        self.camera = camera
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def sluit(self) -> None:
        self.stop.set()
        self.thread.join(timeout=2)

    def _loop(self) -> None:
        while not self.stop.is_set():
            if (frame := self.camera.frame) is not None:
                cv2.imshow(VENSTER, teken(frame))
            if cv2.waitKey(30) & 0xFF == ord("q"):
                break
        cv2.destroyAllWindows()
