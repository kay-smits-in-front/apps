"""Test 1: opstijgen van het gele kruis, 1 m vooruit, 180 graden draaien en landen op geel.

Start vanuit de projectroot:
    python -m shield.flight.test_1
"""

from shield.flight.drone import vlucht_met_camera
from shield.vision.markers import vind_geel


def main() -> None:
    with vlucht_met_camera() as vlucht:
        input("Zet de drone op het gele kruis, ruimte vrij. Enter = opstijgen: ")
        vlucht.opstijgen()
        vlucht.vooruit()
        vlucht.draai(180)
        vlucht.zoek_door_dalen(vind_geel)
        vlucht.vlieg_en_land(vind_geel)


if __name__ == "__main__":
    main()
