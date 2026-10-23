"""Test 1: opstijgen van het gele kruis, 1 m vooruit, 180 graden draaien en landen op geel.

Start vanuit de projectroot:
    python -m shield.flight.test_1
"""

from shield.flight.drone import drone_met_camera, vlieg_en_land, zoek_door_dalen
from shield.vision.markers import vind_geel

VOORUIT_CM = 100


def main() -> None:
    with drone_met_camera() as (tello, camera):
        input("Zet de drone op het gele kruis, ruimte vrij. Enter = opstijgen: ")
        tello.takeoff()
        tello.move_forward(VOORUIT_CM)
        tello.rotate_clockwise(180)
        zoek_door_dalen(tello, camera, vind_geel)
        vlieg_en_land(tello, camera, vind_geel)


if __name__ == "__main__":
    main()
