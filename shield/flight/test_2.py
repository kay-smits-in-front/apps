"""Test 2: opstijgen van geel, het groene kruis zoeken, ernaartoe vliegen en landen.

Start vanuit de projectroot:
    python -m shield.flight.test_2
"""

from shield.flight.drone import drone_met_camera, houd_rc, opstijgen, stap, vlieg_en_land, zoek_door_draaien
from shield.flight.sturing import Rc
from shield.vision.markers import vind_groen

OMHOOG_S = 1.5  # Het groene kruis staat hoger (kastje); eerst boven het kastje vliegen.


def main() -> None:
    with drone_met_camera() as (tello, camera):
        input("Zet de drone op het gele kruis, ruimte vrij. Enter = opstijgen: ")
        opstijgen(tello)
        stap("omhoog")
        houd_rc(tello, Rc(0, 0, 40, 0), OMHOOG_S)
        stap("zoeken door draaien")
        zoek_door_draaien(tello, camera, vind_groen)
        stap("groen gezien: naar het kruis")
        vlieg_en_land(tello, camera, vind_groen)


if __name__ == "__main__":
    main()
