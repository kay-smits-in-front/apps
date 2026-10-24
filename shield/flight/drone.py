"""Verbinden met de Tello en de vluchtstappen die test_1 en test_2 delen."""

import logging
import math
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

import numpy as np
from djitellopy import Tello, TelloException

from shield.flight.sturing import ROND_RC, STIL, Rc, corrigeer, naar_marker, uitkijkpunten
from shield.vision.markers import SCORE_GEVONDEN, Marker
from shield.vision.muur import MUUR_STOP, muur_aandeel

MIN_BATTERIJ = 40
MIN_HOOGTE_CM = 25  # Niet verder dalen onder deze hoogte (als de hoogtemeting klopt).
DAAL_BUDGET_S = 4.0  # Totaal aantal seconden dat bij het naderen gedaald mag worden.
LOOP_TIJD_S = 0.03
LANDEN_Y = 0.7  # Kruis zo laag in beeld (en gecentreerd): we zijn er bijna.
LAATSTE_CM = 20  # Laatste stuk vooruit met het kruis onder de camera uit beeld.
MIN_NADER_S = 1.5  # Nooit landen voor we minstens zo lang naar het kruis zijn gevlogen.
BEVESTIG_FRAMES = 5  # Een kruis telt pas als hij zo vaak achter elkaar is gezien.
KWIJT_FRAMES = 8  # Zo lang kwijt = onder de camera verdwenen of echt weg.
STABILISEER_S = 1.0
VOORUIT_RC = 20  # Was 40 x 2.5 s: te ver en te hard.
VOORUIT_MAX_S = 2.0  # Maximale duur; stopt eerder zodra de muur het beeld vult.
OMHOOG_RC = 40

MAX_AFWIJKING_CM = 30  # Noodstop als de drone verder dan dit van het nulpunt raakt.
MAX_HELLING_GRADEN = 35  # Noodstop als de drone zo scheef hangt.
SNELHEID_CM = 10  # Aanname: vgx/vgy uit de statuspakketten zijn dm/s. Klopt dit niet, pas aan.

START = time.monotonic()

Zoeker = Callable[[np.ndarray], Marker | None]


