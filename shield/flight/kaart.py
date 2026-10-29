"""Kansenkaart voor het zoeken: een prior over de kamer, bijgewerkt na elke blik, en A* om naartoe te vliegen.

Idee (Bayesiaans zoeken): elke cel van een raster krijgt een kans dat het kruis daar zit (de prior, nu overal gelijk).
Kijkt de drone ergens naar en ziet hij niets, dan daalt de kans in die cellen met de kans dat hij het kruis daar
gemist zou hebben. Het volgende standpunt is het punt met de meeste nog onzekere kans binnen bereik, gedeeld door de
afstand erheen (A* over cellen zonder muur). Is de kans die nog over is klein, dan is de ruimte afgezocht.

Coördinaten: meters vanaf het startpunt, hoeken in graden in de draairichting van rc-yaw vanaf de beginrichting.
Alle posities zijn geschat uit rc-tijd en draaihoek (dead reckoning) en dus onnauwkeurig.
Per hoogteniveau (-1, 0, 1) is er een eigen kansenkaart: wat laag niet gezien is, is hoog nog niet gezien.
"""

import heapq
import math
from typing import NamedTuple

import numpy as np

CEL_M = 0.5
KAMER_M = 6.0  # Het raster is KAMER_M x KAMER_M, met het startpunt in het midden.
N = int(KAMER_M / CEL_M)
KIJK_BEREIK_M = 3.0  # Een kruis van 20 cm is tot ongeveer zover te herkennen.
VLAK_BEREIK_M = 2.0  # Is een strook van het beeld vlak (muur), dan kijken we niet verder dan dit.
VLAK_MUUR = 0.95
CAMERA_HOEK = 65.0  # Horizontaal beeldveld van de Tello in graden (geschat).
KOLOMMEN = 7  # Het beeld wordt in zoveel stroken verdeeld, elk met een eigen kijkrichting.
MIN_WINST = 0.03  # Verwachte kans (van de totale kans 1.0) die een volgend standpunt minstens moet opleveren.
MIN_RESTKANS = 0.10  # Is de totale resterende kans lager dan dit, dan is de ruimte afgezocht.
MIN_VERPLAATSING_M = 1.0  # Op hetzelfde niveau opnieuw scannen vanaf bijna dezelfde plek levert weinig op: minstens zover weg.
WINST_BASIS_M = 1.0  # Maakt dat een heel dichtbij standpunt niet oneindig goed scoort.
NIVEAU_KOSTEN_M = 1.0  # Wat één hoogteniveau wisselen 'kost' in meters vliegen.
MUUR_VEILIG_M = 0.8  # Standpunten dichter bij een muur dan dit scoren lager (weg van de muur, naar het midden).
WAND_AFSTAND_M = 0.8  # Stopt de drone voor een muur, dan staat die ongeveer zover vóór hem.
WAND_BREEDTE_M = 1.5  # ...en we markeren zoveel breedte als muur.

_ASSEN = (np.arange(N) - N / 2 + 0.5) * CEL_M
_X, _Y = np.meshgrid(_ASSEN, _ASSEN)  # Index [y, x].
_AFSTANDEN = np.hypot(_X.reshape(-1, 1) - _X.reshape(1, -1), _Y.reshape(-1, 1) - _Y.reshape(1, -1))
_BUREN = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]

Cel = tuple[int, int]  # (rij = y, kolom = x)


def p_zie(afstand: np.ndarray | float) -> np.ndarray | float:
    """Kans dat we een kruis op deze afstand (m) zien als het in beeld is: dichtbij 90%, op 3 m ongeveer 45%."""
    return np.clip(1.05 - 0.2 * np.asarray(afstand), 0.3, 0.9)


class Besluit(NamedTuple):
    """Het gekozen volgende standpunt."""

    niveau: int
    doel: Cel
    winst: float  # Verwachte kans die het oplevert.
    route: list[Cel]  # A*-route van de huidige cel naar het doel.


def verschil_hoek(a: np.ndarray | float, b: float) -> np.ndarray | float:
    """Kleinste verschil tussen hoeken in graden (0..180)."""
    return np.abs((a - b + 180) % 360 - 180)


