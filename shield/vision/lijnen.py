"""Kruis herkennen aan de figuur: lijnen die in één punt samenkomen, met kleur als steun.

Waarom: een dun kruis verliest op afstand zijn kleur (videocompressie bewaart kleur op halve resolutie),
maar de lijnen blijven zichtbaar. Stappen, elk in een eigen functie:
  1. roze_kans    zachte kleurscore per pixel (0..255), geen harde drempel
  2. segmenten    LSD (Line Segment Detector) vindt rechte stukjes in die kaart
  3. lijnen       segmenten met bijna dezelfde hoek en positie worden één lijn (een tape heeft twee randen)
  4. kruis_uit_lijnen   zoek een punt waar minstens 3 armen samenkomen
"""

from typing import NamedTuple

import cv2
import numpy as np

from shield.vision.markers import ARMEN_OK, Marker

HUE_ROZE = 168  # Gemeten op echte Tello-beelden (hue 162-173).
HUE_BREEDTE = 9
MIN_SEGMENT = 10  # Pixels.
MIN_ARM = 10  # Kortste arm (pixels) die meetelt.
HOEK_TOL = np.radians(10)  # Segmenten binnen deze hoek horen bij dezelfde lijn.
AFSTAND_TOL = 8  # Pixels tussen twee randen van één tape.
MIDDEN_STRAAL = 14  # Armen moeten binnen deze afstand van het kruispunt beginnen of erdoorheen gaan.
MIN_HOEK_TUSSEN_LIJNEN = np.radians(25)
ARM_HOEK_TOL = np.radians(25)  # Armen binnen deze hoek van elkaar zijn dezelfde arm.
CIRKEL_DELEN = (0.3, 0.45, 0.6, 0.75, 0.9)  # Aandelen van de blob-straal waarop de cirkel wordt gemeten.
ARM_KANS = 50  # Zo roze moet een pixel op de arm minstens zijn.
ARM_AANDEEL = 0.7  # Zo groot deel van het eerste stuk van elke arm moet roze zijn.
MIN_PIXELS_KANS = 30  # Minder roze pixels dan dit: geen kruis, sla LSD over.

_LSD = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)


class Lijn(NamedTuple):
    """Een rechte lijn: een punt, een richting (lengte 1) en waar hij begint en eindigt langs die richting."""

    punt: np.ndarray
    richting: np.ndarray
    begin: float
    eind: float


def roze_kans(frame_rgb: np.ndarray) -> np.ndarray:
    """Zachte score 0..255: hoe roze is elke pixel (hue dicht bij roze, genoeg kleur, niet te donker)."""
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    kans = np.exp(-(((h - HUE_ROZE) / HUE_BREEDTE) ** 2)) * np.clip((s - 20) / 40, 0, 1) * np.clip((v - 70) / 60, 0, 1)
    return (kans * 255).astype(np.uint8)


def segmenten(kans: np.ndarray) -> np.ndarray:
    """Rechte stukjes (x1, y1, x2, y2) in de kansenkaart, minstens MIN_SEGMENT lang."""
    if np.count_nonzero(kans > 100) < MIN_PIXELS_KANS:
        return np.zeros((0, 4))
    gevonden = _LSD.detect(kans)[0]
    if gevonden is None:
        return np.zeros((0, 4))
    s = gevonden.reshape(-1, 4)
    return s[np.hypot(s[:, 2] - s[:, 0], s[:, 3] - s[:, 1]) >= MIN_SEGMENT]


