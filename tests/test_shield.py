import numpy as np

from shield.flight.sturing import DOEL_Y, naar_marker
from shield.vision.markers import Marker, vind_geel, vind_groen


def frame_met_blok(rgb, rij, kolom, grootte=120):
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    frame[rij:rij + grootte, kolom:kolom + grootte] = rgb
    return frame


def test_geel_wordt_herkend_op_juiste_plek():
    marker = vind_geel(frame_met_blok((255, 230, 0), 480, 720))
    assert marker is not None
    assert marker.x > 0.5 and marker.y > 0.4


def test_groen_wordt_herkend_en_geel_niet():
    frame = frame_met_blok((0, 200, 0), 100, 100)
    assert vind_groen(frame) is not None
    assert vind_geel(frame) is None


def test_leeg_beeld_geeft_geen_marker():
    assert vind_geel(np.zeros((720, 960, 3), dtype=np.uint8)) is None


def test_sturing_draait_naar_marker_en_houdt_hoogte():
    rc = naar_marker(Marker(0.3, DOEL_Y, 0.01))
    assert rc.yaw > 0 and rc.ud == 0 and rc.fb > 0
    assert naar_marker(Marker(0.0, 0.8, 0.01)).ud < 0  # Te laag in beeld: dalen.
