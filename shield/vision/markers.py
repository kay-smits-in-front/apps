"""Geel en groen kruis (X) herkennen in een Tello-frame.

Het Tello-frame van djitellopy is RGB. Daarom gebruiken we RGB2HSV;
met BGR zou het beeld blauwig en de kleurherkenning fout zijn.

Een kleurvlek is nog geen kruis. Een kandidaat telt pas mee als de vorm klopt:
  1. vier armen op 35% van de straal      (een X of + snijdt een cirkel 4 keer)
  2. vier armen op 65% van de straal
  3. gevuld midden                       (een vierkant of ring is daar leeg)
  4. dun                                 (een boek of vlek is massief)
  5. ongeveer even breed als hoog
Score = aantal eisen / 5. Dat werkt voor elke draaiing, ook als de X als + in beeld staat.
"""

from typing import NamedTuple

import cv2
import numpy as np

SCHAAL = 2  # Frame 960x720 -> 480x360.
MIN_OPPERVLAK = 25  # Pixels in het verkleinde beeld.
MIN_STRAAL = 6  # Kleinste kruis (pixels van midden tot arm-uiteinde) dat we beoordelen.
MAX_KANDIDATEN = 6
SCORE_TONEN = 0.4  # Vanaf hier tekenen we de kandidaat in het live beeld.
SCORE_GEVONDEN = 0.8  # Vanaf hier is het een kruis: 4 van de 5 eisen kloppen.

# Zelfde kleurbereiken als de oude marker_test. Geel begint op hue 22: de oranje houten vloer
# ligt onder warm licht rond hue 10-18.
GEEL = ((22, 70, 70), (40, 255, 255))
GROEN = ((35, 45, 40), (90, 255, 255))

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


def aantal_armen(vlek: np.ndarray, cx: float, cy: float, straal: float) -> int:
    """Hoe vaak de vlek een cirkel rond (cx, cy) kruist. -1 als de cirkel buiten het beeld valt."""
    xs = np.rint(cx + straal * _COS).astype(int)
    ys = np.rint(cy + straal * _SIN).astype(int)
    hoogte, breedte = vlek.shape
    if xs.min() < 0 or ys.min() < 0 or xs.max() >= breedte or ys.max() >= hoogte:
        return -1
    rij = vlek[ys, xs]
    return int(np.sum(rij & ~np.roll(rij, 1)))


def kruis_score(vlek: np.ndarray, cx: float, cy: float, oppervlak: int, breedte: int, hoogte: int) -> float:
    """Score 0..1 hoe goed deze vlek een kruis is (zie de eisen bovenaan)."""
    ys, xs = np.nonzero(vlek)
    straal = float(np.hypot(xs - cx, ys - cy).max())
    if straal < MIN_STRAAL:
        return 0.0
    eisen = (
        aantal_armen(vlek, cx, cy, 0.35 * straal) == 4,
        aantal_armen(vlek, cx, cy, 0.65 * straal) == 4,
        bool(vlek[int(round(cy)) - 1:int(round(cy)) + 2, int(round(cx)) - 1:int(round(cx)) + 2].any()),
        0.04 <= oppervlak / (np.pi * straal**2) <= 0.45,
        0.5 <= breedte / max(hoogte, 1) <= 2.0,
    )
    return sum(eisen) / len(eisen)


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
        s = kruis_score(vlek, cx - xa, cy - ya, int(oppervlak), int(b), int(h))
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