def lijnen(s: np.ndarray) -> list[Lijn]:
    """Voeg segmenten met bijna dezelfde hoek en positie samen tot lijnen (langste eerst)."""
    if len(s) == 0:
        return []
    v = s[:, 2:] - s[:, :2]
    lengte = np.hypot(v[:, 0], v[:, 1])
    hoek = np.arctan2(v[:, 1], v[:, 0]) % np.pi
    normaal = np.stack([-np.sin(hoek), np.cos(hoek)], axis=1)
    afstand = (s[:, :2] * normaal).sum(axis=1)
    vrij = np.ones(len(s), bool)
    resultaat = []
    for i in np.argsort(-lengte):
        if not vrij[i]:
            continue
        verschil = np.abs((hoek - hoek[i] + np.pi / 2) % np.pi - np.pi / 2)
        groep = vrij & (verschil < HOEK_TOL) & (np.abs(afstand - afstand[i]) < AFSTAND_TOL)
        vrij &= ~groep
        richting = np.array([np.cos(hoek[i]), np.sin(hoek[i])])
        eindpunten = np.vstack([s[groep, :2], s[groep, 2:]])
        midden = eindpunten.mean(axis=0)
        langs = (eindpunten - midden) @ richting
        resultaat.append(Lijn(midden, richting, float(langs.min()), float(langs.max())))
    return resultaat


def armen_bij(punt: np.ndarray, alle: list[Lijn]) -> list[tuple[np.ndarray, float]]:
    """Armen (richting als eenheidsvector, lengte) die bij `punt` samenkomen.

    Een lijn die door het punt loopt geeft twee armen, een lijn die er begint of eindigt één.
    """
    armen: list[tuple[np.ndarray, float]] = []
    for lijn in alle:
        langs = float((punt - lijn.punt) @ lijn.richting)
        w = punt - lijn.punt
        dwars = abs(float(w[0] * lijn.richting[1] - w[1] * lijn.richting[0]))
        if dwars > MIDDEN_STRAAL:
            continue
        naar_eind, naar_begin = lijn.eind - langs, langs - lijn.begin
        if naar_eind >= MIN_ARM:
            armen.append((lijn.richting, naar_eind))
        if naar_begin >= MIN_ARM:
            armen.append((-lijn.richting, naar_begin))
    return armen


def unieke_armen(armen: list[tuple[np.ndarray, float]]) -> list[tuple[np.ndarray, float]]:
    """Armen die bijna dezelfde kant op wijzen tellen als één arm (de langste blijft over)."""
    uniek: list[tuple[np.ndarray, float]] = []
    for arm in sorted(armen, key=lambda a: -a[1]):
        if all(np.arccos(np.clip(arm[0] @ ander[0], -1, 1)) > ARM_HOEK_TOL for ander in uniek):
            uniek.append(arm)
    return uniek


def snijpunten(alle: list[Lijn]) -> list[np.ndarray]:
    """Plekken waar twee lijnen (bijna) elkaar raken of kruisen: kandidaat-midden van een kruis."""
    punten = []
    for i, a in enumerate(alle):
        for b in alle[i + 1:]:
            kruisproduct = a.richting[0] * b.richting[1] - a.richting[1] * b.richting[0]
            if abs(kruisproduct) < np.sin(MIN_HOEK_TUSSEN_LIJNEN):
                continue
            w = b.punt - a.punt
            t = (w[0] * b.richting[1] - w[1] * b.richting[0]) / kruisproduct
            u = (w[0] * a.richting[1] - w[1] * a.richting[0]) / kruisproduct
            if a.begin - MIDDEN_STRAAL <= t <= a.eind + MIDDEN_STRAAL and b.begin - MIDDEN_STRAAL <= u <= b.eind + MIDDEN_STRAAL:
                punten.append(a.punt + t * a.richting)
    return punten


