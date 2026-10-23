"""Test 2: opstijgen van geel, het groene kruis zoeken, ernaartoe vliegen en landen.

Start vanuit de projectroot:
    python -m shield.flight.test_2
"""

from shield.flight.drone import drone_met_camera, vlieg_en_land, zoek_door_draaien
from shield.vision.markers import vind_groen

OMHOOG_CM = 60  # Het groene kruis staat hoger (kastje); eerst boven het kastje vliegen.


def main() -> None:
    with drone_met_camera() as (tello, camera):
        input("Zet de drone op het gele kruis, ruimte vrij. Enter = opstijgen: ")
        tello.takeoff()
        tello.move_up(OMHOOG_CM)
        zoek_door_draaien(tello, camera, vind_groen)
        vlieg_en_land(tello, camera, vind_groen)


if __name__ == "__main__":
    main()
