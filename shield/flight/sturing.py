"""Pure rekenfuncties voor de sturing. Geen drone nodig, dus testbaar."""

from typing import NamedTuple

import numpy as np

from shield.vision.markers import Marker

DOEL_Y = 0.5  # Gewenste hoogte van het kruis in beeld (0 = midden, 1 = onderrand).
KP_YAW = 45.0
KP_HOOGTE = 40.0
VOORUIT_SNEL = 15
MAX_DAAL = -20
MAX_STIJG = 0  # Tijdens het naderen alleen dalen, nooit stijgen.
CENTREER_X = 0.25  # Alleen vooruit vliegen als het kruis minstens zo dicht bij het midden staat.
NAAST_STRAAL = 0.20  # Kruis zo groot (halve breedte als aandeel van het beeld, ~40-50 cm): stop ervoor.
REMMEN_STRAAL = 0.10  # Vanaf deze grootte rustiger vooruit.
VOORUIT_LANGZAAM = 8
EINDE_ONDERIN_Y = 0.55  # Kruis onderin beeld verdwenen na deze hoogte: we zijn erboven.
MIN_STRAAL_BIJ_VERLIES = 0.04  # ...maar alleen als het kruis eerst groot genoeg in beeld was.
OVER_HET_KRUIS_S = 0.8  # Daarna zo lang nog vooruit voor we landen.
ROND_RC = 30  # Draaisnelheid bij rondkijken (ongeveer graden per seconde).
MAX_RC = 100

# Zoeken: per standpunt een 360-scan, dan naar de meest open richting en een ander hoogteniveau.
ZOEK_VOORUIT_S = 4.0  # Vooruit naar het volgende standpunt (stopt eerder bij een muur).
MIN_ZOEK_CM = 40  # Niet lager zoeken dan dit (gemeten hoogte).
MAX_ZOEK_CM = 160  # Niet hoger zoeken dan dit.
MAX_NETTO_S = 2.0  # Als de hoogtemeting 0 geeft: nooit meer dan zoveel seconden netto stijgen of dalen.
START_OMHOOG_S = 0.8  # Kleine stijging voor de eerste scan.
HOOGTE_RC = 30
HOOGTE_S = 1.0  # Eén stap omhoog of omlaag tussen twee scans.
MAX_RONDES = 6  # Maximaal aantal standpunten voor we opgeven.
PRIORITEIT_FRAMES = 3  # Zo veel beelden achter elkaar 'lijkt op een kruis' (score >= SCORE_TONEN): stop met draaien.
VERIFIEER_S = 5.0  # Zo lang rustig naar een mogelijk kruis toe vliegen om te zien of het er echt een is.
GENEGEERD_GRADEN = 25  # Na een vals alarm negeren we kandidaten binnen zoveel graden van die richting.
HERSTEL_RC = 25  # Draaisnelheid om een kwijtgeraakt kruis terug te vinden.
HERSTEL_S = 2.5
SPOOR_SPRONG = 0.25  # Zo ver mag een kruis tussen twee beelden verspringen tijdens de scan (-1..1).
SLOT_SPRONG = 0.35  # Idem tijdens het naderen: een kruis dat verder springt is een ander kruis.


class Rc(NamedTuple):
    """Waarden voor send_rc_control: links/rechts, voor/achter, omhoog/omlaag, yaw."""

    lr: int
    fb: int
    ud: int
    yaw: int


STIL = Rc(0, 0, 0, 0)

# Drift-demping: tegenstuur op de gemeten snelheid. Het teken hangt af van de assen van de
# Tello; klopt het niet (drone drijft harder weg), draai dan TEKEN_FB of TEKEN_LR om.
KP_DEMP = 5.0
MAX_DEMP = 25
TEKEN_FB = -1
TEKEN_LR = 1


def begrens(waarde: float) -> int:
    return int(np.clip(waarde, -MAX_RC, MAX_RC))


def naar_marker(marker: Marker) -> Rc:
    """Draai naar het kruis, vlieg vooruit als het in het midden staat, houd het op DOEL_Y."""
    yaw = begrens(KP_YAW * marker.x)
    ud = int(np.clip(-KP_HOOGTE * (marker.y - DOEL_Y), MAX_DAAL, MAX_STIJG))
    snelheid = VOORUIT_LANGZAAM if marker.straal >= REMMEN_STRAAL else VOORUIT_SNEL
    fb = snelheid if abs(marker.x) < CENTREER_X else 0
    return Rc(0, fb, ud, yaw)


def is_dichtbij(marker: Marker) -> bool:
    """Is het kruis zo groot in beeld dat we er vlak voor staan? (Ook voor een kruis op een muur of kast.)"""
    return marker.straal >= NAAST_STRAAL


def is_erboven_verdwenen(laatste: Marker | None) -> bool:
    """Verdween het kruis onderin het beeld, nadat we het van dichtbij zagen? Dan vliegen we erboven."""
    return laatste is not None and laatste.y >= EINDE_ONDERIN_Y and laatste.straal >= MIN_STRAAL_BIJ_VERLIES


def demping(vx: float, vy: float) -> Rc:
    """Tegenstuurcommando om de gemeten snelheid (vx voor/achter, vy zijwaarts) af te remmen."""
    lr = int(np.clip(TEKEN_LR * KP_DEMP * vy, -MAX_DEMP, MAX_DEMP))
    fb = int(np.clip(TEKEN_FB * KP_DEMP * vx, -MAX_DEMP, MAX_DEMP))
    return Rc(lr, fb, 0, 0)


def corrigeer(rc: Rc, vx: float, vy: float) -> Rc:
    """Demp alleen de assen waarop we niets bewust commanderen."""
    d = demping(vx, vy)
    return Rc(rc.lr or d.lr, rc.fb or d.fb, rc.ud, rc.yaw)


RICHTING = {
    "omhoog": Rc(0, 0, HOOGTE_RC, 0),
    "omlaag": Rc(0, 0, -HOOGTE_RC, 0),
}


def verticale_opties(hoogte_cm: float, netto_s: float) -> list[str]:
    """Waarheen kan de drone verticaal? Hoogte 0 = onbekend: dan telt het netto stijgen/dalen."""
    omhoog = (hoogte_cm <= 0 or hoogte_cm < MAX_ZOEK_CM) and netto_s < MAX_NETTO_S
    omlaag = (hoogte_cm <= 0 or hoogte_cm > MIN_ZOEK_CM) and netto_s > -MAX_NETTO_S
    return (["omhoog"] if omhoog else []) + (["omlaag"] if omlaag else [])
