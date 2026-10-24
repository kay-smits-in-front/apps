"""Geel en groen marker herkennen in een Tello-frame.

Het Tello-frame van djitellopy is RGB. Daarom gebruiken we RGB2HSV;
met BGR zou het beeld blauwig en de kleurherkenning fout zijn.
"""

from typing import NamedTuple

import cv2
import numpy as np

SCHAAL = 3  # Frame 960x720 -> 320x240: ~9x minder pixels, genoeg voor tape.
MIN_OPPERVLAK = 60  # Pixels in het verkleinde beeld.
MAX_AANDEEL = 0.4  # Meer dan dit deel van het beeld is vloer of muur, geen tape.

# Zelfde kleurbereiken als de oude marker_test.
# Geel begint op hue 22: de oranje houten vloer ligt onder warm licht rond hue 10-18.
GEEL = ((22, 70, 70), (40, 255, 255))
GROEN = ((35, 45, 40), (90, 255, 255))


# Score: hoeveel van het beeld de marker vult, relatief aan een duidelijk zichtbare marker.
SCORE_REF = 0.01  # Marker vult 1% van het beeld = score 100%. Aan te passen met het live beeld.
SCORE_INTERESSANT = 0.3  # Vanaf hier is het geen toeval meer: gericht naar toe vliegen.


class Marker(NamedTuple):
    """Positie van een marker. x en y lopen van -1 (links/boven) tot 1 (rechts/onder)."""

    x: float
    y: float
    oppervlak: float  # Aandeel van het beeld (0..1).


def verklein(frame_rgb: np.ndarray) -> np.ndarray:
    """Neem elke SCHAAL-de pixel: een view, dus geen kopie en geen rekentijd."""
    return frame_rgb[::SCHAAL, ::SCHAAL]


def kleur_masker(frame_rgb: np.ndarray, bereik: tuple) -> np.ndarray:
    """Binair masker van alle pixels binnen het HSV-bereik."""
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    return cv2.inRange(hsv, *bereik)


def marker_uit_masker(masker: np.ndarray) -> Marker | None:
    """Zwaartepunt en grootte van het grootste vlek in het masker, of None."""
    aantal, _, stats, zwaartepunten = cv2.connectedComponentsWithStats(masker)
    if aantal < 2:
        return None
    grootste = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    oppervlak = stats[grootste, cv2.CC_STAT_AREA]
    hoogte, breedte = masker.shape
    if oppervlak < MIN_OPPERVLAK or oppervlak > MAX_AANDEEL * hoogte * breedte:
        return None
    x, y = zwaartepunten[grootste]
    return Marker(x / breedte * 2 - 1, y / hoogte * 2 - 1, oppervlak / (hoogte * breedte))


def vind_marker(frame_rgb: np.ndarray, bereik: tuple) -> Marker | None:
    """Vind een marker met de gegeven kleur in een RGB-frame."""
    return marker_uit_masker(kleur_masker(verklein(frame_rgb), bereik))


def vind_geel(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, GEEL)


def vind_groen(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, GROEN)


def score(marker: Marker) -> float:
    """Zoekscore 0..1: 0 = niets, ~0.01 = te weinig, 0.3 = interessant, 1 = duidelijk in beeld."""
    return min(1.0, marker.oppervlak / SCORE_REF)
