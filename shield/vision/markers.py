"""Geel en groen kruis (X) herkennen in een Tello-frame.

Het Tello-frame van djitellopy is RGB. Daarom gebruiken we RGB2HSV;
met BGR zou het beeld blauwig en de kleurherkenning fout zijn.

Een kleurvlek is nog geen kruis. Een kandidaat telt pas mee als de vorm klopt. Omdat de drone het
kruis schuin van boven ziet (platgedrukt, gedraaid), meten we in een "witte" ruimte: de vlek wordt
eerst omgerekend zodat hij rond is, en dan pas beoordeeld. Eisen:
  1. vier armen op 30% van de straal      (een X of + snijdt een cirkel 4 keer)
  2. vier armen op 50% van de straal      (verplicht)
  3. vier armen op 70% van de straal
  4. gevuld midden                       (een vierkant of ring is daar leeg)
  5. dun                                 (een boek of vlek is massief)
  6. geen streep                         (niet alleen in een richting uitgerekt)
Score = aantal eisen / 6, maximaal 50% zolang eis 2 niet klopt.
"""

from typing import NamedTuple

import cv2
import numpy as np

SCHAAL = 2  # Frame 960x720 -> 480x360.
MIN_OPPERVLAK = 40  # Pixels in het verkleinde beeld.
MIN_STRAAL = 8  # Kleinste kruis (pixels van midden tot arm-uiteinde) dat we beoordelen.
MIN_VORM = 0.08  # Kleinste verhouding tussen de korte en lange as van de vlek (1 = rond).
MAX_KANDIDATEN = 6
SCORE_TONEN = 0.5  # Vanaf hier tekenen we de kandidaat in het live beeld.
SCORE_GEVONDEN = 0.8  # Vanaf hier is het een kruis: minstens 5 van de 6 eisen kloppen.

# Zelfde kleurbereiken als de oude marker_test. Geel begint op hue 22: de oranje houten vloer
# ligt onder warm licht rond hue 10-18.
GEEL = ((22, 70, 70), (40, 255, 255))
GROEN = ((35, 45, 40), (90, 255, 255))
# Roze/magenta ligt op hue 145-175: boven de blauwpaarse muur (hue ~120-130) en onder rood (hue 0-10, 175+).
ROZE = ((145, 70, 80), (175, 255, 255))

_PUNTEN = 72
_HOEK = np.linspace(0, 2 * np.pi, _PUNTEN, endpoint=False)
_COS, _SIN = np.cos(_HOEK), np.sin(_HOEK)
_SLUITEN = np.ones((3, 3), np.uint8)


class Marker(NamedTuple):
    """Een gevonden kruis. x en y lopen van -1 (links/boven) tot 1 (rechts/onder)."""

    x: float
    y: float
    oppervlak: float  # Aandeel van het beeld (0..1).
    score: float = 1.0  # Hoe goed de vorm een kruis is (0..1).


def verklein(frame_rgb: np.ndarray) -> np.ndarray:
    """Neem elke SCHAAL-de pixel: een view, dus geen kopie en geen rekentijd."""
    return frame_rgb[::SCHAAL, ::SCHAAL]


def kleur_masker(frame_rgb: np.ndarray, bereik: tuple) -> np.ndarray:
    """Binair masker van alle pixels binnen het HSV-bereik, met kleine gaatjes gedicht."""
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    return cv2.morphologyEx(cv2.inRange(hsv, *bereik), cv2.MORPH_CLOSE, _SLUITEN)


