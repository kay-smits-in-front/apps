"""Simple, supervised take-off and landing test for the DJI Tello.

Run from the apps repository root:
    python -m klm.connection.takeoff_test

The drone will take off, hover briefly, and land. Test in a clear area.
"""
from time import sleep

from djitellopy import Tello


tello = Tello()

try:
    print("Verbinden met de Tello...")
    tello.connect()

    batterij = tello.get_battery()
    print(f"Batterij: {batterij}%")

    if batterij < 30:
        print("Batterij is lager dan 30%. Test afgebroken.")
    else:
        akkoord = input(
            "Zorg dat de ruimte vrij is en de drone stabiel staat. "
            "Typ TAKEOFF om op te stijgen: "
        )

        if akkoord == "TAKEOFF":
            print("Opstijgen...")
            tello.takeoff()

            print("3 seconden blijven zweven...")
            sleep(3)

            print("Landen...")
            tello.land()
            print("Test afgerond.")
        else:
            print("Afgebroken. De drone is niet opgestegen.")

finally:
    tello.end()
