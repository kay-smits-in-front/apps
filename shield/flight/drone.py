"""Verbinden met de Tello en de vluchtstappen die test_1 en test_2 delen."""

import logging
import math
import time
from contextlib import contextmanager
from typing import Callable, Iterator

import numpy as np
from djitellopy import Tello, TelloException

from shield.flight.sturing import STIL, Rc, corrigeer, naar_marker, zoek_dalen, zoek_draaien, zoek_vegen
from shield.vision.live import LiveBeeld
from shield.vision.markers import Marker

MIN_BATTERIJ = 40
MIN_HOOGTE_CM = 25
LOOP_TIJD_S = 0.03
LANDEN_Y = 0.75
LAATSTE_METERS_CM = 20
STABILISEER_S = 4.0
VOORUIT_RC = 20  # Was 40 x 2.5 s: te ver en te hard.
VOORUIT_S = 2.0
OMHOOG_RC = 40

MAX_AFWIJKING_CM = 30  # Noodstop als de drone verder dan dit van het nulpunt raakt.
MAX_HELLING_GRADEN = 35  # Noodstop als de drone zo scheef hangt.
SNELHEID_CM = 10  # Aanname: vgx/vgy uit de statuspakketten zijn dm/s. Klopt dit niet, pas aan.

START = time.monotonic()

Zoeker = Callable[[np.ndarray], Marker | None]


class Noodstop(RuntimeError):
    """De drone doet iets wat niet is afgesproken: direct landen."""


def stap(naam: str) -> None:
    print(f"[{time.monotonic() - START:5.1f}s] {naam}")


class Positie:
    """Afstand tot een nulpunt, opgeteld uit de snelheid in de statuspakketten (dead reckoning)."""

    def __init__(self, tello: Tello) -> None:
        self.tello = tello
        self.nulpunt()

    def nulpunt(self) -> None:
        self.x = self.y = 0.0
        self.laatste = time.monotonic()

    def bijwerken(self) -> None:
        nu = time.monotonic()
        dt, self.laatste = nu - self.laatste, nu
        self.x += self.tello.get_speed_x() * SNELHEID_CM * dt
        self.y += self.tello.get_speed_y() * SNELHEID_CM * dt

    def afwijking(self) -> float:
        return math.hypot(self.x, self.y)


