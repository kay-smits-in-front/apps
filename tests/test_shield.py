import cv2
import numpy as np
import pytest

import shield.flight.drone as drone
from shield.flight.drone import Hoek, Noodstop, Spoor, Vlucht
from shield.flight.sturing import DOEL_Y, RICHTING, STIL, Rc, corrigeer, naar_marker
from shield.vision.markers import SCORE_GEVONDEN, Marker, vind_geel, vind_groen

GEEL_RGB = (255, 230, 0)
GROEN_RGB = (0, 200, 0)


def leeg() -> np.ndarray:
    return np.zeros((720, 960, 3), dtype=np.uint8)


def frame_met_kruis(rgb, cx=480, cy=360, lengte=60, hoek=45, dikte=8) -> np.ndarray:
    """Een kruis van twee strepen: hoek=45 is een X, hoek=0 een +."""
    frame = leeg()
    for h in (hoek, hoek + 90):
        dx, dy = lengte * np.cos(np.radians(h)), lengte * np.sin(np.radians(h))
        cv2.line(frame, (int(cx - dx), int(cy - dy)), (int(cx + dx), int(cy + dy)), rgb, dikte)
    return frame


# --- Kruisdetectie -------------------------------------------------------------------


def test_geel_kruis_wordt_herkend_op_juiste_plek():
    marker = vind_geel(frame_met_kruis(GEEL_RGB, cx=720, cy=480))
    assert marker is not None and marker.score >= SCORE_GEVONDEN
    assert marker.x > 0.4 and marker.y > 0.2


@pytest.mark.parametrize("hoek", [0, 20, 45, 70])
def test_kruis_wordt_herkend_bij_elke_draaiing(hoek):
    marker = vind_geel(frame_met_kruis(GEEL_RGB, hoek=hoek))
    assert marker is not None and marker.score >= SCORE_GEVONDEN


def test_groen_kruis_is_geen_geel_kruis():
    frame = frame_met_kruis(GROEN_RGB)
    assert vind_groen(frame) is not None
    assert vind_geel(frame) is None


def test_boek_massieve_vlek_is_geen_kruis():
    frame = leeg()
    frame[300:420, 380:600] = GROEN_RGB
    marker = vind_groen(frame)
    assert marker is None or marker.score < SCORE_GEVONDEN


def test_vierkante_rand_is_geen_kruis():
    frame = leeg()
    cv2.rectangle(frame, (380, 260), (580, 460), GEEL_RGB, 10)
    marker = vind_geel(frame)
    assert marker is None or marker.score < SCORE_GEVONDEN


def test_stipje_en_leeg_beeld_zijn_geen_kruis():
    frame = leeg()
    cv2.circle(frame, (200, 200), 6, GROEN_RGB, -1)
    assert vind_groen(frame) is None
    assert vind_geel(leeg()) is None


def test_oranje_vloer_is_geen_geel():
    vloer = np.full((720, 960, 3), (200, 120, 50), dtype=np.uint8)
    assert vind_geel(vloer) is None


def test_live_beeld_tekent_herkend_kruis():
    from shield.vision.live import teken

    frame = frame_met_kruis(GEEL_RGB)
    zonder = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    assert (teken(frame) != zonder).any()
    assert (teken(leeg()) == 0).all()


def test_muur_aandeel():
    from shield.vision.muur import muur_aandeel

    egaal = np.full((720, 960, 3), 200, dtype=np.uint8)
    ruis = np.random.default_rng(0).integers(0, 255, (720, 960, 3), dtype=np.uint8)
    assert muur_aandeel(egaal) > 0.99 and muur_aandeel(ruis) < 0.2


# --- Sturing -------------------------------------------------------------------------


def test_naar_marker_draait_naar_het_kruis_en_vliegt_vooruit_als_gecentreerd():
    rc = naar_marker(Marker(0.1, DOEL_Y, 0.01))
    assert rc.yaw > 0 and rc.ud == 0 and rc.fb > 0
    assert naar_marker(Marker(0.6, DOEL_Y, 0.01)).fb == 0  # Eerst draaien, dan pas vooruit.
    assert naar_marker(Marker(0.0, 0.9, 0.01)).ud < 0  # Te laag in beeld: dalen.


def test_demping_alleen_op_assen_zonder_commando():
    assert corrigeer(Rc(0, 40, 0, 0), vx=3, vy=0).fb == 40
    assert corrigeer(Rc(0, 0, 0, 0), vx=0, vy=2).lr != 0


