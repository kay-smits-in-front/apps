"""Slim zoeken: onthoud wat per 360-graden scan gezien is en kies daaruit waar we heen vliegen.

Geen kaart (de positie uit de drone is te onbetrouwbaar), maar per standpunt een dekking per richting:
hoeveel beelden, hoe vlak (muur) en hoe goed de beste kruis-kandidaat was. Alle hoeken zijn graden in de
draairichting van rc-yaw, gemeten vanaf de richting waarin de drone aan de scan begon. Alles hier is puur
rekenwerk, zonder drone, en dus testbaar.
"""

import numpy as np

SECTOR_GRADEN = 10
AANTAL_SECTOREN = 360 // SECTOR_GRADEN
VENSTER_SECTOREN = 3  # Bij het kiezen van een richting kijken we ±3 sectoren (±30 graden) mee.
MIN_OPEN = 0.10  # Minder 'open' dan dit (aandeel niet-vlak beeld): geen weg om doorheen te vliegen.
TERUG_STRAF_GRADEN = 50  # Richtingen binnen zoveel graden van waar we vandaan kwamen krijgen een straf.
TERUG_STRAF = 0.5
MIN_DEKKING = 0.9  # Aandeel sectoren dat gezien moet zijn om een standpunt 'rondgekeken' te noemen.


class Dekking:
    """Wat één 360-scan gezien heeft, per richting van 10 graden."""

    def __init__(self) -> None:
        self.aantal = np.zeros(AANTAL_SECTOREN, int)
        self.muur_som = np.zeros(AANTAL_SECTOREN)
        self.beste_score = np.zeros(AANTAL_SECTOREN)

    @staticmethod
    def sector(graden: float) -> int:
        return int((graden % 360) // SECTOR_GRADEN)

    def registreer(self, graden: float, muur: float, score: float) -> None:
        """Verwerk één beeld, genomen terwijl de drone `graden` was gedraaid."""
        i = self.sector(graden)
        self.aantal[i] += 1
        self.muur_som[i] += muur
        self.beste_score[i] = max(self.beste_score[i], score)

    def gezien(self) -> float:
        """Aandeel van de sectoren (0..1) waar minstens één beeld van is."""
        return float((self.aantal > 0).mean())

    def open_per_sector(self) -> np.ndarray:
        """Per sector hoe 'open' het is (0 = vlakke muur, 1 = veel te zien). Onbekend telt als 0."""
        gemiddeld = np.divide(self.muur_som, self.aantal, out=np.ones(AANTAL_SECTOREN), where=self.aantal > 0)
        return 1.0 - gemiddeld


def gladstrijken(waarden: np.ndarray, venster: int = VENSTER_SECTOREN) -> np.ndarray:
    """Gemiddelde over ±venster sectoren, rondom (355 graden grenst aan 5 graden)."""
    return np.mean([np.roll(waarden, k) for k in range(-venster, venster + 1)], axis=0)


def kies_richting(dekking: Dekking, terug: list[float]) -> float | None:
    """Richting (graden) met de meeste open ruimte, behalve richting waar we net vandaan kwamen.

    Geeft None als alles vlak is: er is geen weg om doorheen te vliegen.
    """
    open_ruimte = gladstrijken(dekking.open_per_sector())
    midden = np.arange(AANTAL_SECTOREN) * SECTOR_GRADEN + SECTOR_GRADEN / 2
    for t in terug:
        verschil = np.abs((midden - t + 180) % 360 - 180)
        open_ruimte = np.where(verschil < TERUG_STRAF_GRADEN, open_ruimte * TERUG_STRAF, open_ruimte)
    beste = int(np.argmax(open_ruimte))
    return float(midden[beste]) if open_ruimte[beste] >= MIN_OPEN else None


def kies_stap_hoogte(niveau: int, bezocht: set[int], mogelijk: list[str]) -> str | None:
    """Naar welk aangrenzend hoogteniveau voor de volgende scan? Eerst omlaag (bureau, bed), dan omhoog.

    `mogelijk` zijn de richtingen die binnen de hoogtegrenzen vallen. None: beide buren zijn al bezocht.
    """
    for naam, stap in (("omlaag", -1), ("omhoog", 1)):
        if naam in mogelijk and (niveau + stap) not in bezocht:
            return naam
    return None


class Geheugen:
    """Wat we tot nu toe doorzocht hebben: bezochte hoogteniveaus en de richting terug naar eerdere standpunten."""

    def __init__(self) -> None:
        self.niveau = 0
        self.bezocht = {0}
        self.terug: list[float] = []
        self.dekkingen: list[Dekking] = []

    def leg_vast(self, dekking: Dekking) -> None:
        self.dekkingen.append(dekking)

    def gedraaid(self, graden: float) -> None:
        """De drone draaide `graden`: de richtingen terug schuiven mee."""
        self.terug = [(t - graden) % 360 for t in self.terug]

    def verplaatst(self) -> None:
        """De drone vloog vooruit: het vorige standpunt ligt nu recht achter ons."""
        self.terug.append(180.0)

    def veranderd_van_niveau(self, stap: str) -> None:
        self.niveau += 1 if stap == "omhoog" else -1
        self.bezocht.add(self.niveau)
