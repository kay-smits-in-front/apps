"""Test 2: opstijgen, vooruit tot de muur, rondkijken naar het groene kruis, erheen vliegen en landen.

Start vanuit de projectroot:
    python -m shield.flight.test_2

Het live beeld opent eerst. SPATIE in het venster = opstijgen, q = direct landen.
"""

from shield.flight.drone import Vlucht
from shield.flight.runner import voer_uit
from shield.vision.markers import vind_groen


def plan(vlucht: Vlucht) -> None:
    vlucht.opstijgen()
    vlucht.vooruit()
    vlucht.zoek_kruis(vind_groen)
    vlucht.vlieg_en_land(vind_groen)


if __name__ == "__main__":
    voer_uit(plan)
