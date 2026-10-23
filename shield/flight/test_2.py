"""Test 2: opstijgen van geel, het groene kruis zoeken, ernaartoe vliegen en landen.

Start vanuit de projectroot:
    python -m shield.flight.test_2
"""

from shield.flight.drone import vlucht_met_camera
from shield.vision.markers import vind_groen

OMHOOG_S = 1.5  # Het groene kruis staat hoger (kastje); eerst boven het kastje vliegen.


def main() -> None:
    with vlucht_met_camera() as vlucht:
        input("Zet de drone op het gele kruis, ruimte vrij. Enter = opstijgen: ")
        vlucht.opstijgen()
        vlucht.omhoog(OMHOOG_S)
        vlucht.zoek_door_draaien(vind_groen)
        vlucht.vlieg_en_land(vind_groen)


if __name__ == "__main__":
    main()
