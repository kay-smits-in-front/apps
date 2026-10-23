"""Verbinden met de Tello en de vluchtstappen die test_1 en test_2 delen."""

import time
from contextlib import contextmanager
from typing import Callable, Iterator

import numpy as np
from djitellopy import Tello

from shield.flight.sturing import STIL, Rc, naar_marker, zoek_dalen, zoek_draaien
from shield.vision.markers import Marker

MIN_BATTERIJ = 40
MIN_HOOGTE_CM = 25
LOOP_TIJD_S = 0.03  # ~30 Hz; de camera levert maar ~30 fps.
LANDEN_Y = 0.75  # Marker zo laag in beeld: bijna boven de marker.
LAATSTE_METERS_CM = 20  # Blind vooruit als de marker onder de camera verdwijnt.

Zoeker = Callable[[np.ndarray], Marker | None]


@contextmanager
def drone_met_camera() -> Iterator[tuple[Tello, object]]:
    """Verbind, zet de camera aan voor het opstijgen en land altijd bij een fout."""
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
        yield tello, camera
    finally:
        if tello.is_flying:
            tello.send_rc_control(*STIL)
            tello.land()
        tello.streamoff()
        tello.end()


def stuur(tello: Tello, rc: Rc) -> None:
    tello.send_rc_control(*rc)


def zoek_marker(tello: Tello, camera, zoeker: Zoeker, zoek_actie: Callable[[], Rc], timeout_s: float) -> Marker:
    """Voer zoek_actie uit tot de marker zichtbaar is. Faalt na timeout of te lage hoogte."""
    einde = time.monotonic() + timeout_s
    while time.monotonic() < einde:
        if (marker := zoeker(camera.frame)) is not None:
            stuur(tello, STIL)
            return marker
        if tello.get_height() < MIN_HOOGTE_CM:
            break
        stuur(tello, zoek_actie())
        time.sleep(LOOP_TIJD_S)
    stuur(tello, STIL)
    raise TimeoutError("Marker niet gevonden.")


def zoek_door_dalen(tello: Tello, camera, zoeker: Zoeker, timeout_s: float = 20) -> Marker:
    return zoek_marker(tello, camera, zoeker, zoek_dalen, timeout_s)


def zoek_door_draaien(tello: Tello, camera, zoeker: Zoeker, timeout_s: float = 25) -> Marker:
    """Eén volledige draai kost ~15 s bij snelheid 25."""
    return zoek_marker(tello, camera, zoeker, zoek_draaien, timeout_s)


def vlieg_en_land(tello: Tello, camera, zoeker: Zoeker, timeout_s: float = 30) -> None:
    """Volg de marker; zodra hij laag in beeld is of onderin verdwijnt: laatste stuk en landen."""
    einde = time.monotonic() + timeout_s
    laatste: Marker | None = None
    while time.monotonic() < einde:
        marker = zoeker(camera.frame)
        if marker is None:
            if laatste is not None and laatste.y > LANDEN_Y - 0.15:
                break  # Onder de camera verdwenen: we zijn er bijna.
            stuur(tello, STIL)
        elif marker.y > LANDEN_Y:
            break
        else:
            stuur(tello, naar_marker(marker))
            laatste = marker
        time.sleep(LOOP_TIJD_S)
    else:
        stuur(tello, STIL)
        raise TimeoutError("Niet op tijd bij de marker.")
    stuur(tello, STIL)
    tello.move_forward(LAATSTE_METERS_CM)
    tello.land()
