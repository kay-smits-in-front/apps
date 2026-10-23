"""Test 1: opstijgen van het gele kruis, 1 m vooruit, 180 graden draaien en landen op geel.

Start vanuit de projectroot:
    python -m shield.flight.test_1
"""

from shield.flight.drone import (
    draai_180, drone_met_camera, opstijgen, stap, vlieg_en_land, vooruit, zoek_door_dalen,
)
from shield.vision.markers import vind_geel


def main() -> None:
    with drone_met_camera() as (tello, camera):
        input("Zet de drone op het gele kruis, ruimte vrij. Enter = opstijgen: ")
        opstijgen(tello)
        vooruit(tello)
        draai_180(tello)
        stap("zoeken door dalen")
        zoek_door_dalen(tello, camera, vind_geel)
        stap("geel gezien: naar het kruis")
        vlieg_en_land(tello, camera, vind_geel)


if __name__ == "__main__":
    main()
