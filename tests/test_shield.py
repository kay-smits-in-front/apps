import cv2
import numpy as np
import pytest

import shield.flight.drone as drone
from shield.flight.drone import Hoek, Noodstop, Spoor, Vlucht
from shield.flight.zoeken import Dekking, Geheugen, kies_richting, kies_stap_hoogte
from shield.flight.sturing import (
    DOEL_Y, MAX_NETTO_S, MAX_ZOEK_CM, MIN_ZOEK_CM, RICHTING, STIL, Rc, corrigeer, is_dichtbij, is_erboven_verdwenen,
    naar_marker, verticale_opties,
)
from shield.vision.markers import SCORE_GEVONDEN, Marker, vind_geel, vind_groen, vind_roze

GEEL_RGB = (255, 230, 0)
ROZE_RGB = (255, 60, 160)
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

    frame = frame_met_kruis(ROZE_RGB)
    zonder = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    assert (teken(frame) != zonder).any()
    assert (teken(leeg()) == 0).all()


def test_muur_aandeel():
    from shield.vision.muur import muur_aandeel

    egaal = np.full((720, 960, 3), 200, dtype=np.uint8)
    ruis = np.random.default_rng(0).integers(0, 255, (720, 960, 3), dtype=np.uint8)
    assert muur_aandeel(egaal) > 0.99 and muur_aandeel(ruis) < 0.5


# --- Sturing -------------------------------------------------------------------------


def test_naar_marker_draait_naar_het_kruis_en_vliegt_vooruit_als_gecentreerd():
    rc = naar_marker(Marker(0.1, DOEL_Y, 0.01))
    assert rc.yaw > 0 and rc.ud == 0 and rc.fb > 0
    assert naar_marker(Marker(0.6, DOEL_Y, 0.01)).fb == 0  # Eerst draaien, dan pas vooruit.
    assert naar_marker(Marker(0.0, 0.9, 0.01)).ud < 0  # Te laag in beeld: dalen.


def test_demping_alleen_op_assen_zonder_commando():
    assert corrigeer(Rc(0, 40, 0, 0), vx=3, vy=0).fb == 40
    assert corrigeer(Rc(0, 0, 0, 0), vx=0, vy=2).lr != 0


def test_alleen_nog_hoogtebewegingen_als_vaste_stap():
    assert set(RICHTING) == {"omhoog", "omlaag"}
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


# --- Zoeken: dekking, richting kiezen, scan ---------------------------------------------


def dekking_met(open_van: float, open_tot: float, muur_elders: float = 0.95) -> Dekking:
    """Dekking waarin alleen de richtingen tussen open_van en open_tot open zijn."""
    dekking = Dekking()
    for graden in range(0, 360, 10):
        muur = 0.1 if open_van <= graden < open_tot else muur_elders
        dekking.registreer(graden + 5, muur, 0.0)
    return dekking


def test_dekking_telt_beelden_per_richting_en_welk_deel_gezien_is():
    dekking = Dekking()
    dekking.registreer(5, 0.9, 0.2)
    dekking.registreer(8, 0.5, 0.6)
    dekking.registreer(365, 0.1, 0.0)  # Draaide een klein stukje te ver: hoort weer bij de eerste sector.
    assert dekking.aantal[0] == 3 and dekking.beste_score[0] == 0.6
    assert dekking.gezien() == 1 / 36


def test_kies_richting_gaat_naar_de_open_kant():
    richting = kies_richting(dekking_met(100, 170), terug=[])
    assert 100 <= richting <= 170


def test_kies_richting_vermijdt_de_kant_waar_we_vandaan_kwamen():
    dekking = Dekking()
    for graden in range(0, 360, 10):  # Open rondom, maar rechts achter ons (180) is het meest open.
        dekking.registreer(graden + 5, 0.2 if 150 <= graden < 210 else 0.4, 0.0)
    assert 150 <= kies_richting(dekking, terug=[]) <= 210
    assert not 130 <= kies_richting(dekking, terug=[180.0]) <= 230


def test_kies_richting_geeft_none_als_alles_muur_is():
    assert kies_richting(dekking_met(0, 0, muur_elders=0.98), terug=[]) is None


def test_geheugen_schuift_de_richting_terug_mee_met_een_draai():
    geheugen = Geheugen()
    geheugen.verplaatst()
    geheugen.gedraaid(90)
    assert geheugen.terug == [90.0]


