import cv2
import numpy as np
import pytest

import shield.flight.drone as drone
from shield.flight.drone import Hoek, Noodstop, Spoor, Vlucht
from shield.flight.kaart import KOLOMMEN, MIN_RESTKANS, N, Kaart, peiling_en_afstand, rechte_stukken
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


@pytest.fixture(autouse=True)
def snel_kijken(monkeypatch):
    monkeypatch.setattr(drone, "KIJK_S", 0.05)
    monkeypatch.setattr(drone, "KIJK_TUSSEN_S", 0.01)


def vrij(kolommen: float = 0.2) -> np.ndarray:
    return np.full(KOLOMMEN, kolommen)


def test_kijken_zonder_kruis_verlaagt_de_kans_voor_de_drone_maar_niet_erachter():
    kaart = Kaart()
    voor = kaart.kansen[0].sum()
    kaart.bekijk(0, 0.0, vrij())  # Kijkt langs de +x-as.
    voorin, achterin = kaart.cel(1.5, 0), kaart.cel(-1.5, 0)
    assert kaart.kansen[0].sum() < voor
    assert kaart.kansen[0][voorin] < 0.4 * kaart.kansen[0][achterin]
    assert kaart.kansen[1].sum() == pytest.approx(kaart.kansen[-1].sum())  # Andere niveaus onaangeroerd.


def test_een_vlakke_strook_beperkt_hoe_ver_we_kijken():
    open_zicht, muur_zicht = Kaart(), Kaart()
    open_zicht.bekijk(0, 0.0, vrij(0.2))
    muur_zicht.bekijk(0, 0.0, vrij(0.99))
    ver = open_zicht.cel(2.5, 0)
    assert open_zicht.kansen[0][ver] < muur_zicht.kansen[0][ver]


def test_na_een_volledige_ronde_is_er_veel_minder_kans_over():
    kaart = Kaart()
    for richting in range(0, 360, 40):
        kaart.bekijk(0, float(richting), vrij())
    assert kaart.kansen[0].sum() < 0.5 * kaart.kansen[1].sum()


def test_kaart_kiest_een_ander_standpunt_met_meer_nog_niet_geziene_kans():
    kaart = Kaart()
    for richting in range(0, 360, 40):
        kaart.bekijk(0, float(richting), vrij())
    besluit = kaart.kies(0, {0})
    assert besluit is not None and besluit.doel != kaart.cel(0, 0)
    assert besluit.route[0] == kaart.cel(0, 0) and besluit.route[-1] == besluit.doel


def test_kaart_wisselt_van_niveau_als_dat_meer_oplevert():
    kaart = Kaart()
    for richting in range(0, 360, 40):
        kaart.bekijk(0, float(richting), vrij())  # Niveau 0 is bekeken; -1 en 1 niet.
    assert kaart.kies(0, {-1, 0, 1}).niveau != 0


def test_kaart_zegt_afgezocht_als_de_kans_op_is():
    kaart = Kaart()
    for n in kaart.kansen:
        kaart.kansen[n][:] = MIN_RESTKANS / (3 * N * N) * 0.5
    assert kaart.kies(0, {0}) is None