class Kaart:
    """Kansen per cel en hoogteniveau, bekende muren en onze geschatte positie."""

    def __init__(self, gewichten: tuple[float, ...] = (1.0, 1.0, 1.0)) -> None:
        """Eén kansenkaart per hoogteniveau (0, 1, 2, ...); `gewichten` is de prior per niveau."""
        self.wand = np.zeros((N, N), bool)
        self.buiten = np.zeros((N, N), bool)  # Cellen achter een muur: geen kruis en geen route.
        totaal = sum(gewichten)
        self.kansen = {n: np.full((N, N), g / totaal / (N * N)) for n, g in enumerate(gewichten)}
        self.x = self.y = 0.0

    @staticmethod
    def cel(x: float, y: float) -> Cel:
        """Cel (rij, kolom) bij een positie in meters, binnen het raster."""
        return (int(np.clip(math.floor(y / CEL_M + N / 2), 0, N - 1)), int(np.clip(math.floor(x / CEL_M + N / 2), 0, N - 1)))

    @staticmethod
    def midden(cel: Cel) -> tuple[float, float]:
        """Positie (x, y) in meters van het midden van een cel."""
        return float(_ASSEN[cel[1]]), float(_ASSEN[cel[0]])

    def verplaats(self, afstand_m: float, koers: float) -> None:
        self.x += afstand_m * math.cos(math.radians(koers))
        self.y += afstand_m * math.sin(math.radians(koers))

    def restkans(self) -> float:
        """Totale kans (0..1) dat het kruis nog ergens ligt waar we niet gekeken hebben."""
        return float(sum(k.sum() for k in self.kansen.values()))

    def bekijk(self, niveau: int, koers: float, kolommen: np.ndarray) -> None:
        """Verwerk één blik zonder kruis: de kans in alle cellen die we goed konden zien daalt."""
        dx, dy = _X - self.x, _Y - self.y
        afstand, hoek = np.hypot(dx, dy), np.degrees(np.arctan2(dy, dx))
        breedte = CAMERA_HOEK / len(kolommen)
        gezien = np.zeros((N, N))
        for k, muur in enumerate(kolommen):
            richting = koers + (k + 0.5) * breedte - CAMERA_HOEK / 2
            vlak = muur >= VLAK_MUUR
            in_wig = verschil_hoek(hoek, richting) <= breedte / 2
            if vlak:  # Een muur: alles daarachter ligt buiten de kamer.
                self.sluit_buiten(in_wig & (afstand > VLAK_BEREIK_M))
            in_beeld = in_wig & (afstand <= (VLAK_BEREIK_M if vlak else KIJK_BEREIK_M))
            gezien = np.where(in_beeld, np.maximum(gezien, p_zie(afstand)), gezien)
        self.kansen[niveau] *= 1 - gezien

    def sluit_buiten(self, cellen: np.ndarray) -> None:
        """Markeer cellen als buiten de kamer: geen kans meer en niet te bereiken."""
        self.buiten |= cellen
        for kans in self.kansen.values():
            kans[self.buiten] = 0.0

    def geblokkeerd(self) -> np.ndarray:
        """Cellen waar de drone niet door kan: bekende muren en alles wat buiten de kamer ligt."""
        return self.wand | self.buiten

    def afstand_tot_muur(self) -> np.ndarray:
        """Per cel de afstand (m) tot de dichtstbijzijnde geblokkeerde cel (oneindig als er geen is)."""
        blok = self.geblokkeerd().reshape(-1)
        if not blok.any():
            return np.full((N, N), np.inf)
        return _AFSTANDEN[:, blok].min(axis=1).reshape(N, N)

    def markeer_wand(self, koers: float, afstand_m: float = WAND_AFSTAND_M) -> None:
        """De drone stopte voor een muur: markeer een stuk muur vóór hem (geen kans meer en niet doorheen vliegen)."""
        r = math.radians(koers)
        mx, my = self.x + afstand_m * math.cos(r), self.y + afstand_m * math.sin(r)
        for t in np.arange(-WAND_BREEDTE_M / 2, WAND_BREEDTE_M / 2 + 1e-9, CEL_M / 2):
            cel = self.cel(mx - t * math.sin(r), my + t * math.cos(r))
            self.wand[cel] = True
            for kans in self.kansen.values():
                kans[cel] = 0.0

    def winst_per_cel(self, niveau: int) -> np.ndarray:
        """Per cel: verwachte kans die een blik rondom vanaf die cel oplevert."""
        p = np.where(_AFSTANDEN <= KIJK_BEREIK_M, p_zie(_AFSTANDEN), 0.0)
        return (p @ self.kansen[niveau].reshape(-1)).reshape(N, N)

    def afstanden(self, start: Cel) -> np.ndarray:
        """Kortste afstand (m) over vrije cellen van `start` naar elke cel (Dijkstra); oneindig als onbereikbaar."""
        blok = self.geblokkeerd()
        dist = np.full((N, N), np.inf)
        dist[start] = 0.0
        wachtrij = [(0.0, start)]
        while wachtrij:
            d, (r, c) = heapq.heappop(wachtrij)
            if d > dist[r, c]:
                continue
            for dr, dc in _BUREN:
                nr, nc = r + dr, c + dc
                if 0 <= nr < N and 0 <= nc < N and not blok[nr, nc]:
                    nd = d + CEL_M * math.hypot(dr, dc)
                    if nd < dist[nr, nc]:
                        dist[nr, nc] = nd
                        heapq.heappush(wachtrij, (nd, (nr, nc)))
        return dist

    def route(self, start: Cel, doel: Cel) -> list[Cel]:
        """Kortste route van start naar doel over vrije cellen met A* (hemelsbrede afstand als schatting)."""
        if start == doel:
            return [start]
        blok = self.geblokkeerd()
        g, vorige = {start: 0.0}, {}
        wachtrij = [(0.0, start)]
        while wachtrij:
            _, cel = heapq.heappop(wachtrij)
            if cel == doel:
                pad = [cel]
                while pad[-1] in vorige:
                    pad.append(vorige[pad[-1]])
                return pad[::-1]
            for dr, dc in _BUREN:
                buur = (cel[0] + dr, cel[1] + dc)
                if not (0 <= buur[0] < N and 0 <= buur[1] < N) or blok[buur]:
                    continue
                nieuw = g[cel] + CEL_M * math.hypot(dr, dc)
                if nieuw < g.get(buur, np.inf):
                    g[buur], vorige[buur] = nieuw, cel
                    heapq.heappush(wachtrij, (nieuw + CEL_M * math.hypot(buur[0] - doel[0], buur[1] - doel[1]), buur))
        return []

    def kies(self, niveau: int, mogelijke_niveaus: set[int]) -> Besluit | None:
        """Beste volgende standpunt: de meeste verwachte winst per meter vliegen, of None als er niets zinvols meer is."""
        if self.restkans() < MIN_RESTKANS:
            return None
        start = self.cel(self.x, self.y)
        afstand, muur_afstand = self.afstanden(start), self.afstand_tot_muur()
        veilig = np.clip(muur_afstand / MUUR_VEILIG_M, 0.2, 1.0)  # Dicht bij een muur: lagere score.
        beste: tuple[float, Besluit] | None = None
        for n in mogelijke_niveaus & set(self.kansen):
            winst = self.winst_per_cel(n)
            kosten = afstand + NIVEAU_KOSTEN_M * abs(n - niveau)
            mogelijk = np.isfinite(afstand) & ~self.geblokkeerd() & ((afstand >= MIN_VERPLAATSING_M) | (n != niveau))
            score = np.where(mogelijk, winst * veilig / (kosten + WINST_BASIS_M), -1.0)
            doel = np.unravel_index(int(np.argmax(score)), score.shape)
            if score[doel] > 0 and winst[doel] >= MIN_WINST and (beste is None or score[doel] > beste[0]):
                doel_cel = (int(doel[0]), int(doel[1]))
                beste = (float(score[doel]), Besluit(n, doel_cel, float(winst[doel]), self.route(start, doel_cel)))
        return None if beste is None else beste[1]


def rechte_stukken(route: list[Cel]) -> list[Cel]:
    """Knikpunten van een route: tussen twee opeenvolgende punten kan de drone in een rechte lijn vliegen."""
    if len(route) < 3:
        return route[1:]
    punten = []
    for i in range(1, len(route) - 1):
        if (route[i][0] - route[i - 1][0], route[i][1] - route[i - 1][1]) != (route[i + 1][0] - route[i][0], route[i + 1][1] - route[i][1]):
            punten.append(route[i])
    return punten + [route[-1]]


def peiling_en_afstand(van: tuple[float, float], naar: tuple[float, float]) -> tuple[float, float]:
    """Hoek (graden, 0..360, in de draairichting van rc-yaw) en afstand (m) van het ene punt naar het andere."""
    dx, dy = naar[0] - van[0], naar[1] - van[1]
    return math.degrees(math.atan2(dy, dx)) % 360, math.hypot(dx, dy)