def test_hoogteniveaus_eerst_omlaag_dan_omhoog_en_nooit_dubbel():
    assert kies_stap_hoogte(0, {0}, ["omhoog", "omlaag"]) == "omlaag"
    assert kies_stap_hoogte(-1, {0, -1}, ["omhoog", "omlaag"]) == "omhoog" or kies_stap_hoogte(-1, {0, -1}, ["omhoog", "omlaag"]) == "omlaag"
    assert kies_stap_hoogte(0, {0, -1, 1}, ["omhoog", "omlaag"]) is None
    assert kies_stap_hoogte(0, {0}, ["omhoog"]) == "omhoog"  # Omlaag mag niet (te laag): omhoog.


def test_hoogtegrenzen_voorkomen_te_laag_en_te_hoog():
    assert verticale_opties(MIN_ZOEK_CM, 0) == ["omhoog"]
    assert verticale_opties(MAX_ZOEK_CM, 0) == ["omlaag"]
    assert verticale_opties(100, 0) == ["omhoog", "omlaag"]
    assert verticale_opties(0, MAX_NETTO_S) == ["omlaag"]  # Hoogte onbekend: netto stijgen is begrensd.


def test_scan_draait_een_hele_ronde_en_vult_de_dekking():
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    dekking = Dekking()
    assert vlucht.scan(vind_roze, dekking, [], snelheid=40) is None  # Nep-draai: 8 graden per beeld.
    assert dekking.gezien() > 0.9


def test_scan_stopt_direct_bij_een_mogelijk_kruis_en_bevestigt_het():
    vlucht = Vlucht(NepTello(draait=True), Camera(frame_met_kruis(ROZE_RGB)))
    kruis = vlucht.scan(vind_roze, Dekking(), [], snelheid=100)
    assert kruis is not None and kruis.score >= SCORE_GEVONDEN
    assert sum(1 for c in vlucht.tello.commandos if c[3] > 0) < 15  # Niet eerst nog een hele ronde.


def test_scan_negeert_een_boek_en_draait_door():
    boek = leeg()
    boek[300:420, 380:600] = GROEN_RGB
    vlucht = Vlucht(NepTello(draait=True), Camera(boek))
    assert vlucht.scan(vind_groen, Dekking(), [], snelheid=100) is None


def test_scan_negeert_richtingen_van_een_eerder_vals_alarm():
    halfkruis = frame_met_kruis(ROZE_RGB)
    halfkruis[:, 480:] = 0  # Halve kruis: score ligt tussen 'lijkt erop' en 'bevestigd'.
    vlucht = Vlucht(NepTello(draait=True), Camera(halfkruis))
    genegeerd = list(range(0, 360, 10))  # Alles genegeerd: nergens meer stoppen.
    assert vlucht.scan(vind_roze, Dekking(), genegeerd, snelheid=100) is None


def test_draai_naar_kiest_de_kortste_kant():
    links, rechts = NepTello(draait=True), NepTello(draait=True)
    Vlucht(links, camera=None).draai_naar(300)
    Vlucht(rechts, camera=None).draai_naar(60)
    assert any(c[3] < 0 for c in links.commandos) and all(c[3] >= 0 for c in rechts.commandos)


def test_zoek_kruis_vliegt_naar_de_open_kant_en_wisselt_van_hoogte(monkeypatch):
    monkeypatch.setattr(drone, "ROND_RC", 100)
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    acties = []
    monkeypatch.setattr(vlucht, "draai_naar", lambda graden: acties.append(("draai", graden)))
    monkeypatch.setattr(vlucht, "vooruit", lambda max_s, zoeker=None: acties.append(("vooruit", max_s)))
    monkeypatch.setattr(vlucht, "beweeg", lambda naam, s: acties.append((naam, s)))
    monkeypatch.setattr(
        vlucht, "scan", lambda zoeker, dekking, genegeerd, snelheid=None: [dekking.registreer(g + 5, 0.1 if 60 <= g < 120 else 0.95, 0) for g in range(0, 360, 10)] and None
    )
    with pytest.raises(Noodstop):
        vlucht.zoek_kruis(vind_roze, max_rondes=2)
    assert acties[0][0] == "draai" and 60 <= acties[0][1] <= 120
    assert [a[0] for a in acties[1:]] == ["vooruit", "omlaag"]


