"""Test 2: opstijgen, naar de vloersensor en het startniveau, 360-graden scan, naar het roze kruis vliegen en erop landen.

Start vanuit de projectroot:
    python -m shield.flight.test_2

Het live beeld opent eerst. SPATIE in het venster = opstijgen, q = direct landen, f = beeld opslaan.
"""

from shield.flight.drone import Vlucht
from shield.flight.runner import voer_uit
from shield.vision.kruis import vind_roze_kruis


def plan(vlucht: Vlucht) -> None:
    vlucht.opstijgen()
    vlucht.start_hoogte()
    kruis = vlucht.zoek_kruis(vind_roze_kruis)
    vlucht.vlieg_en_land(vind_roze_kruis, vast=kruis)


if __name__ == "__main__":
    voer_uit(plan)
