"""Test 1: opstijgen, kleine stijging, 360-graden scan, naar het roze kruis vliegen en erop landen.

Start vanuit de projectroot:
    python -m shield.flight.test_1

Het live beeld opent eerst. SPATIE in het venster = opstijgen, q = direct landen, f = beeld opslaan.
"""

from shield.flight.drone import Vlucht
from shield.flight.runner import voer_uit
from shield.vision.markers import vind_roze


def plan(vlucht: Vlucht) -> None:
    vlucht.opstijgen()
    vlucht.kleine_stijging()
    kruis = vlucht.zoek_kruis(vind_roze)
    vlucht.vlieg_en_land(vind_roze, vast=kruis)


if __name__ == "__main__":
    voer_uit(plan)