def test_zoek_kruis_stopt_als_de_ruimte_afgezocht_is(monkeypatch):
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    monkeypatch.setattr(vlucht, "scan", lambda zoeker, dekking, genegeerd, snelheid=None: dekking_met(0, 0, 0.99) and None)
    monkeypatch.setattr(vlucht.tello, "get_height", lambda: MIN_ZOEK_CM)  # Omlaag mag niet.
    vlucht.netto_hoogte_s = MAX_NETTO_S  # Omhoog ook niet.
    with pytest.raises(Noodstop, match="afgezocht"):
        vlucht.zoek_kruis(vind_roze, max_rondes=5)


def test_zoek_kruis_beweegt_niet_als_kruis_al_zichtbaar():
    vlucht = Vlucht(NepTello(draait=True), Camera(frame_met_kruis(ROZE_RGB)))
    assert vlucht.zoek_kruis(vind_roze) is not None
    assert vlucht.tello.stappen == []


def test_vooruit_geeft_een_kruis_dat_onderweg_in_beeld_komt():
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(ROZE_RGB)))
    assert vlucht.vooruit(5.0, zoeker=vind_roze) is not None


# --- Naderen en landen ---------------------------------------------------------------


def test_vliegt_naar_het_kruis_en_landt_niet_op_een_ander_punt():
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cy=300)))  # Hoog in beeld.
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, timeout_s=0.4)
    assert any(c[1] > 0 for c in vlucht.tello.commandos)  # Er is vooruit gestuurd.
    assert not vlucht.tello.geland


def test_landt_na_het_naderen_als_kruis_gecentreerd_onderin_staat(monkeypatch):
    monkeypatch.setattr(drone, "MIN_VOORUIT_S", 0.2)
    monkeypatch.setattr(drone, "REMMEN_STRAAL", 0.05)  # Dit nagemaakte kruis is klein.
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cy=640, lengte=100)))
    vlucht.vlieg_en_land(vind_geel, timeout_s=3)
    assert vlucht.tello.geland and vlucht.tello.stappen == []  # Geen move_*: alleen rc vooruit en landen.
    assert any(c[1] > 0 for c in vlucht.tello.commandos)


def test_landt_niet_voordat_er_naar_het_kruis_gevlogen_is():
    vlucht = Vlucht(NepTello(), Camera(frame_met_kruis(GEEL_RGB, cy=600, lengte=110)))
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_geel, timeout_s=0.5)  # Korter dan MIN_VOORUIT_S: nog niet aangekomen.
    assert not vlucht.tello.geland and any(c[1] > 0 for c in vlucht.tello.commandos)


def test_een_boek_als_groen_kruis_laat_hem_niet_landen():
    boek = leeg()
    boek[560:680, 380:600] = GROEN_RGB  # Onderin beeld, maar geen kruis.
    vlucht = Vlucht(NepTello(), Camera(boek))
    with pytest.raises(Noodstop):
        vlucht.vlieg_en_land(vind_groen, timeout_s=1)
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





def test_roze_kruis_wordt_herkend_en_geel_en_groen_niet():
    from shield.vision.markers import vind_roze

    assert vind_roze(frame_met_kruis(ROZE_RGB)).score >= SCORE_GEVONDEN
    assert vind_roze(frame_met_kruis(GEEL_RGB)) is None and vind_roze(frame_met_kruis(GROEN_RGB)) is None


def test_blauwpaarse_muur_is_geen_roze():
    from shield.vision.markers import vind_roze

    muur = np.full((720, 960, 3), (90, 80, 140), dtype=np.uint8)
    assert vind_roze(muur) is None


# --- Lijnen en gecombineerde detectie -------------------------------------------------


def test_lijnendetector_vindt_roze_kruis_ook_bij_dunne_tape():
    from shield.vision.lijnen import vind_kruis_lijnen

    for dikte in (3, 6, 12):
        kruis = vind_kruis_lijnen(frame_met_kruis(ROZE_RGB, dikte=dikte))
        assert kruis is not None and abs(kruis.x) < 0.1 and abs(kruis.y) < 0.1, dikte


