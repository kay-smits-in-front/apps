"""Voert een vluchtplan uit met live beeld vooraf: SPATIE = opstijgen, q = stoppen en landen."""

import threading
import traceback
from typing import Callable

from shield.flight.drone import Noodstop, Vlucht, stap, vlucht_met_camera
from shield.vision.live import LiveBeeld

Plan = Callable[[Vlucht], None]


def werk(plan: Plan, vlucht: Vlucht, live: LiveBeeld) -> None:
    """Wacht op SPATIE en voer het plan uit. Een noodstop of q wordt hier afgehandeld."""
    stap("camera aan; SPATIE in het beeldvenster = opstijgen, q = stoppen")
    live.start.wait()
    if live.stop.is_set():
        return
    try:
        plan(vlucht)
    except Noodstop as reden:
        print(f"NOODSTOP: {reden}")
    except Exception as fout:  # Elke andere fout: melden; daarna landt vlucht_met_camera.
        print(f"FOUT: {type(fout).__name__}: {fout}")
        traceback.print_exc()


def voer_uit(plan: Plan) -> None:
    """Live beeld in de hoofdthread, het vluchtplan in een werker-thread."""
    with vlucht_met_camera() as vlucht:
        live = LiveBeeld(vlucht.camera)
        werker = threading.Thread(target=werk, args=(plan, vlucht, live))
        werker.start()
        live.toon(werker)
        vlucht.stop.set()  # q ingedrukt of klaar: het plan stopt bij het volgende commando.
        werker.join()
