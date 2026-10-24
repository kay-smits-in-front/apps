import cv2
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


# --- Vlucht met een nep-Tello -------------------------------------------------
import pytest

from shield.flight.drone import Noodstop, Vlucht
from shield.flight.sturing import STIL, Rc, corrigeer


class NepTello:
    def __init__(self, vx=0, vy=0, pitch=0, roll=0, draait=False):
        self.vx, self.vy, self.pitch, self.roll, self.draait = vx, vy, pitch, roll, draait
        self.yaw, self.commandos, self.geland = 0.0, [], False

    def get_speed_x(self): return self.vx
    def get_speed_y(self): return self.vy
    def get_pitch(self): return self.pitch
    def get_roll(self): return self.roll
    def get_yaw(self): return self.yaw
    def land(self): self.geland = True

    def send_rc_control(self, lr, fb, ud, yaw):
        self.commandos.append((lr, fb, ud, yaw))
        if self.draait:
            self.yaw = (self.yaw + yaw * 0.2 + 180) % 360 - 180  # Nep-draai per commando.


def test_noodstop_bij_te_grote_afwijking():
    vlucht = Vlucht(NepTello(vx=20), camera=None)  # 200 cm/s aangenomen
    with pytest.raises(Noodstop):
        vlucht.houd(STIL, 2.0)


def test_geen_noodstop_als_bewegen_is_afgesproken():
    vlucht = Vlucht(NepTello(vx=20), camera=None)
    vlucht.houd(Rc(0, 40, 0, 0), 0.2, max_afwijking=None)


def test_noodstop_bij_te_scheef():
    with pytest.raises(Noodstop):
        Vlucht(NepTello(roll=50), camera=None).stuur(STIL)


def test_draai_180_stopt_en_stuurt_alleen_yaw():
    tello = NepTello(draait=True)
    Vlucht(tello, camera=None).draai(180)
    assert any(c[3] > 0 for c in tello.commandos)
    assert abs(abs(tello.yaw) - 180) < 40


def test_demping_alleen_op_assen_zonder_commando():
    assert corrigeer(Rc(0, 40, 0, 0), vx=3, vy=0).fb == 40
    assert corrigeer(Rc(0, 0, 0, 0), vx=0, vy=2).lr != 0


def test_live_beeld_tekent_herkend_geel():
    from shield.vision.live import teken

    frame = frame_met_blok((255, 230, 0), 300, 400)
    zonder = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    met = teken(frame)
    assert met.shape == zonder.shape and (met != zonder).any()
    assert (teken(np.zeros_like(frame)) == 0).all()


def test_zoek_vegen_zwaait_links_rechts_en_gaat_vooruit():
    from shield.flight.sturing import zoek_vegen

    assert zoek_vegen(0).lr == 0
    assert zoek_vegen(1.5).lr > 0 > zoek_vegen(4.5).lr
    assert all(zoek_vegen(t).fb > 0 and zoek_vegen(t).ud == 0 for t in (0, 1, 2, 3))


def test_zoek_door_vegen_stopt_zodra_geel_zichtbaar():
    class Camera:
        frame = frame_met_blok((255, 230, 0), 300, 400)

    vlucht = Vlucht(NepTello(), camera=Camera())
    assert vlucht.zoek_door_vegen(vind_geel) is not None
    assert vlucht.tello.commandos[-1] == (0, 0, 0, 0)


def test_zoek_door_vegen_geeft_noodstop_na_timeout():
    class Camera:
        frame = np.zeros((720, 960, 3), dtype=np.uint8)

    vlucht = Vlucht(NepTello(), camera=Camera())
    with pytest.raises(Noodstop):
        vlucht.zoek_door_vegen(vind_geel, timeout_s=0.3)


def test_geel_op_de_vloer_wordt_niet_gezien():
    vloer = np.zeros((720, 960, 3), dtype=np.uint8)
    vloer[:] = (200, 120, 50)  # Oranje hout (hue ~12), vult het hele beeld.
    assert vind_geel(vloer) is None


def test_vliegt_naar_de_marker_en_landt_niet_meteen():
    class Camera:
        frame = frame_met_blok((255, 230, 0), 300, 420)  # Midden, y ~ 0.1.

    vlucht = Vlucht(NepTello(), camera=Camera())
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, timeout_s=0.4)
    assert any(c[1] > 0 for c in vlucht.tello.commandos)  # Er is vooruit gestuurd.
    assert not vlucht.tello.geland


def test_landt_als_marker_laag_in_beeld_staat():
    class Camera:
        frame = frame_met_blok((255, 230, 0), 580, 420)  # Onderin, y ~ 0.85.

    vlucht = Vlucht(NepTello(), camera=Camera())
    vlucht.vlieg_en_land(vind_geel, timeout_s=2)
    assert vlucht.tello.geland


def test_q_stopt_de_vlucht_direct():
    vlucht = Vlucht(NepTello(), camera=None)
    vlucht.stop.set()
    with pytest.raises(Noodstop):
        vlucht.stuur(STIL)


def test_marker_even_kwijt_houdt_koers():
    class Camera:
        frames = iter([frame_met_blok((255, 230, 0), 300, 420)] * 3)
        leeg = np.zeros((720, 960, 3), dtype=np.uint8)

        @property
        def frame(self):
            return next(self.frames, self.leeg)

    vlucht = Vlucht(NepTello(), camera=Camera())
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, timeout_s=0.3)
    fb = [c[1] for c in vlucht.tello.commandos]
    assert fb[:6].count(0) == 0  # Eerste commando's blijven vooruit, ook na het kwijtraken.
