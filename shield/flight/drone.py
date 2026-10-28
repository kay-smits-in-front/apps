"""Verbinden met de Tello en de vluchtstappen die test_1 en test_2 delen."""

import logging
import math
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

import numpy as np
from djitellopy import Tello, TelloException

from shield.flight.sturing import (
    CENTREER_X, GENEGEERD_GRADEN, HERSTEL_RC, HERSTEL_S, HOOGTE_S, MAX_RONDES, OVER_HET_KRUIS_S, PRIORITEIT_FRAMES,
    REMMEN_STRAAL, RICHTING, ROND_RC, SLOT_SPRONG, SPOOR_SPRONG, START_OMHOOG_S, STIL, VERIFIEER_S, ZOEK_VOORUIT_S, Rc,
    corrigeer, is_dichtbij, is_erboven_verdwenen, naar_marker, verticale_opties,
)
from shield.flight.zoeken import Dekking, Geheugen, kies_richting, kies_stap_hoogte
from shield.vision.markers import SCORE_GEVONDEN, SCORE_TONEN, Marker
from shield.vision.muur import MUUR_STOP, muur_aandeel

MIN_BATTERIJ = 40
MIN_HOOGTE_CM = 25  # Niet verder dalen onder deze hoogte (als de hoogtemeting klopt).
DAAL_BUDGET_S = 4.0  # Totaal aantal seconden dat bij het naderen gedaald mag worden.
LOOP_TIJD_S = 0.03
LANDEN_Y = 0.7  # Kruis zo laag in beeld (en gecentreerd): we zijn er bijna.
LAATSTE_CM = 20  # Laatste stuk vooruit met het kruis onder de camera uit beeld.
MIN_NADER_S = 1.5  # Nooit landen voor we minstens zo lang naar het kruis zijn gevlogen.
BEVESTIG_FRAMES = 5
MIN_VOORUIT_S = 5.0  # Zo lang moet de drone naar het kruis toe gevlogen hebben voor hij 'aangekomen' mag zijn.
AANKOMST_FRAMES = 3  # Zo veel beelden achter elkaar moet het kruis 'dichtbij' zijn.  # Een kruis telt pas als hij zo vaak achter elkaar is gezien.
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