class Hoek:
    """Telt hoeveel graden de drone gedraaid is, ook over de +-180 grens heen."""

    def __init__(self, yaw: float) -> None:
        self.vorige = yaw
        self.totaal = 0.0

    def bijwerken(self, yaw: float) -> float:
        """Verwerk een nieuwe yaw en geef het totaal gedraaide aantal graden (positief)."""
        self.totaal += (yaw - self.vorige + 540) % 360 - 180
        self.vorige = yaw
        return abs(self.totaal)


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
        self.daal_s = DAAL_BUDGET_S
        self.stop = threading.Event()  # Gezet door q: direct landen.
        self.max_afwijking: float | None = None  # None = bewust bewegen, geen afstandslimiet.

    def controleer(self) -> None:
        """Gooi Noodstop als de drone te scheef hangt of te ver van het nulpunt is."""
        if self.stop.is_set():
            raise Noodstop("Gestopt met q.")
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

    def vooruit(self, max_s: float = VOORUIT_MAX_S) -> None:
        """Vlieg vooruit tot de muur het beeld vult (bevestigd) of max_s om is."""
        stap("vooruit tot muur")
        self.nieuw_nulpunt(None)
        start, muur = time.monotonic(), 0
        while time.monotonic() - start < max_s:
            muur = muur + 1 if muur_aandeel(self.camera.frame) >= MUUR_STOP else 0
            if muur >= BEVESTIG_FRAMES:
                break
            self.stuur(Rc(0, VOORUIT_RC, 0, 0))
            time.sleep(LOOP_TIJD_S)
        self.houd(STIL, 1.0, max_afwijking=None)

    def draai(self, graden: float, marge: float = 8, timeout_s: float = 15) -> None:
        """Draai via rc-yaw op de gemeten yaw. 'cw' faalt zonder geldige vision-positie."""
        stap(f"draaien {graden:.0f}")
        self.nieuw_nulpunt(None)  # Alleen helling bewaken; de snelheid draait mee met de drone.
        hoek = Hoek(self.tello.get_yaw())
        einde = time.monotonic() + timeout_s
        while (gedraaid := hoek.bijwerken(self.tello.get_yaw())) < graden - marge:
            if time.monotonic() > einde:
                raise Noodstop("Draaien duurt te lang.")
            self.stuur(Rc(0, 0, 0, int(np.clip(graden - gedraaid, 25, 60))))
            time.sleep(0.05)
        self.houd(STIL, 1.0)

    def verplaats(self, richting: str, cm: int) -> None:
        """Eén stap met het ingebouwde move-commando. Weigert de drone dat, dan noodstop."""
        stap(f"{richting} {cm} cm")
        try:
            getattr(self.tello, f"move_{richting}")(cm)
        except TelloException as fout:
            raise Noodstop(f"Stap '{richting}' geweigerd door de drone: {fout}") from fout
        self.controleer()

    def rondkijken(self, zoeker: Zoeker, graden: float = 360.0, snelheid: int | None = None) -> Marker | None:
        """Draai langzaam rond en kijk naar elk beeld. Kruis terug zodra het BEVESTIG_FRAMES achter elkaar klopt."""
        snelheid = snelheid or ROND_RC
        self.nieuw_nulpunt(None)
        hoek = Hoek(self.tello.get_yaw())
        einde = time.monotonic() + 2 * graden / snelheid + 5
        gezien = 0
        while hoek.bijwerken(self.tello.get_yaw()) < graden and time.monotonic() < einde:
            marker = zoeker(self.camera.frame)
            gezien = gezien + 1 if marker is not None and marker.score >= SCORE_GEVONDEN else 0
            if gezien >= BEVESTIG_FRAMES:
                self.stuur(STIL)
                stap(f"kruis gezien, score {marker.score:.0%}")
                return marker
            self.stuur(Rc(0, 0, 0, snelheid))
            time.sleep(LOOP_TIJD_S)
        self.stuur(STIL)
        return None

    def zoek_kruis(self, zoeker: Zoeker, timeout_s: float = 150) -> Marker:
        """Rondkijken; niets gezien? Wissel van standpunt (stijgen, dalen, links, rechts) en kijk opnieuw rond."""
        start = time.monotonic()
        stap("rondkijken")
        if (marker := self.rondkijken(zoeker)) is not None:
            return marker
        for richting, cm in uitkijkpunten():
            if time.monotonic() - start > timeout_s:
                break
            self.verplaats(richting, cm)
            stap("rondkijken")
            if (marker := self.rondkijken(zoeker)) is not None:
                return marker
        raise Noodstop("Geen kruis gevonden.")

    def begrens_dalen(self, rc: Rc) -> Rc:
        """Daal in totaal maximaal DAAL_BUDGET_S en nooit onder MIN_HOOGTE_CM (als de meting klopt)."""
        if rc.ud >= 0:
            return rc
        hoogte = self.tello.get_height()
        if self.daal_s <= 0 or 0 < hoogte < MIN_HOOGTE_CM:
            return rc._replace(ud=0)
        self.daal_s -= LOOP_TIJD_S
        return rc

    def vlieg_en_land(self, zoeker: Zoeker, timeout_s: float = 40, min_nader_s: float = MIN_NADER_S) -> None:
        """Vlieg naar het kruis en land. Pas bij een gecentreerd kruis onderin beeld, na min_nader_s."""
        stap("naar het kruis")
        self.nieuw_nulpunt(None)
        start = time.monotonic()
        laatste: Marker | None = None
        rc, nabij, kwijt = STIL, 0, 0
        while time.monotonic() - start < timeout_s:
            marker = zoeker(self.camera.frame)
            genoeg_tijd = time.monotonic() - start >= min_nader_s
            if marker is not None and marker.score >= SCORE_GEVONDEN:
                kwijt, laatste = 0, marker
                nabij = nabij + 1 if abs(marker.x) < 0.25 and marker.y > LANDEN_Y else 0
                if nabij >= BEVESTIG_FRAMES and genoeg_tijd:
                    break
                rc = self.begrens_dalen(naar_marker(marker))
                self.stuur(rc)
            else:
                kwijt, nabij = kwijt + 1, 0
                if kwijt >= KWIJT_FRAMES:
                    if laatste is not None and laatste.y > LANDEN_Y - 0.15 and genoeg_tijd:
                        break  # Onderin beeld verdwenen: we zijn erboven.
                    raise Noodstop("Kruis kwijt.")
                self.stuur(rc)  # Kort kwijt: koers houden.
            time.sleep(LOOP_TIJD_S)
        else:
            raise Noodstop("Niet op tijd bij het kruis.")
        stap("laatste stuk en landen")
        self.stuur(STIL)
        try:
            self.tello.move_forward(LAATSTE_CM)
        except TelloException:
            pass  # Landen op de plek waar we nu zijn is beter dan niet landen.
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
def vlucht_met_camera() -> Iterator[Vlucht]:
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
    try:
        yield Vlucht(tello, camera)
    except Noodstop as reden:
        print(f"NOODSTOP: {reden}")
    finally:
        landen(tello)
        tello.streamoff()
        tello.end()