def test_lijnendetector_vindt_geen_kruis_in_sticker_ring_of_leeg_beeld():
    from shield.vision.lijnen import vind_kruis_lijnen

    sticker, ring = leeg(), leeg()
    sticker[300:420, 380:600] = ROZE_RGB
    cv2.circle(ring, (480, 360), 40, ROZE_RGB, 6)
    assert vind_kruis_lijnen(sticker) is None and vind_kruis_lijnen(ring) is None and vind_kruis_lijnen(leeg()) is None


def test_gecombineerd_beide_methoden_geven_honderd_procent():
    from shield.vision.kruis import vind_roze_kruis

    kruis = vind_roze_kruis(frame_met_kruis(ROZE_RGB))
    assert kruis is not None and kruis.score == 1.0


def test_gecombineerd_negeert_geel_en_leeg():
    from shield.vision.kruis import vind_roze_kruis

    assert vind_roze_kruis(frame_met_kruis(GEEL_RGB)) is None and vind_roze_kruis(leeg()) is None


def test_gecombineerd_vindt_een_dik_kruis_op_een_witte_ondergrond():
    from shield.vision.kruis import vind_roze_kruis

    wit = np.full((720, 960, 3), 235, dtype=np.uint8)
    kruis = frame_met_kruis(ROZE_RGB, lengte=55, dikte=22)
    wit[kruis.sum(axis=2) > 0] = kruis[kruis.sum(axis=2) > 0]
    gevonden = vind_roze_kruis(wit)
    assert gevonden is not None and gevonden.score >= SCORE_GEVONDEN


# --- Aankomst bij het kruis ---------------------------------------------------------


def test_dichtbij_is_een_groot_kruis_ook_als_het_op_een_muur_staat():
    assert is_dichtbij(Marker(0, 0, 0.01, 1.0, straal=0.25))
    assert not is_dichtbij(Marker(0, 0, 0.01, 1.0, straal=0.08))


def test_erboven_verdwenen_alleen_na_een_kruis_dat_onderin_en_groot_genoeg_was():
    assert is_erboven_verdwenen(Marker(0, 0.7, 0.01, 1.0, straal=0.1))
    assert not is_erboven_verdwenen(Marker(0, 0.1, 0.01, 1.0, straal=0.1))  # Midden in beeld verdwenen: niet erboven.
    assert not is_erboven_verdwenen(Marker(0, 0.7, 0.0, 1.0, straal=0.01))  # Een stipje: geen kruis van dichtbij.
    assert not is_erboven_verdwenen(None)


def test_naar_marker_gaat_rustiger_vooruit_als_het_kruis_groot_wordt():
    ver, dichtbij = naar_marker(Marker(0, 0.5, 0.0, 1.0, 0.03)), naar_marker(Marker(0, 0.5, 0.0, 1.0, 0.15))
    assert 0 < dichtbij.fb < ver.fb


def test_land_direct_voor_een_groot_kruis_op_een_muur(monkeypatch):
    monkeypatch.setattr(drone, "MIN_VOORUIT_S", 0.2)
    wit = np.full((720, 960, 3), 235, dtype=np.uint8)
    kruis = frame_met_kruis(ROZE_RGB, lengte=200, dikte=30)
    wit[kruis.sum(axis=2) > 0] = kruis[kruis.sum(axis=2) > 0]
    vlucht = Vlucht(NepTello(), Camera(wit))
    from shield.vision.kruis import vind_roze_kruis

    vlucht.vlieg_en_land(vind_roze_kruis, timeout_s=3)
    vooruit = sum(1 for c in vlucht.tello.commandos if c[1] > 0)
    assert vlucht.tello.geland and vlucht.tello.commandos[-1] == (0, 0, 0, 0) and vooruit < 6  # Geen extra stuk vooruit.


def test_kruis_verdwijnt_onderin_na_nadering_dan_nog_even_vooruit_en_landen(monkeypatch):
    monkeypatch.setattr(drone, "MIN_VOORUIT_S", 0.05)
    class Verdwijnend:
        def __init__(self):
            self.n = 0

        @property
        def frame(self):
            self.n += 1
            return frame_met_kruis(ROZE_RGB, cy=600, lengte=80) if self.n <= 6 else leeg()

    from shield.vision.kruis import vind_roze_kruis

    vlucht = Vlucht(NepTello(), Verdwijnend())
    vlucht.vlieg_en_land(vind_roze_kruis, timeout_s=5)
    assert vlucht.tello.geland