def test_astar_loopt_om_een_muur_heen_en_vindt_niets_in_een_gesloten_vak():
    kaart = Kaart()
    kaart.wand[:, N // 2] = True  # Hele muur van boven naar onder.
    assert kaart.route((0, 0), (0, N - 1)) == []
    kaart.wand[3, N // 2] = False  # Een opening.
    route = kaart.route((0, 0), (0, N - 1))
    assert route and (3, N // 2) in route


def test_astar_route_is_recht_zonder_obstakels_en_rechte_stukken_geven_knikpunten():
    kaart = Kaart()
    route = kaart.route((2, 2), (2, 8))
    assert route == [(2, c) for c in range(2, 9)] and rechte_stukken(route) == [(2, 8)]
    assert rechte_stukken([(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)]) == [(0, 2), (2, 2)]


def test_muur_markeren_blokkeert_cellen_en_haalt_de_kans_weg():
    kaart = Kaart()
    kaart.markeer_wand(0.0)  # Muur 0,8 m vóór de drone langs de +x-as.
    cel = kaart.cel(0.8, 0)
    assert kaart.wand[cel] and all(k[cel] == 0 for k in kaart.kansen.values())


def test_verplaatsen_volgt_de_koers():
    kaart = Kaart()
    kaart.verplaats(1.0, 90.0)
    assert kaart.x == pytest.approx(0.0, abs=1e-9) and kaart.y == pytest.approx(1.0)


def test_peiling_en_afstand():
    assert peiling_en_afstand((0, 0), (0, 2)) == pytest.approx((90.0, 2.0))
    assert peiling_en_afstand((1, 1), (0, 1))[0] == pytest.approx(180.0)


def test_hoogtegrenzen_voorkomen_te_laag_en_te_hoog():
    assert verticale_opties(MIN_ZOEK_CM, 0) == ["omhoog"]
    assert verticale_opties(MAX_ZOEK_CM, 0) == ["omlaag"]
    assert verticale_opties(100, 0) == ["omhoog", "omlaag"]
    assert verticale_opties(0, MAX_NETTO_S) == ["omlaag"]  # Hoogte onbekend: netto stijgen is begrensd.


def test_scan_draait_een_hele_ronde_en_verlaagt_de_kans_overal():
    ruis = np.repeat(np.random.default_rng(2).integers(0, 255, (720, 960, 1), dtype=np.uint8), 3, axis=2)  # Grijs, niets vlaks.
    vlucht = Vlucht(NepTello(draait=True), Camera(ruis))
    assert vlucht.scan(vind_roze, [], stap_graden=40) is None
    assert vlucht.kaart.kansen[0].sum() < 0.5 * vlucht.kaart.kansen[1].sum()
    assert vlucht.koers == pytest.approx(0.0, abs=15) or vlucht.koers > 345  # Weer in de beginrichting.


def test_scan_stopt_direct_bij_een_mogelijk_kruis_en_bevestigt_het():
    vlucht = Vlucht(NepTello(draait=True), Camera(frame_met_kruis(ROZE_RGB)))
    kruis = vlucht.scan(vind_roze, [])
    assert kruis is not None and kruis.score >= SCORE_GEVONDEN
    assert sum(1 for c in vlucht.tello.commandos if c[3] > 0) < 15  # Niet eerst nog een hele ronde.


def test_scan_negeert_een_boek_en_draait_door():
    boek = leeg()
    boek[300:420, 380:600] = GROEN_RGB
    vlucht = Vlucht(NepTello(draait=True), Camera(boek))
    assert vlucht.scan(vind_groen, []) is None


def test_scan_negeert_richtingen_van_een_eerder_vals_alarm():
    halfkruis = frame_met_kruis(ROZE_RGB)
    halfkruis[:, 480:] = 0  # Halve kruis: score ligt tussen 'lijkt erop' en 'bevestigd'.
    vlucht = Vlucht(NepTello(draait=True), Camera(halfkruis))
    genegeerd = list(range(0, 360, 10))  # Alles genegeerd: nergens meer stoppen.
    assert vlucht.scan(vind_roze, genegeerd) is None


def test_draai_naar_kiest_de_kortste_kant():
    links, rechts = NepTello(draait=True), NepTello(draait=True)
    Vlucht(links, camera=None).draai_naar(300)
    Vlucht(rechts, camera=None).draai_naar(60)
    assert any(c[3] < 0 for c in links.commandos) and all(c[3] >= 0 for c in rechts.commandos)


def test_zoek_kruis_vliegt_naar_het_door_de_kaart_gekozen_standpunt(monkeypatch):
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    acties = []
    monkeypatch.setattr(vlucht, "mogelijke_niveaus", lambda: {0})
    monkeypatch.setattr(vlucht, "scan", lambda zoeker, genegeerd: [vlucht.kaart.bekijk(0, float(r), vrij()) for r in range(0, 360, 40)] and None)
    monkeypatch.setattr(vlucht, "draai_naar", lambda graden: acties.append(("draai", graden)))
    monkeypatch.setattr(vlucht, "vooruit", lambda max_s, zoeker=None: acties.append(("vooruit", max_s)))
    monkeypatch.setattr(vlucht, "beweeg", lambda naam, s: acties.append((naam, s)))
    with pytest.raises(Noodstop):
        vlucht.zoek_kruis(vind_roze, max_rondes=2)
    assert acties and acties[0][0] in ("draai", "vooruit")
    assert any(a[0] == "vooruit" and a[1] > 0 for a in acties)


def test_zoek_kruis_stopt_als_de_ruimte_afgezocht_is(monkeypatch):
    vlucht = Vlucht(NepTello(draait=True), Camera(leeg()))
    monkeypatch.setattr(vlucht, "scan", lambda zoeker, genegeerd: None)
    for kans in vlucht.kaart.kansen.values():
        kans[:] = 0.0
    with pytest.raises(Noodstop, match="afgezocht"):
        vlucht.zoek_kruis(vind_roze, max_rondes=5)


def test_vooruit_markeert_een_muur_en_telt_de_afstand_mee():
    muur = Vlucht(NepTello(), Camera(np.full((720, 960, 3), 200, dtype=np.uint8)))
    muur.vooruit(2.0)
    assert muur.kaart.wand.any()
    open_ruimte = Vlucht(NepTello(), Camera(np.random.default_rng(1).integers(0, 255, (720, 960, 3), dtype=np.uint8)))
    open_ruimte.vooruit(0.5)
    assert open_ruimte.kaart.x > 0.05 and not open_ruimte.kaart.wand.any()


def test_koers_telt_mee_met_draaien():
    vlucht = Vlucht(NepTello(draait=True), camera=None)
    vlucht.draai(90)
    assert 70 < vlucht.koers < 110
    vlucht.draai_naar(300)  # Kortste kant: 60 graden terug.
    assert 5 < vlucht.koers < 70


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


def test_muur_kolommen_zien_waar_de_rand_zit():
    from shield.vision.muur import muur_kolommen

    frame = np.full((720, 960, 3), 200, dtype=np.uint8)
    frame[:, 700:] = np.random.default_rng(0).integers(0, 255, (720, 260, 3), dtype=np.uint8)
    kolommen = muur_kolommen(frame, 7)
    assert kolommen[0] > 0.95 and kolommen[-1] < 0.5
