"""Verbinden met de Tello en de vluchtstappen die test_1 en test_2 delen."""

import logging
import math
import random
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, NamedTuple

import numpy as np
from djitellopy import Tello, TelloException

from shield.flight.sturing import (
    BOOG_S, BOOG_YAW, HERSTEL_RC, HERSTEL_S, HOOGTE_S, MAX_RONDES, RICHTING, ROND_RC, SLOT_SPRONG, SPOOR_SPRONG,
    START_OMHOOG_S, STIL, ZIJ_S, ZOEK_VOORUIT_S, Rc, corrigeer, horizontale_opties, naar_marker, verticale_opties,
)
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


class Waarneming(NamedTuple):
    """Een kruis dat tijdens de scan recht voor de drone stond, en in welke richting dat was."""

    graden: float  # Hoeveel graden na de start van de scan (0..360).
    marker: Marker


class Spoor:
    """Houdt bij of opeenvolgende detecties bij hetzelfde kruis horen: een kruis springt niet door het beeld."""

    def __init__(self, sprong: float) -> None:
        self.sprong = sprong
        self.laatste: Marker | None = None
        self.lengte = 0

    def past(self, marker: Marker) -> bool:
        """Is dit kruis dichtbij genoeg bij het vorige om hetzelfde te zijn (of is er nog geen vorige)?"""
        return self.laatste is None or (
            abs(marker.x - self.laatste.x) <= self.sprong and abs(marker.y - self.laatste.y) <= self.sprong
        )

    def volg(self, marker: Marker | None) -> int:
        """Verwerk een beeld; geef hoeveel beelden achter elkaar hetzelfde goede kruis is gezien."""
        if marker is None or marker.score < SCORE_GEVONDEN:
            self.laatste, self.lengte = None, 0
            return 0
        self.lengte = self.lengte + 1 if self.past(marker) else 1
        self.laatste = marker
        return self.lengte


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
        self.netto_hoogte_s = 0.0  # Seconden omhoog min omlaag tijdens het zoeken.
        self.rng = random.Random()
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

    def vooruit(self, max_s: float = VOORUIT_MAX_S, yaw: int = 0, zoeker: Zoeker | None = None) -> Marker | None:
        """Vlieg vooruit (met yaw > 0 of < 0 in een boog) tot de muur het beeld vult of max_s om is.

        Met een zoeker kijkt de drone onderweg mee: een kruis dat BEVESTIG_FRAMES vast in beeld staat stopt de vlucht.
        """
        stap("vooruit tot muur" if yaw == 0 else "boog")
        self.nieuw_nulpunt(None)
        start, muur, spoor, gezien = time.monotonic(), 0, Spoor(SPOOR_SPRONG), None
        while time.monotonic() - start < max_s:
            frame = self.camera.frame
            muur = muur + 1 if muur_aandeel(frame) >= MUUR_STOP else 0
            if zoeker is not None and spoor.volg(zoeker(frame)) >= BEVESTIG_FRAMES:
                gezien = spoor.laatste
                break
            if muur >= BEVESTIG_FRAMES:
                break
            self.stuur(Rc(0, VOORUIT_RC, 0, yaw))
            time.sleep(LOOP_TIJD_S)
        self.houd(STIL, 1.0, max_afwijking=None)
        return gezien

    def draai(self, graden: float, richting: int = 1, marge: float = 8, timeout_s: float = 15) -> None:
        """Draai via rc-yaw op de gemeten yaw. 'cw' faalt zonder geldige vision-positie."""
        stap(f"draaien {richting * graden:.0f}")
        self.nieuw_nulpunt(None)  # Alleen helling bewaken; de snelheid draait mee met de drone.
        hoek = Hoek(self.tello.get_yaw())
        einde = time.monotonic() + timeout_s
        while (gedraaid := hoek.bijwerken(self.tello.get_yaw())) < graden - marge:
            if time.monotonic() > einde:
                raise Noodstop("Draaien duurt te lang.")
            self.stuur(Rc(0, 0, 0, richting * int(np.clip(graden - gedraaid, 25, 60))))
            time.sleep(0.05)
        self.houd(STIL, 1.0)

    def draai_naar(self, graden: float) -> None:
        """Draai naar een richting (0..360 graden vanaf de start van de scan) via de kortste kant."""
        if graden <= 180:
            self.draai(graden)
        else:
            self.draai(360 - graden, richting=-1)

    def beweeg(self, naam: str, seconden: float) -> None:
        """Een korte, begrensde beweging (rechts, links, omhoog, omlaag) met rc, daarna stilhangen."""
        stap(f"{naam} {seconden:.1f} s")
        self.netto_hoogte_s += seconden * ((naam == "omhoog") - (naam == "omlaag"))
        self.houd(RICHTING[naam], seconden, max_afwijking=None)
        self.houd(STIL, 0.6, max_afwijking=None)

    def kleine_stijging(self) -> None:
        self.beweeg("omhoog", START_OMHOOG_S)

    def muur_voor(self) -> bool:
        """Staat er een muur recht voor ons? (bevestigd over een paar beelden)"""
        metingen = []
        for _ in range(BEVESTIG_FRAMES):
            metingen.append(muur_aandeel(self.camera.frame) >= MUUR_STOP)
            time.sleep(LOOP_TIJD_S)
        return all(metingen)

    def scan360(self, zoeker: Zoeker, snelheid: int | None = None) -> Waarneming | None:
        """Draai een hele ronde en kijk naar elk beeld. Geef het kruis dat het langst vast in beeld stond.

        De kijkrichting is het moment waarop dat kruis het dichtst bij het midden van het beeld stond.
        """
        snelheid = snelheid or ROND_RC
        self.nieuw_nulpunt(None)
        hoek = Hoek(self.tello.get_yaw())
        einde = time.monotonic() + 2 * 360 / snelheid + 5
        spoor, beste, beste_lengte, kandidaat = Spoor(SPOOR_SPRONG), None, 0, None
        while hoek.bijwerken(self.tello.get_yaw()) < 360 and time.monotonic() < einde:
            marker = zoeker(self.camera.frame)
            lengte = spoor.volg(marker)
            if lengte == 0:
                kandidaat = None
            elif lengte == 1:
                kandidaat = Waarneming(abs(hoek.totaal), marker)
            elif kandidaat is not None and abs(marker.x) < abs(kandidaat.marker.x):
                kandidaat = Waarneming(abs(hoek.totaal), marker)
            if lengte >= BEVESTIG_FRAMES and lengte > beste_lengte:
                beste, beste_lengte = kandidaat, lengte
            self.stuur(Rc(0, 0, 0, snelheid))
            time.sleep(LOOP_TIJD_S)
        self.stuur(STIL)
        if beste is not None:
            stap(f"kruis gezien ({beste_lengte} beelden), score {beste.marker.score:.0%}, op {beste.graden:.0f} graden")
        return beste

    def zoek_kruis(self, zoeker: Zoeker, max_rondes: int = MAX_RONDES) -> Marker:
        """Scan eerst de hele ruimte. Gevonden: draai ernaartoe. Niets: ergens anders heen en opnieuw."""
        for ronde in range(max_rondes):
            stap(f"scan {ronde + 1} van {max_rondes}")
            if (waarneming := self.scan360(zoeker)) is not None:
                self.draai_naar(waarneming.graden)
                return waarneming.marker
            if ronde < max_rondes - 1 and (onderweg := self.nieuwe_plek(zoeker)) is not None:
                return onderweg  # Tijdens het verplaatsen al gezien: meteen vergrendelen.
        raise Noodstop("Geen kruis gevonden.")

    def nieuwe_plek(self, zoeker: Zoeker | None = None) -> Marker | None:
        """Willekeurige horizontale stap (vooruit, opzij of boog) plus een stap omhoog of omlaag binnen de grenzen."""
        keuze = self.rng.choice(horizontale_opties(self.muur_voor()))
        gezien = None
        if keuze == "vooruit":
            gezien = self.vooruit(ZOEK_VOORUIT_S, zoeker=zoeker)
        elif keuze.startswith("boog"):
            gezien = self.vooruit(BOOG_S, yaw=BOOG_YAW if keuze == "boog_rechts" else -BOOG_YAW, zoeker=zoeker)
        else:
            self.beweeg(keuze, ZIJ_S)
        if gezien is None and (hoogte := verticale_opties(self.tello.get_height(), self.netto_hoogte_s)):
            self.beweeg(self.rng.choice(hoogte), HOOGTE_S)
        return gezien

    def begrens_dalen(self, rc: Rc) -> Rc:
        """Daal in totaal maximaal DAAL_BUDGET_S en nooit onder MIN_HOOGTE_CM (als de meting klopt)."""
        if rc.ud >= 0:
            return rc
        hoogte = self.tello.get_height()
        if self.daal_s <= 0 or 0 < hoogte < MIN_HOOGTE_CM:
            return rc._replace(ud=0)
        self.daal_s -= LOOP_TIJD_S
        return rc

    def vlieg_en_land(
        self, zoeker: Zoeker, vast: Marker | None = None, timeout_s: float = 40, min_nader_s: float = MIN_NADER_S
    ) -> None:
        """Vergrendel op het kruis, vlieg ernaartoe op een vaste route en land.

        Vergrendeld: alleen een kruis dat bij het vorige past telt; een ander kruis elders in beeld wordt genegeerd.
        Route: naar het kruis draaien, vooruit zodra het in het midden staat, dalen als het te laag in beeld komt.
        """
        stap("vergrendeld, naar het kruis")
        self.nieuw_nulpunt(None)
        start = time.monotonic()
        slot, laatste = Spoor(SLOT_SPRONG), vast
        slot.laatste = vast
        rc, nabij, kwijt, herstel_start = STIL, 0, 0, None
        while time.monotonic() - start < timeout_s:
            marker = zoeker(self.camera.frame)
            genoeg_tijd = time.monotonic() - start >= min_nader_s
            if marker is not None and marker.score >= SCORE_GEVONDEN and slot.past(marker):
                kwijt, laatste, herstel_start, slot.laatste = 0, marker, None, marker
                nabij = nabij + 1 if abs(marker.x) < 0.25 and marker.y > LANDEN_Y else 0
                if nabij >= BEVESTIG_FRAMES and genoeg_tijd:
                    break
                rc = self.begrens_dalen(naar_marker(marker))
                self.stuur(rc)
            else:
                kwijt, nabij = kwijt + 1, 0
                if kwijt < KWIJT_FRAMES:
                    self.stuur(rc)  # Kort kwijt: koers houden.
                elif laatste is not None and laatste.y > LANDEN_Y - 0.15 and genoeg_tijd:
                    break  # Onderin beeld verdwenen: we zijn erboven.
                elif herstel_start is None or time.monotonic() - herstel_start < HERSTEL_S:
                    herstel_start = herstel_start or time.monotonic()
                    slot.laatste = None  # Ontgrendel: elk goed kruis mag weer.
                    richting = -1 if laatste is not None and laatste.x < 0 else 1
                    self.stuur(Rc(0, 0, 0, richting * HERSTEL_RC))  # Draai naar waar het kruis het laatst was.
                else:
                    raise Noodstop("Kruis kwijt.")
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
