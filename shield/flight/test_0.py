"""Test 0: alleen opstijgen, 4 s stil zweven, landen. Logt wat de drone zelf meet.

Doel: zien of de drone zijn eigen drift opmerkt. Start vanuit de projectroot:
    python -m shield.flight.test_0

Schrijft shield/flight/telemetrie.csv en print één samenvatting.
"""

import time
from pathlib import Path

import numpy as np

from shield.flight.drone import vlucht_met_camera
from shield.flight.sturing import STIL

ZWEEF_S = 4.0
VELDEN = ("vgx", "vgy", "vgz", "pitch", "roll", "yaw", "h", "tof")
PAD = Path(__file__).with_name("telemetrie.csv")


def zweef_en_meet(tello, seconden: float) -> np.ndarray:
    """Zweef stil en geef per meting [t, *VELDEN] terug."""
    start = time.monotonic()
    rijen = []
    while (t := time.monotonic() - start) < seconden:
        tello.send_rc_control(*STIL)
        staat = tello.get_current_state()
        rijen.append([t, *(staat[veld] for veld in VELDEN)])
        time.sleep(0.05)
    return np.array(rijen, dtype=float)


def samenvatting(metingen: np.ndarray) -> str:
    """Waarden in 'eenheid x seconde': deel door het gemeten afstandsverschil voor de schaal."""
    t, vgx, vgy = metingen[:, 0], metingen[:, 1], metingen[:, 2]
    ix, iy = np.trapezoid(vgx, t), np.trapezoid(vgy, t)
    return (
        f"snelheid-integraal x={ix:.1f} y={iy:.1f} | max |vgx|={abs(vgx).max():.0f} "
        f"max |vgy|={abs(vgy).max():.0f} | max pitch={abs(metingen[:, 4]).max():.0f} "
        f"roll={abs(metingen[:, 5]).max():.0f} | hoogte {metingen[0, 7]:.0f}->{metingen[-1, 7]:.0f}"
    )


def main() -> None:
    with vlucht_met_camera() as vlucht:
        input("Open ruimte, gordijn weg, drone op de vloer. Enter = opstijgen: ")
        vlucht.tello.takeoff()
        metingen = zweef_en_meet(vlucht.tello, ZWEEF_S)
        np.savetxt(PAD, metingen, delimiter=",", header="t," + ",".join(VELDEN), comments="")
        print(samenvatting(metingen))


if __name__ == "__main__":
    main()