def aantal_armen(vlek: np.ndarray, midden: np.ndarray, vorm: np.ndarray, straal: float) -> int:
    """Hoe vaak de vlek de ellips rond `midden` kruist. -1 als die buiten het beeld valt.

    `vorm` is de matrix die de ronde cirkel in de scheve ellips van de vlek omzet.
    """
    punten = midden[:, None] + vorm @ (straal * np.vstack([_COS, _SIN]))
    xs, ys = np.rint(punten[0]).astype(int), np.rint(punten[1]).astype(int)
    hoogte, breedte = vlek.shape
    if xs.min() < 0 or ys.min() < 0 or xs.max() >= breedte or ys.max() >= hoogte:
        return -1
    rij = vlek[ys, xs]
    rij = rij | (np.roll(rij, 1) & np.roll(rij, -1))  # Gaatje van 1 meting dichten.
    rij = rij & (np.roll(rij, 1) | np.roll(rij, -1))  # Losse enkele meting weghalen.
    return int(np.sum(rij & ~np.roll(rij, 1)))


def kruis_score(vlek: np.ndarray, cx: float, cy: float, oppervlak: int) -> float:
    """Score 0..1 hoe goed deze vlek een kruis is (zie de eisen bovenaan)."""
    ys, xs = np.nonzero(vlek)
    punten = np.stack([xs - cx, ys - cy]).astype(float)
    if np.hypot(*punten).max() < MIN_STRAAL:
        return 0.0
    covariantie = punten @ punten.T / punten.shape[1]
    assen = np.linalg.eigvalsh(covariantie)
    if assen[0] <= 1e-6:
        return 0.0
    vorm = np.linalg.cholesky(covariantie)
    rond = np.linalg.solve(vorm, punten)  # De vlek omgerekend naar een ronde ruimte.
    straal = float(np.hypot(*rond).max())
    midden = np.array([cx, cy])
    armen = [aantal_armen(vlek, midden, vorm, f * straal) for f in (0.3, 0.5, 0.7)]
    vulling = oppervlak / (np.sqrt(np.linalg.det(covariantie)) * np.pi * straal**2)
    eisen = (
        armen[0] == 4,
        armen[1] == 4,
        armen[2] == 4,
        bool(vlek[int(round(cy)) - 1:int(round(cy)) + 2, int(round(cx)) - 1:int(round(cx)) + 2].any()),
        0.04 <= vulling <= 0.45,
        assen[0] / assen[1] >= MIN_VORM,
    )
    score = sum(eisen) / len(eisen)
    return score if eisen[1] else min(score, 0.5)


def marker_uit_masker(masker: np.ndarray) -> Marker | None:
    """Beste kruis-kandidaat in het masker, of None. Beoordeelt de grootste vlekken op vorm."""
    aantal, labels, stats, zwaartepunten = cv2.connectedComponentsWithStats(masker)
    if aantal < 2:
        return None
    hoogte, breedte = masker.shape
    volgorde = 1 + np.argsort(stats[1:, cv2.CC_STAT_AREA])[::-1][:MAX_KANDIDATEN]
    beste: Marker | None = None
    for i in volgorde:
        x0, y0, b, h, oppervlak = stats[i]
        if oppervlak < MIN_OPPERVLAK:
            break
        cx, cy = zwaartepunten[i]
        marge = int(max(b, h)) + 2  # De cirkels kunnen net buiten de bounding box vallen.
        ya, yb = max(y0 - marge, 0), min(y0 + h + marge, hoogte)
        xa, xb = max(x0 - marge, 0), min(x0 + b + marge, breedte)
        vlek = labels[ya:yb, xa:xb] == i
        s = kruis_score(vlek, cx - xa, cy - ya, int(oppervlak))
        if s >= SCORE_TONEN and (beste is None or s > beste.score):
            beste = Marker(cx / breedte * 2 - 1, cy / hoogte * 2 - 1, oppervlak / (hoogte * breedte), s)
    return beste


def vind_marker(frame_rgb: np.ndarray, bereik: tuple) -> Marker | None:
    """Vind het beste kruis met de gegeven kleur in een RGB-frame."""
    return marker_uit_masker(kleur_masker(verklein(frame_rgb), bereik))


def vind_geel(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, GEEL)


def vind_groen(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, GROEN)


def vind_roze(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, ROZE)