def arm_is_roze(kans: np.ndarray, punt: np.ndarray, richting: np.ndarray) -> bool:
    """Loopt de arm vanaf het kruispunt over roze? (Raaklijnen van een ring beginnen in het lege gat.)"""
    stappen = np.arange(0, MIN_ARM + 1)
    xs = np.rint(punt[0] + stappen * richting[0]).astype(int)
    ys = np.rint(punt[1] + stappen * richting[1]).astype(int)
    hoogte, breedte = kans.shape
    binnen = (xs >= 1) & (xs < breedte - 1) & (ys >= 1) & (ys < hoogte - 1)
    if not binnen.all():
        return True  # Arm loopt het beeld uit: niet te beoordelen, dus niet afkeuren.
    buurt = np.maximum.reduce([kans[ys + dy, xs + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    return float((buurt >= ARM_KANS).mean()) >= ARM_AANDEEL


def keer_roze_op_cirkel(vlek: np.ndarray, punt: np.ndarray, straal: float) -> int:
    """Hoe vaak loopt een cirkel rond `punt` de roze vlek in? -1 als de cirkel buiten het beeld valt.

    Er wordt elke ~1 pixel bemonsterd, zodat ook een tape van 2-3 pixels breed niet tussen de metingen valt.
    """
    n = max(72, int(2 * np.pi * straal))
    hoek = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xs = np.rint(punt[0] + straal * np.cos(hoek)).astype(int)
    ys = np.rint(punt[1] + straal * np.sin(hoek)).astype(int)
    hoogte, breedte = vlek.shape
    if xs.min() < 0 or ys.min() < 0 or xs.max() >= breedte or ys.max() >= hoogte:
        return -1
    rij = vlek[ys, xs]
    return int(np.sum(rij & ~np.roll(rij, 1)))


def blob_straal(vlek: np.ndarray, punt: np.ndarray) -> float:
    """Afstand van `punt` tot de verste pixel van de roze vlek waar het punt in (of vlak naast) ligt. 0 = geen vlek."""
    _, labels = cv2.connectedComponents(vlek.astype(np.uint8), connectivity=8)
    x, y = int(round(punt[0])), int(round(punt[1]))
    buurt = labels[max(y - 3, 0):y + 4, max(x - 3, 0):x + 4]
    soorten = buurt[buurt > 0]
    if soorten.size == 0:
        return 0.0
    ys, xs = np.nonzero(labels == np.bincount(soorten).argmax())
    return float(np.hypot(xs - punt[0], ys - punt[1]).max())


def past_bij_kruis(kans: np.ndarray, punt: np.ndarray) -> bool:
    """Snijdt een cirkel rond het punt de roze vlek 3 of 4 keer? Een sticker (massief) of ring (gat) faalt.

    Een dun kruis valt uiteen vlak bij het midden, een dik kruis pas dicht bij de uiteinden. Daarom meten we op
    vijf stralen tussen 30 en 90% van de vlek en eisen we het op minstens twee ervan.
    """
    vlek = cv2.dilate((kans > ARM_KANS).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    straal = blob_straal(vlek, punt)
    if straal < MIN_ARM:
        return False
    tellingen = [keer_roze_op_cirkel(vlek, punt, f * straal) for f in CIRKEL_DELEN]
    return sum(n in (*ARMEN_OK, -1) for n in tellingen) >= 2


def kruis_uit_lijnen(alle: list[Lijn], kans: np.ndarray) -> Marker | None:
    """Beste kruis: het snijpunt met de meeste verschillende armen (3 = 85%, 4 = 100%)."""
    hoogte, breedte = kans.shape
    beste: Marker | None = None
    for punt in snijpunten(alle):
        armen = unieke_armen([a for a in armen_bij(punt, alle) if arm_is_roze(kans, punt, a[0])])
        score = 1.0 if len(armen) >= 4 else 0.85  # 3 armen: een arm ligt in de schaduw of buiten beeld.
        opposite = any(a[0] @ b[0] < -0.5 for a in armen for b in armen)  # Minstens één lijn loopt door het punt.
        if len(armen) >= 3 and opposite and (beste is None or score > beste.score) and past_bij_kruis(kans, punt):
            beste = Marker(punt[0] / breedte * 2 - 1, punt[1] / hoogte * 2 - 1, 0.0, score)
    return beste


def vind_kruis_lijnen(frame_rgb: np.ndarray) -> Marker | None:
    """Kruis zoeken op de figuur (lijnen), met roze als kaart waarin we de lijnen zoeken."""
    kans = roze_kans(frame_rgb)
    return kruis_uit_lijnen(lijnen(segmenten(kans)), kans)
