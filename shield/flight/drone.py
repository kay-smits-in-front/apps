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
    CENTREER_X, GENEGEERD_GRADEN, HERSTEL_RC, HERSTEL_S, HOOGTE_CM_PER_S, HOOGTE_MARGE_CM, HOOGTE_MAX_S, HOOGTE_RC,
    KIJK_FRAMES, KIJK_S, KIJK_TUSSEN_S, MAX_RONDES, MIN_STAP_RC, MIN_VLOER_CM, NIVEAU_CM, NIVEAU_PRIOR,
    OVER_HET_KRUIS_S, PRIORITEIT_FRAMES, RC_M_PER_S, REMMEN_STRAAL, SCAN_STAP_GRADEN, SLOT_SPRONG, SPOOR_SPRONG,
    STAP_RC, START_NIVEAU, STIL, TAKEOFF_CM, VERIFIEER_S, Rc, corrigeer, is_dichtbij, is_erboven_verdwenen,
    naar_marker,
)
from shield.flight.kaart import KOLOMMEN, Kaart, peiling_en_afstand, rechte_stukken
from shield.vision.markers import SCORE_GEVONDEN, SCORE_TONEN, Marker
from shield.vision.muur import MUUR_STOP, muur_aandeel, muur_kolommen

MIN_BATTERIJ = 40
DAAL_BUDGET_S = 4.0  # Totaal aantal seconden dat bij het naderen gedaald mag worden.
LOOP_TIJD_S = 0.03
LANDEN_Y = 0.7  # Kruis zo laag in beeld (en gecentreerd): we zijn er bijna.
LAATSTE_CM = 20  # Laatste stuk vooruit met het kruis onder de camera uit beeld.
MIN_NADER_S = 1.5  # Nooit landen voor we minstens zo lang naar het kruis zijn gevlogen.
BEVESTIG_FRAMES = 5
MIN_VOORUIT_S = 5.0  # Zo lang moet de drone naar het kruis toe gevlogen hebben voor hij 'aangekomen' mag zijn.
AANKOMST_FRAMES = 3  # Zo veel beelden achter elkaar moet het kruis 'dichtbij' zijn.  # Een kruis telt pas als hij zo vaak achter elkaar is gezien.
KWIJT_S = 0.8  # Zo lang geen kruis gezien = onder de camera verdwenen of echt weg (tijd, want een beeld kost ~50 ms).
STIL_ZOEK_S = 1.5  # Eerst zo lang stilhangen en kijken voor we ronddraaien om een kwijtgeraakt kruis te zoeken.
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
        self.hoogte_schatting = float(TAKEOFF_CM)  # Alleen gebruikt als de hoogtemeting 0 geeft.
        self.kaart = Kaart(NIVEAU_PRIOR)
        self.koers = 0.0  # Kijkrichting in graden (draairichting van rc-yaw) vanaf de startrichting.
        self.niveau = START_NIVEAU  # Huidig hoogteniveau (index in NIVEAU_CM).
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

    def vooruit(self, max_s: float, zoeker: Zoeker | None = None) -> Marker | None:
        """Vlieg vooruit tot de muur het beeld vult of max_s om is; houd de afgelegde afstand op de kaart bij.

        Met een zoeker kijkt de drone onderweg mee: een kruis dat BEVESTIG_FRAMES vast in beeld staat stopt de vlucht.
        Stopte hij voor een muur, dan wordt die op de kaart gezet.
        """
        stap(f"vooruit, maximaal {max_s:.1f} s (stopt bij een muur)")
        self.nieuw_nulpunt(None)
        start = vorig = time.monotonic()
        muur, spoor, gezien, gevlogen_s = 0, Spoor(SPOOR_SPRONG), None, 0.0
        while vorig - start < max_s:
            frame = self.camera.frame
            muur = muur + 1 if muur_aandeel(frame) >= MUUR_STOP else 0
            if zoeker is not None and spoor.volg(zoeker(frame)) >= BEVESTIG_FRAMES:
                gezien = spoor.laatste
                break
            if muur >= BEVESTIG_FRAMES:
                break
            self.stuur(Rc(0, VOORUIT_RC, 0, 0))
            time.sleep(LOOP_TIJD_S)
            nu = time.monotonic()
            gevlogen_s, vorig = gevlogen_s + (nu - vorig), nu
        self.kaart.verplaats(gevlogen_s * VOORUIT_RC * RC_M_PER_S, self.koers)
        if muur >= BEVESTIG_FRAMES:
            self.kaart.markeer_wand(self.koers)
        self.houd(STIL, 1.0, max_afwijking=None)
        return gezien

    def draai_tot(self, hoek: Hoek, doel_graden: float, richting: int = 1, marge: float = 4, timeout_s: float = 10) -> None:
        """Draai via rc-yaw tot `hoek` (de gemeten yaw sinds de start) `doel_graden` heeft bereikt, en blijf dan stil."""
        einde, begin = time.monotonic() + timeout_s, abs(hoek.totaal)
        try:
            while (gedraaid := hoek.bijwerken(self.tello.get_yaw())) < doel_graden - marge:
                if time.monotonic() > einde:
                    raise Noodstop("Draaien duurt te lang.")
                self.stuur(Rc(0, 0, 0, richting * int(np.clip(doel_graden - gedraaid, MIN_STAP_RC, STAP_RC))))
                time.sleep(0.05)
        finally:
            self.koers = (self.koers + richting * (abs(hoek.totaal) - begin)) % 360
        self.stuur(STIL)

    def draai(self, graden: float, richting: int = 1, marge: float = 8, timeout_s: float = 15) -> None:
        """Draai via rc-yaw op de gemeten yaw. 'cw' faalt zonder geldige vision-positie."""
        stap(f"draaien {richting * graden:.0f}")
        self.nieuw_nulpunt(None)  # Alleen helling bewaken; de snelheid draait mee met de drone.
        self.draai_tot(Hoek(self.tello.get_yaw()), graden, richting, marge, timeout_s)
        self.houd(STIL, 1.0)

    def draai_naar(self, graden: float) -> None:
        """Draai naar een richting (0..360 graden vanaf de start van de scan) via de kortste kant."""
        if graden <= 180:
            self.draai(graden)
        else:
            self.draai(360 - graden, richting=-1)

    def hoogte_cm(self) -> float:
        """Hoogte boven de vloer in cm: de sensor als die iets meldt, anders onze eigen schatting uit rc-tijd."""
        gemeten = self.tello.get_height()
        return float(gemeten) if gemeten > 0 else self.hoogte_schatting

    def ga_naar_hoogte(self, doel_cm: float, max_s: float = HOOGTE_MAX_S) -> None:
        """Stijg of daal tot de sensor de gewenste hoogte meldt (maximaal max_s), en hang dan stil."""
        doel_cm = max(doel_cm, MIN_VLOER_CM)
        stap(f"naar hoogte {doel_cm:.0f} cm (nu {self.hoogte_cm():.0f})")
        self.nieuw_nulpunt(None)
        start = vorig = time.monotonic()
        while vorig - start < max_s and abs(hoogte := self.hoogte_cm()) and abs(doel_cm - hoogte) > HOOGTE_MARGE_CM:
            richting = 1 if hoogte < doel_cm else -1
            self.stuur(Rc(0, 0, richting * HOOGTE_RC, 0))
            time.sleep(0.05)
            nu = time.monotonic()
            self.hoogte_schatting += richting * HOOGTE_CM_PER_S * (nu - vorig)
            vorig = nu
        self.houd(STIL, 0.6, max_afwijking=None)
        self.hoogte_schatting = self.hoogte_cm()

    def naar_niveau(self, niveau: int) -> None:
        """Ga naar een hoogteniveau uit NIVEAU_CM."""
        self.ga_naar_hoogte(NIVEAU_CM[niveau])
        self.niveau = niveau

    def start_hoogte(self) -> None:
        """Eerst naar beneden tot de vloersensor het laagste niveau meldt (zo kennen we de hoogte), dan naar het startniveau."""
        stap(f"hoogtesensoren: barometer/vloer {self.tello.get_height()} cm, ToF {self.tello.get_distance_tof()}")
        self.naar_niveau(0)
        self.naar_niveau(START_NIVEAU)

    def muur_voor(self) -> bool:
        """Staat er een muur recht voor ons? (bevestigd over een paar beelden)"""
        metingen = []
        for _ in range(BEVESTIG_FRAMES):
            metingen.append(muur_aandeel(self.camera.frame) >= MUUR_STOP)
            time.sleep(LOOP_TIJD_S)
        return all(metingen)

    def kijk(self, zoeker: Zoeker, graden: float, spoor: Spoor, genegeerd: list[float]) -> bool:
        """Sta stil, neem KIJK_FRAMES verse beelden. True bij een mogelijk kruis (PRIORITEIT_FRAMES vast).

        Zonder kruis wordt de kans in alles wat we zagen op de kaart verlaagd.
        """
        self.houd(STIL, KIJK_S, max_afwijking=None)
        negeren = any(abs((graden - g + 180) % 360 - 180) < GENEGEERD_GRADEN for g in genegeerd)
        for _ in range(KIJK_FRAMES):
            frame = self.camera.frame
            if spoor.volg(None if negeren else zoeker(frame)) >= PRIORITEIT_FRAMES:
                return True
            self.stuur(STIL)
            time.sleep(KIJK_TUSSEN_S)
        self.kaart.bekijk(self.niveau, self.koers, muur_kolommen(frame, KOLOMMEN))
        return False

    def scan(self, zoeker: Zoeker, genegeerd: list[float], stap_graden: float = SCAN_STAP_GRADEN) -> Marker | None:
        """Draai een ronde in stappen: draai, hang stil, kijk. Stop direct bij een mogelijk kruis.

        Stilstaan bij het kijken voorkomt bewegingsonscherpte en een achterlopend beeld. Een 'mogelijk kruis'
        (score >= SCORE_TONEN, PRIORITEIT_FRAMES vast) stopt de scan meteen; `verifieer` kijkt of het er echt een
        is. Was het vals alarm, dan wordt die richting genegeerd en gaat de scan door. Geeft het bevestigde kruis,
        of None na een volledige ronde (de drone kijkt dan weer de richting op waarin hij begon).
        """
        self.nieuw_nulpunt(None)
        hoek = Hoek(self.tello.get_yaw())
        spoor = Spoor(SPOOR_SPRONG, SCORE_TONEN)
        for doel in np.arange(0, 360 - 1e-6, stap_graden):
            self.draai_tot(hoek, float(doel))
            if self.kijk(zoeker, abs(hoek.totaal), spoor, genegeerd):
                stap(f"mogelijk kruis op {abs(hoek.totaal):.0f} graden: stop met draaien")
                if (bevestigd := self.verifieer(zoeker)) is not None:
                    return bevestigd
                genegeerd.append(abs(hoek.totaal))
                spoor = Spoor(SPOOR_SPRONG, SCORE_TONEN)
        self.draai_tot(hoek, 360.0)  # Weer in de beginrichting kijken.
        stap(f"scan klaar, geschatte afwijking {self.positie.afwijking():.0f} cm")
        return None

    def verifieer(self, zoeker: Zoeker) -> Marker | None:
        """Vlieg rustig naar een mogelijk kruis toe tot het bevestigd is (score >= SCORE_GEVONDEN) of vals alarm blijkt.

        Alleen draaien en vooruit (nooit dalen). Het kruis blijft kwijt of de score stijgt niet: vals alarm.
        """
        stap("controleren: dichterbij kijken")
        self.nieuw_nulpunt(None)
        spoor, einde = Spoor(SLOT_SPRONG, SCORE_TONEN), time.monotonic() + VERIFIEER_S
        gezien_op = time.monotonic()
        while time.monotonic() < einde:
            marker = zoeker(self.camera.frame)
            lengte = spoor.volg(marker)
            if lengte == 0:
                if time.monotonic() - gezien_op >= KWIJT_S:
                    break
                self.stuur(STIL)
            else:
                gezien_op = time.monotonic()
                if marker.score >= SCORE_GEVONDEN and lengte >= BEVESTIG_FRAMES:
                    self.stuur(STIL)
                    return marker
                self.stuur(naar_marker(marker)._replace(ud=0))
            time.sleep(LOOP_TIJD_S)
        self.houd(STIL, 0.5, max_afwijking=None)
        stap("vals alarm, verder zoeken")
        return None

    def zoek_kruis(self, zoeker: Zoeker, max_rondes: int = MAX_RONDES) -> Marker:
        """Scan het standpunt; niets: ga naar het standpunt met de meeste verwachte winst (A*) en scan opnieuw.

        Stopt als de kans dat het kruis nog ergens ligt waar we niet gekeken hebben te klein is geworden.
        """
        for ronde in range(max_rondes):
            stap(f"standpunt {ronde + 1} van {max_rondes}, niveau {self.niveau}, ({self.kaart.x:.1f}, {self.kaart.y:.1f}) m")
            if (marker := self.scan(zoeker, [])) is not None:
                return marker
            stap(f"niets gezien; kans dat het kruis nog ergens ligt: {self.kaart.restkans():.0%}")
            if ronde == max_rondes - 1:
                break
            volgende = self.volgend_standpunt(zoeker)
            if volgende is False:
                raise Noodstop("Ruimte afgezocht: de resterende kans is te klein of er is nergens meer winst te halen.")
            if volgende is not True:
                return volgende  # Onderweg al een kruis gezien.
        raise Noodstop("Geen kruis gevonden.")

    def mogelijke_niveaus(self) -> set[int]:
        """Alle hoogteniveaus: de sensor stuurt de hoogte, dus elk niveau is bereikbaar."""
        return set(range(len(NIVEAU_CM)))

    def volgend_standpunt(self, zoeker: Zoeker) -> Marker | bool:
        """Vlieg naar het standpunt dat de kaart kiest, en pas het hoogteniveau aan.

        Geeft True na een verplaatsing, False als de kaart niets zinvols meer ziet, of een Marker als er onderweg
        een kruis in beeld kwam.
        """
        if (besluit := self.kaart.kies(self.niveau, self.mogelijke_niveaus())) is None:
            return False
        stap(f"kaart kiest {self.kaart.midden(besluit.doel)} m, niveau {besluit.niveau}, verwachte winst {besluit.winst:.0%}")
        for knik in rechte_stukken(besluit.route):
            peiling, afstand = peiling_en_afstand((self.kaart.x, self.kaart.y), self.kaart.midden(knik))
            if afstand < 0.1:
                continue
            self.draai_naar((peiling - self.koers) % 360)
            gestopt_voor_muur = self.kaart.wand.sum()
            if (gezien := self.vooruit(afstand / (VOORUIT_RC * RC_M_PER_S), zoeker=zoeker)) is not None:
                return gezien
            if self.kaart.wand.sum() != gestopt_voor_muur:
                break  # Muur in de weg: hier scannen in plaats van doorvliegen.
        if besluit.niveau != self.niveau:
            self.naar_niveau(besluit.niveau)
        return True

    def begrens_dalen(self, rc: Rc) -> Rc:
        """Daal in totaal maximaal DAAL_BUDGET_S en nooit onder MIN_HOOGTE_CM (als de meting klopt)."""
        if rc.ud >= 0:
            return rc
        hoogte = self.tello.get_height()
        if self.daal_s <= 0 or 0 < hoogte < MIN_VLOER_CM:
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
        rc, laag, dichtbij, herstel_start, vooruit_s, gezien_op = STIL, 0, 0, None, 0.0, start
        reden: str | None = None
        while time.monotonic() - start < timeout_s and reden is None:
            frame = self.camera.frame
            marker = zoeker(frame)
            nu = time.monotonic()
            vooruit_s += (nu - vorig) * (rc.fb > 0)
            vorig = nu
            onderweg = vooruit_s >= MIN_VOORUIT_S  # Aankomst telt pas nadat we echt naar het kruis gevlogen hebben.
            if marker is not None and marker.score >= SCORE_TONEN and slot.past(marker):  # Eenmaal vergrendeld: 50% volstaat.
                laatste, herstel_start, slot.laatste, gezien_op = marker, None, marker, nu
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
                laag, dichtbij, kwijt_s = 0, 0, nu - gezien_op
                if kwijt_s < KWIJT_S:
                    self.stuur(rc)  # Kort kwijt: koers houden.
                elif onderweg and is_erboven_verdwenen(laatste):
                    reden = "erboven"
                elif kwijt_s < KWIJT_S + STIL_ZOEK_S:
                    rc = STIL
                    self.stuur(STIL)  # Eerst stilhangen: bij het vooruitvliegen kantelt de camera en is het beeld onscherp.
                elif herstel_start is None or nu - herstel_start < HERSTEL_S:
                    herstel_start = herstel_start or nu
                    slot.laatste = None  # Ontgrendel: elk goed kruis mag weer.
                    richting = -1 if laatste is not None and laatste.x < 0 else 1
                    self.stuur(Rc(0, 0, 0, richting * HERSTEL_RC))  # Draai naar waar het kruis het laatst was.
                else:
                    if laatste is not None:
                        stap(f"kruis kwijt: laatst x {laatste.x:.2f}, y {laatste.y:.2f}, straal {laatste.straal:.2f}, {vooruit_s:.1f} s vooruit")
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
