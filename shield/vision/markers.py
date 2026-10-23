"""Geel en groen marker herkennen in een Tello-frame.

Het Tello-frame van djitellopy is RGB. Daarom gebruiken we RGB2HSV;
met BGR zou het beeld blauwig en de kleurherkenning fout zijn.
"""

from typing import NamedTuple

import cv2
import numpy as np

SCHAAL = 3  # Frame 960x720 -> 320x240: ~9x minder pixels, genoeg voor tape.
MIN_OPPERVLAK = 60  # Pixels in het verkleinde beeld.

# Zelfde kleurbereiken als de oude marker_test.
GEEL = ((18, 70, 70), (40, 255, 255))
GROEN = ((35, 45, 40), (90, 255, 255))


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
    """Zwaartepunt en grootte van het masker, of None als er te weinig is."""
    momenten = cv2.moments(masker, binaryImage=True)
    oppervlak = momenten["m00"]
    if oppervlak < MIN_OPPERVLAK:
        return None
    hoogte, breedte = masker.shape
    x = momenten["m10"] / oppervlak / breedte * 2 - 1
    y = momenten["m01"] / oppervlak / hoogte * 2 - 1
    return Marker(x, y, oppervlak / (hoogte * breedte))


def vind_marker(frame_rgb: np.ndarray, bereik: tuple) -> Marker | None:
    """Vind een marker met de gegeven kleur in een RGB-frame."""
    return marker_uit_masker(kleur_masker(verklein(frame_rgb), bereik))


def vind_geel(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, GEEL)


def vind_groen(frame_rgb: np.ndarray) -> Marker | None:
    return vind_marker(frame_rgb, GROEN)
