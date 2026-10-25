"""Alleen camera: toont live of de Tello roze ziet. Geen opstijgen, geen vluchtcommando's.

Start vanuit de projectroot:
    python -m shield.vision.marker_test

Vensters: kleurbeeld met kaders, en de maskers. q = stoppen.
"""

import cv2
from djitellopy import Tello

from shield.vision.markers import ROZE

MIN_OPPERVLAK_PX = 100


def teken_kaders(scherm, masker, naam: str, kleur: tuple) -> None:
    """Teken een kader om elke vlek in het masker die groot genoeg is."""
    vormen, _ = cv2.findContours(masker, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for vorm in vormen:
        if cv2.contourArea(vorm) > MIN_OPPERVLAK_PX:
            x, y, b, h = cv2.boundingRect(vorm)
            cv2.rectangle(scherm, (x, y), (x + b, y + h), kleur, 2)
            cv2.putText(scherm, naam, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, kleur, 2)


def main() -> None:
    tello = Tello()
    tello.connect()
    tello.streamon()
    camera = tello.get_frame_read()
    try:
        while True:
            beeld = camera.frame.copy()
            # Het Tello-frame is RGB: zo krijg je correcte kleuren (anders is alles blauwig).
            hsv = cv2.cvtColor(beeld, cv2.COLOR_RGB2HSV)
            scherm = cv2.cvtColor(beeld, cv2.COLOR_RGB2BGR)
            roze_masker = cv2.inRange(hsv, *ROZE)
            teken_kaders(scherm, roze_masker, "ROZE", (255, 0, 255))
            cv2.imshow("Tello - herkenning roze (q = stoppen)", scherm)
            cv2.imshow("Roze masker", roze_masker)
            if cv2.waitKey(1) == ord("q"):
                break
    finally:
        tello.streamoff()
        tello.end()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