def test_richtingen_zijn_links_rechts_omhoog_omlaag():
    assert set(RICHTING) == {"links", "rechts", "omhoog", "omlaag"}
    assert RICHTING["rechts"].lr > 0 > RICHTING["links"].lr
    assert RICHTING["omhoog"].ud > 0 > RICHTING["omlaag"].ud


def test_spoor_telt_alleen_door_bij_een_kruis_dat_op_dezelfde_plek_blijft():
    spoor = Spoor(0.25)
    assert [spoor.volg(Marker(0.0, 0.0, 100, 1.0)) for _ in range(3)] == [1, 2, 3]
    assert spoor.volg(Marker(0.8, 0.0, 100, 1.0)) == 1  # Ander kruis elders: opnieuw beginnen.
    assert spoor.volg(Marker(0.8, 0.0, 100, 0.4)) == 0  # Te lage score: spoor weg.


def test_hoek_telt_door_over_de_180_grens():
    hoek = Hoek(170)
    assert hoek.bijwerken(-170) == pytest.approx(20)
    assert hoek.bijwerken(-150) == pytest.approx(40)


# --- Vlucht met een nep-Tello --------------------------------------------------------


class NepTello:
    def __init__(self, vx=0, vy=0, pitch=0, roll=0, draait=False):
        self.vx, self.vy, self.pitch, self.roll, self.draait = vx, vy, pitch, roll, draait
        self.yaw, self.commandos, self.geland, self.stappen = 0.0, [], False, []

    def get_speed_x(self): return self.vx
    def get_speed_y(self): return self.vy
    def get_pitch(self): return self.pitch
    def get_roll(self): return self.roll
    def get_yaw(self): return self.yaw
    def get_height(self): return 80
    def land(self): self.geland = True
    def move_right(self, cm): self.stappen.append(("right", cm))
    def move_left(self, cm): self.stappen.append(("left", cm))
    def move_up(self, cm): self.stappen.append(("up", cm))
    def move_down(self, cm): self.stappen.append(("down", cm))
    def move_forward(self, cm): self.stappen.append(("forward", cm))

    def send_rc_control(self, lr, fb, ud, yaw):
        self.commandos.append((lr, fb, ud, yaw))
        if self.draait:
            self.yaw = (self.yaw + yaw * 0.2 + 180) % 360 - 180  # Nep-draai per commando.


class Camera:
    def __init__(self, frame):
        self.frame = frame


def test_noodstop_bij_te_grote_afwijking():
    with pytest.raises(Noodstop):
        Vlucht(NepTello(vx=20), camera=None).houd(STIL, 2.0)


def test_geen_noodstop_als_bewegen_is_afgesproken():
    Vlucht(NepTello(vx=20), camera=None).houd(Rc(0, 40, 0, 0), 0.2, max_afwijking=None)


def test_noodstop_bij_te_scheef():
    with pytest.raises(Noodstop):
        Vlucht(NepTello(roll=50), camera=None).stuur(STIL)


def test_q_stopt_de_vlucht_direct():
    vlucht = Vlucht(NepTello(), camera=None)
    vlucht.stop.set()
    with pytest.raises(Noodstop):
        vlucht.stuur(STIL)


def test_draai_180_stopt_en_stuurt_alleen_yaw():
    tello = NepTello(draait=True)
    Vlucht(tello, camera=None).draai(180)
    assert any(c[3] > 0 for c in tello.commandos)
    assert abs(abs(tello.yaw) - 180) < 40


def test_vooruit_stopt_bij_muur_en_gaat_door_in_open_ruimte():
    muur = Camera(np.full((720, 960, 3), 200, dtype=np.uint8))
    open_ruimte = Camera(np.random.default_rng(1).integers(0, 255, (720, 960, 3), dtype=np.uint8))
    bij_muur, in_open = Vlucht(NepTello(), muur), Vlucht(NepTello(), open_ruimte)
    bij_muur.vooruit(max_s=1.0)
    in_open.vooruit(max_s=0.5)
    vooruit = lambda v: sum(1 for c in v.tello.commandos if c[1] > 0)
    assert vooruit(bij_muur) <= 5 < vooruit(in_open)


# --- Scannen en zoeken --------------------------------------------------------------


def test_scan_vindt_het_kruis_en_onthoudt_de_richting():
    vlucht = Vlucht(NepTello(draait=True), Camera(frame_met_kruis(GEEL_RGB)))
    waarneming = vlucht.scan360(vind_geel, snelheid=100)
    assert waarneming is not None and waarneming.marker.score >= 0.8
    assert vlucht.tello.commandos[-1] == (0, 0, 0, 0)


def test_scan_draait_een_hele_ronde_zonder_kruis():
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    assert vlucht.scan360(vind_geel, snelheid=100) is None
    assert sum(c[3] for c in vlucht.tello.commandos if c[3] > 0) * 0.2 >= 340


