"""Test 1: opstijgen van het gele kruis, vooruit, 180 graden draaien, geel zoeken en erop landen.

Start vanuit de projectroot:
    python -m shield.flight.test_1

Het live beeld opent eerst. SPATIE in het venster = opstijgen, q = direct landen.
"""

from shield.flight.drone import Vlucht
from shield.flight.runner import voer_uit
from shield.vision.markers import vind_geel


def plan(vlucht: Vlucht) -> None:
    vlucht.opstijgen()
    vlucht.vooruit()
    vlucht.draai(180)
    vlucht.zoek_door_vegen(vind_geel)
    vlucht.vlieg_en_land(vind_geel)


if __name__ == "__main__":
    voer_uit(plan)