class Vlucht:
    """Eén vlucht: stuurt de drone en bewaakt hem bij elk commando."""

    def __init__(self, tello: Tello, camera) -> None:
        self.tello = tello
        self.camera = camera
        self.positie = Positie(tello)
        self.max_afwijking: float | None = None  # None = bewust bewegen, geen afstandslimiet.

    def controleer(self) -> None:
        """Gooi Noodstop als de drone te scheef hangt of te ver van het nulpunt is."""
        self.positie.bijwerken()
        helling = max(abs(self.tello.get_pitch()), abs(self.tello.get_roll()))
        if helling > MAX_HELLING_GRADEN:
            raise Noodstop(f"Te scheef: {helling:.0f} graden.")
        if self.max_afwijking is not None and self.positie.afwijking() > self.max_afwijking:
            raise Noodstop(f"Te ver van het nulpunt: {self.positie.afwijking():.0f} cm.")

    def stuur(self, rc: Rc) -> None:
        """Controleer, demp de drift en stuur."""
        self.controleer()
        gecorrigeerd = corrigeer(rc, self.tello.get_speed_x(), self.tello.get_speed_y())
        self.tello.send_rc_control(*gecorrigeerd)

    def nieuw_nulpunt(self, max_afwijking: float | None) -> None:
        self.positie.nulpunt()
        self.max_afwijking = max_afwijking

    def houd(self, rc: Rc, seconden: float, max_afwijking: float | None = MAX_AFWIJKING_CM) -> None:
        """Houd rc vast voor een tijd. Met max_afwijking=None mag de drone bewust bewegen."""
        self.nieuw_nulpunt(max_afwijking)
        einde = time.monotonic() + seconden
        while time.monotonic() < einde:
            self.stuur(rc)
            time.sleep(0.05)

    def opstijgen(self) -> None:
        """Opstijgen; daarna stil hangen binnen de afstandslimiet."""
        stap("opstijgen")
        self.tello.takeoff()
        stap("stabiliseren")
        self.houd(STIL, STABILISEER_S)

    def omhoog(self, seconden: float) -> None:
        stap("omhoog")
        self.houd(Rc(0, 0, OMHOOG_RC, 0), seconden, max_afwijking=None)
        self.houd(STIL, 1.0)

    def vooruit(self) -> None:
        stap("vooruit")
        self.houd(Rc(0, VOORUIT_RC, 0, 0), VOORUIT_S, max_afwijking=None)
        self.houd(STIL, 1.0)

    def draai(self, graden: float, marge: float = 8, timeout_s: float = 15) -> None:
        """Draai via rc-yaw op de gemeten yaw. 'cw' faalt zonder geldige vision-positie."""
        stap(f"draaien {graden:.0f}")
        self.nieuw_nulpunt(None)  # Alleen helling bewaken; de snelheid draait mee met de drone.
        gedraaid, vorige = 0.0, self.tello.get_yaw()
        einde = time.monotonic() + timeout_s
        while abs(gedraaid) < graden - marge:
            if time.monotonic() > einde:
                raise Noodstop("Draaien duurt te lang.")
            yaw = self.tello.get_yaw()
            gedraaid += (yaw - vorige + 540) % 360 - 180
            vorige = yaw
            snelheid = int(np.clip(graden - abs(gedraaid), 25, 60))
            self.stuur(Rc(0, 0, 0, snelheid))
            time.sleep(0.05)
        self.houd(STIL, 1.0)

    def zoek_marker(
        self,
        zoeker: Zoeker,
        zoek_actie: Callable[[float], Rc],
        timeout_s: float,
        max_afwijking: float | None = MAX_AFWIJKING_CM,
        min_hoogte: float = 0.0,
    ) -> Marker:
        """Voer zoek_actie(t) uit tot de marker zichtbaar is. Faalt na timeout of te lage hoogte."""
        self.nieuw_nulpunt(max_afwijking)
        start = time.monotonic()
        while (t := time.monotonic() - start) < timeout_s:
            if (marker := zoeker(self.camera.frame)) is not None:
                self.stuur(STIL)
                return marker
            if min_hoogte and self.tello.get_height() < min_hoogte:
                break
            self.stuur(zoek_actie(t))
            time.sleep(LOOP_TIJD_S)
        raise Noodstop("Marker niet gevonden.")

    def zoek_door_dalen(self, zoeker: Zoeker, timeout_s: float = 20) -> Marker:
        stap("zoeken door dalen")
        return self.zoek_marker(zoeker, lambda t: zoek_dalen(), timeout_s, min_hoogte=MIN_HOOGTE_CM)

    def zoek_door_draaien(self, zoeker: Zoeker, timeout_s: float = 25) -> Marker:
        stap("zoeken door draaien")
        return self.zoek_marker(zoeker, lambda t: zoek_draaien(), timeout_s)

    def zoek_door_vegen(self, zoeker: Zoeker, timeout_s: float = 10) -> Marker:
        """Vooruit en links-rechts zwaaien; ~10 s bij rc 6 is ruim een meter vooruit."""
        stap("zoeken door vegen")
        return self.zoek_marker(zoeker, zoek_vegen, timeout_s, max_afwijking=None)

    def vlieg_en_land(self, zoeker: Zoeker, timeout_s: float = 30) -> None:
        """Volg de marker; zodra hij laag in beeld is of onderin verdwijnt: laatste stuk en landen."""
        stap("naar de marker")
        self.nieuw_nulpunt(None)
        einde = time.monotonic() + timeout_s
        laatste: Marker | None = None
        while time.monotonic() < einde:
            marker = zoeker(self.camera.frame)
            if marker is None:
                if laatste is not None and laatste.y > LANDEN_Y - 0.15:
                    break
                self.stuur(STIL)
            elif marker.y > LANDEN_Y:
                break
            else:
                self.stuur(naar_marker(marker))
                laatste = marker
            time.sleep(LOOP_TIJD_S)
        else:
            raise Noodstop("Niet op tijd bij de marker.")
        stap("laatste stuk en landen")
        self.houd(Rc(0, VOORUIT_RC, 0, 0), LAATSTE_METERS_CM / 100, max_afwijking=None)
        self.tello.send_rc_control(*STIL)
        self.tello.land()


def landen(tello: Tello) -> None:
    """Land. Lukt dat niet (bijv. 'Motor stop'), zet dan de motoren uit."""
    if not tello.is_flying:
        return
    tello.send_rc_control(*STIL)
    try:
        tello.land()
    except TelloException:
        tello.emergency()
        tello.is_flying = False


@contextmanager
def vlucht_met_camera(toon_beeld: bool = True) -> Iterator[Vlucht]:
    """Verbind, zet de camera aan voor het opstijgen en land altijd, ook bij een noodstop."""
    logging.getLogger("djitellopy").setLevel(logging.WARNING)  # Elke rc-regel printen vertraagt.
    Tello.RESPONSE_TIMEOUT = 3
    tello = Tello()
    tello.connect()
    if tello.get_battery() < MIN_BATTERIJ:
        tello.end()
        raise RuntimeError(f"Batterij onder {MIN_BATTERIJ}%.")
    tello.streamon()
    camera = tello.get_frame_read()
    while camera.frame is None or not camera.frame.any():
        time.sleep(0.05)
    live = LiveBeeld(camera) if toon_beeld else None
    if live:
        live.start()
    try:
        yield Vlucht(tello, camera)
    except Noodstop as reden:
        print(f"NOODSTOP: {reden}")
    finally:
        landen(tello)
        if live:
            live.sluit()
        tello.streamoff()
        tello.end()
