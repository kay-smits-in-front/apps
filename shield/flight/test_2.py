"""Test 2: opstijgen van geel, het groene kruis zoeken, ernaartoe vliegen en landen.

Start vanuit de projectroot:
    python -m shield.flight.test_2

Het live beeld opent eerst. SPATIE in het venster = opstijgen, q = direct landen.
"""

from shield.flight.drone import Vlucht
from shield.flight.runner import voer_uit
from shield.vision.markers import vind_groen

OMHOOG_S = 1.5  # Het groene kruis staat hoger (kastje); eerst boven het kastje vliegen.


def plan(vlucht: Vlucht) -> None:
    vlucht.opstijgen()
    vlucht.omhoog(OMHOOG_S)
    vlucht.zoek_door_draaien(vind_groen)
    vlucht.vlieg_en_land(vind_groen)


if __name__ == "__main__":
    voer_uit(plan)