class Spoor:
    """Houdt bij of opeenvolgende detecties bij hetzelfde kruis horen: een kruis springt niet door het beeld."""

    def __init__(self, sprong: float, min_score: float = SCORE_GEVONDEN) -> None:
        self.sprong = sprong
        self.min_score = min_score
        self.laatste: Marker | None = None
        self.lengte = 0

    def past(self, marker: Marker) -> bool:
        """Is dit kruis dichtbij genoeg bij het vorige om hetzelfde te zijn (of is er nog geen vorige)?"""
        return self.laatste is None or (
            abs(marker.x - self.laatste.x) <= self.sprong and abs(marker.y - self.laatste.y) <= self.sprong
        )

    def volg(self, marker: Marker | None) -> int:
        """Verwerk een beeld; geef hoeveel beelden achter elkaar hetzelfde kruis (score >= min_score) is gezien."""
        if marker is None or marker.score < self.min_score:
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

    def vooruit(self, max_s: float = VOORUIT_MAX_S, zoeker: Zoeker | None = None) -> Marker | None:
        """Vlieg vooruit tot de muur het beeld vult of max_s om is.

        Met een zoeker kijkt de drone onderweg mee: een kruis dat BEVESTIG_FRAMES vast in beeld staat stopt de vlucht.
        """
        stap("vooruit tot muur")
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
            self.stuur(Rc(0, VOORUIT_RC, 0, 0))
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
        """Een korte, begrensde hoogteverandering (omhoog of omlaag) met rc, daarna stilhangen."""
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

    def scan(self, zoeker: Zoeker, dekking: Dekking, genegeerd: list[float], snelheid: int | None = None) -> Marker | None:
        """Draai een ronde en noteer per richting wat er te zien is. Stop direct bij een mogelijk kruis.

        Een 'mogelijk kruis' (score >= SCORE_TONEN, PRIORITEIT_FRAMES vast) stopt de draai meteen; `verifieer` kijkt dan
        of het er echt een is. Was het vals alarm, dan wordt die richting genegeerd en draait de scan door.
        Geeft het bevestigde kruis, of None na een volledige ronde.
        """
        snelheid = snelheid or ROND_RC
        self.nieuw_nulpunt(None)
        hoek = Hoek(self.tello.get_yaw())
        einde = time.monotonic() + 2 * 360 / snelheid + 5
        spoor = Spoor(SPOOR_SPRONG, SCORE_TONEN)
        while hoek.bijwerken(self.tello.get_yaw()) < 360 and time.monotonic() < einde:
            frame = self.camera.frame
            graden = abs(hoek.totaal)
            marker = zoeker(frame)
            dekking.registreer(graden, muur_aandeel(frame), marker.score if marker is not None else 0.0)
            negeren = any(abs((graden - g + 180) % 360 - 180) < GENEGEERD_GRADEN for g in genegeerd)
            if spoor.volg(None if negeren else marker) >= PRIORITEIT_FRAMES:
                stap(f"mogelijk kruis op {graden:.0f} graden, score {marker.score:.0%}: stop met draaien")
                self.stuur(STIL)
                if (bevestigd := self.verifieer(zoeker)) is not None:
                    return bevestigd
                genegeerd.append(graden)
                spoor = Spoor(SPOOR_SPRONG, SCORE_TONEN)
                continue
            self.stuur(Rc(0, 0, 0, snelheid))
            time.sleep(LOOP_TIJD_S)
        self.stuur(STIL)
        return None

    def verifieer(self, zoeker: Zoeker) -> Marker | None:
        """Vlieg rustig naar een mogelijk kruis toe tot het bevestigd is (score >= SCORE_GEVONDEN) of vals alarm blijkt.

        Alleen draaien en vooruit (nooit dalen). Het kruis blijft kwijt of de score stijgt niet: vals alarm.
        """
        stap("controleren: dichterbij kijken")
        self.nieuw_nulpunt(None)
        spoor, kwijt, einde = Spoor(SLOT_SPRONG, SCORE_TONEN), 0, time.monotonic() + VERIFIEER_S
        while time.monotonic() < einde:
            marker = zoeker(self.camera.frame)
            lengte = spoor.volg(marker)
            if lengte == 0:
                kwijt += 1
                if kwijt >= KWIJT_FRAMES:
                    break
                self.stuur(STIL)
            else:
                kwijt = 0
                if marker.score >= SCORE_GEVONDEN and lengte >= BEVESTIG_FRAMES:
                    self.stuur(STIL)
                    return marker
                self.stuur(naar_marker(marker)._replace(ud=0))
            time.sleep(LOOP_TIJD_S)
        self.houd(STIL, 0.5, max_afwijking=None)
        stap("vals alarm, verder zoeken")
        return None

    def zoek_kruis(self, zoeker: Zoeker, max_rondes: int = MAX_RONDES) -> Marker:
        """Scan het standpunt. Niets: ga naar de meest open richting en een ander hoogteniveau en scan opnieuw.

        Vliegt nergens heen waar een scan al muur zag. Is er geen open richting en geen nieuw hoogteniveau meer,
        dan is deze ruimte afgezocht.
        """
        geheugen, genegeerd = Geheugen(), []
        for ronde in range(max_rondes):
            stap(f"standpunt {ronde + 1} van {max_rondes}, niveau {geheugen.niveau}")
            dekking = Dekking()
            if (marker := self.scan(zoeker, dekking, genegeerd)) is not None:
                return marker
            geheugen.leg_vast(dekking)
            stap(f"niets gezien; {dekking.gezien():.0%} van de richtingen bekeken")
            if ronde == max_rondes - 1:
                break
            volgende = self.volgend_standpunt(zoeker, dekking, geheugen)
            if volgende is False:
                raise Noodstop("Ruimte afgezocht: geen kruis, geen open richting of nieuw hoogteniveau meer.")
            if volgende is not True:
                return volgende  # Onderweg al een kruis gezien.
            genegeerd = []
        raise Noodstop("Geen kruis gevonden.")

    def volgend_standpunt(self, zoeker: Zoeker, dekking: Dekking, geheugen: Geheugen) -> Marker | bool:
        """Draai naar de meest open richting en vlieg vooruit; pas het hoogteniveau aan.

        Geeft True na een verplaatsing, False als er nergens meer heen te gaan is, of een Marker als er onderweg
        een kruis in beeld kwam.
        """
        richting = kies_richting(dekking, geheugen.terug)
        stap_hoogte = kies_stap_hoogte(
            geheugen.niveau, geheugen.bezocht, verticale_opties(self.tello.get_height(), self.netto_hoogte_s)
        )
        if richting is None and stap_hoogte is None:
            return False
        if richting is not None:
            stap(f"naar de meest open richting: {richting:.0f} graden")
            self.draai_naar(richting)
            geheugen.gedraaid(richting)
            if (gezien := self.vooruit(ZOEK_VOORUIT_S, zoeker=zoeker)) is not None:
                return gezien
            geheugen.verplaatst()
        if stap_hoogte is not None:
            self.beweeg(stap_hoogte, HOOGTE_S)
            geheugen.veranderd_van_niveau(stap_hoogte)
        return True

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
        self, zoeker: Zoeker, vast: Marker | None = None, timeout_s: float = 40
    ) -> None:
        """Vergrendel op het kruis, vlieg ernaartoe, en land bij aankomst.

        Naderen: draai zodat het kruis midden in beeld blijft, vlieg vooruit als het gecentreerd is, daal als het
        te laag in beeld komt, en ga rustiger vooruit naarmate het kruis groter wordt. Een kruis dat ver van het
        vorige ligt wordt genegeerd (vergrendeld).
        Aangekomen als:
          - het kruis zo groot in beeld is dat we er vlak voor staan (ook een kruis op een muur): land direct;
          - het kruis onderin het beeld verdwijnt nadat we het van dichtbij zagen: nog even vooruit, dan landen;
          - het kruis staat laag en gecentreerd in beeld (BEVESTIG_FRAMES achter elkaar): nog even vooruit, dan landen.
        """
        stap("vergrendeld, naar het kruis")
        self.nieuw_nulpunt(None)
        start = vorig = time.monotonic()
        slot, laatste = Spoor(SLOT_SPRONG), vast  # Nog geen slot: na het draaien klopt de plek van `vast` niet meer.
        rc, laag, dichtbij, kwijt, herstel_start, vooruit_s = STIL, 0, 0, 0, None, 0.0
        reden: str | None = None
        while time.monotonic() - start < timeout_s and reden is None:
            frame = self.camera.frame
            marker = zoeker(frame)
            nu = time.monotonic()
            vooruit_s += (nu - vorig) * (rc.fb > 0)
            vorig = nu
            onderweg = vooruit_s >= MIN_VOORUIT_S  # Aankomst telt pas nadat we echt naar het kruis gevlogen hebben.
            if marker is not None and marker.score >= SCORE_GEVONDEN and slot.past(marker):
                kwijt, laatste, herstel_start, slot.laatste = 0, marker, None, marker
                dichtbij = dichtbij + 1 if is_dichtbij(marker) else 0
                laag = laag + 1 if abs(marker.x) < CENTREER_X and marker.y > LANDEN_Y and marker.straal >= REMMEN_STRAAL else 0
                if onderweg and dichtbij >= AANKOMST_FRAMES:
                    reden = "voor"
                elif onderweg and laag >= BEVESTIG_FRAMES:
                    reden = "erboven"
                else:
                    rc = self.begrens_dalen(naar_marker(marker))
                    self.stuur(rc)
            else:
                kwijt, laag, dichtbij = kwijt + 1, 0, 0
                if kwijt < KWIJT_FRAMES:
                    self.stuur(rc)  # Kort kwijt: koers houden.
                elif onderweg and is_erboven_verdwenen(laatste):
                    reden = "erboven"
                elif herstel_start is None or time.monotonic() - herstel_start < HERSTEL_S:
                    herstel_start = herstel_start or time.monotonic()
                    slot.laatste = None  # Ontgrendel: elk goed kruis mag weer.
                    richting = -1 if laatste is not None and laatste.x < 0 else 1
                    self.stuur(Rc(0, 0, 0, richting * HERSTEL_RC))  # Draai naar waar het kruis het laatst was.
                    rc = STIL
                else:
                    raise Noodstop("Kruis kwijt.")
            time.sleep(LOOP_TIJD_S)
        if reden is None:
            raise Noodstop("Niet op tijd bij het kruis.")
        if laatste is not None:
            stap(f"kruis straal {laatste.straal:.2f}, y {laatste.y:.2f}, {vooruit_s:.1f} s vooruit gevlogen")
        self.land_bij_kruis(reden)

    def land_bij_kruis(self, reden: str) -> None:
        """Landen bij aankomst. 'erboven': nog even vooruit (rc, geen move_*), 'voor': meteen landen."""
        stap(f"aangekomen ({reden}), landen")
        if reden == "erboven":
            self.houd(Rc(0, VOORUIT_RC, 0, 0), OVER_HET_KRUIS_S, max_afwijking=None)
        self.stuur(STIL)
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