def test_scan_negeert_een_boek():
    boek = leeg()
    boek[300:420, 380:600] = GROEN_RGB
    assert Vlucht(NepTello(draait=True), Camera(boek)).scan360(vind_groen, snelheid=100) is None


def test_draai_naar_kiest_de_kortste_kant():
    links, rechts = NepTello(draait=True), NepTello(draait=True)
    Vlucht(links, camera=None).draai_naar(300)
    Vlucht(rechts, camera=None).draai_naar(60)
    assert any(c[3] < 0 for c in links.commandos) and all(c[3] >= 0 for c in rechts.commandos)


def test_zoek_kruis_beweegt_pas_na_een_lege_scan(monkeypatch):
    monkeypatch.setattr(drone, "ROND_RC", 100)
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    zijwaarts = []
    monkeypatch.setattr(vlucht, "nieuwe_plek", lambda ronde: zijwaarts.append(ronde))
    with pytest.raises(Noodstop):
        vlucht.zoek_kruis(vind_geel, max_rondes=3)
    assert zijwaarts == [0, 1]  # Na elke lege scan behalve de laatste.


def test_zoek_kruis_beweegt_niet_als_kruis_al_zichtbaar():
    vlucht = Vlucht(NepTello(draait=True), Camera(frame_met_kruis(GEEL_RGB)))
    assert vlucht.zoek_kruis(vind_geel) is not None
    assert vlucht.tello.stappen == []


def test_nieuwe_plek_gaat_zijwaarts_bij_muur_en_vooruit_in_open_ruimte(monkeypatch):
    muur = Vlucht(NepTello(), Camera(np.full((720, 960, 3), 200, dtype=np.uint8)))
    muur.nieuwe_plek(0)
    assert any(c[0] > 0 for c in muur.tello.commandos) and not any(c[1] > 0 for c in muur.tello.commandos)
    open_ruimte = Vlucht(NepTello(), Camera(np.random.default_rng(1).integers(0, 255, (720, 960, 3), dtype=np.uint8)))
    monkeypatch.setattr(open_ruimte, "vooruit", lambda: open_ruimte.tello.stappen.append(("vooruit", 0)))
    open_ruimte.nieuwe_plek(0)
    assert ("vooruit", 0) in open_ruimte.tello.stappen


# --- Naderen en landen ---------------------------------------------------------------


def test_vliegt_naar_het_kruis_en_landt_niet_op_een_ander_punt():
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cy=300)))  # Hoog in beeld.
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, timeout_s=0.4)
    assert any(c[1] > 0 for c in vlucht.tello.commandos)  # Er is vooruit gestuurd.
    assert not vlucht.tello.geland


def test_landt_na_het_naderen_als_kruis_gecentreerd_onderin_staat():
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cy=640)))
    vlucht.vlieg_en_land(vind_geel, timeout_s=3, min_nader_s=0)
    assert vlucht.tello.stappen == [("forward", 20)] and vlucht.tello.geland


def test_landt_niet_voordat_er_genaderd_is():
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cy=640)))
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, timeout_s=0.3, min_nader_s=5)
    assert not vlucht.tello.geland


def test_een_boek_als_groen_kruis_laat_hem_niet_landen():
    boek = leeg()
    boek[560:680, 380:600] = GROEN_RGB  # Onderin beeld, maar geen kruis.
    vlucht = Vlucht(NepTello(), Camera(boek))
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_groen, timeout_s=1, min_nader_s=0)
    assert not vlucht.tello.geland


def test_daalbudget_begrenst_het_dalen():
    vlucht = Vlucht(NepTello(), camera=None)
    assert vlucht.begrens_dalen(Rc(0, 0, -20, 0)).ud == -20
    vlucht.daal_s = 0
    assert vlucht.begrens_dalen(Rc(0, 0, -20, 0)).ud == 0


def test_vergrendeld_negeert_een_kruis_dat_ver_van_het_slot_staat():
    slot = Marker(-0.6, 0.0, 100, 1.0)
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cx=700, cy=300)))  # Kruis rechts van het slot.
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, vast=slot, timeout_s=0.3)
    assert not any(c[1] > 0 for c in vlucht.tello.commandos)  # Niet vooruit gevlogen naar een ander kruis.


def test_bewaar_schrijft_een_leesbare_jpg(tmp_path):
    from shield.vision.live import bewaar

    pad = bewaar(frame_met_kruis(GEEL_RGB), map=tmp_path)
    assert cv2.imread(str(pad)).shape == (720, 960, 3)
