"""Eenvoudige Tello-test: camerabeeld vooraf controleren, opstijgen, vooruit, draaien en geel zoeken.

Start vanuit de map apps:
    python klm/connection/yellow_marker_flight.py
"""

import time

import cv2
import numpy as np
from djitellopy import Tello


MIN_BATTERY = 40
FORWARD_CM = 60
DESCEND_STEP_CM = 20
MAX_DESCENT_STEPS = 8
YELLOW_MIN_AREA = 180


def find_yellow_marker(frame):
    """Herken een geel vlak in het RGB-camerabeeld."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    display = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    mask = cv2.inRange(hsv, np.array((18, 70, 70)), np.array((40, 255, 255)))
    mask = cv2.medianBlur(mask, 5)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    geel = [contour for contour in contours if cv2.contourArea(contour) >= YELLOW_MIN_AREA]

    if not geel:
        return display, mask, False

    grootste = max(geel, key=cv2.contourArea)
    cv2.drawContours(display, [grootste], -1, (0, 255, 255), 2)
    cv2.putText(display, "GEEL HERKEND", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 255, 255), 2)
    return display, mask, True


def toon_camera(camera):
    """Toon live beeld en meld of geel zichtbaar is."""
    frame = camera.frame
    if frame is None:
        return False

    display, mask, geel = find_yellow_marker(frame.copy())
    cv2.imshow("Tello - camera en gele marker (Q = stoppen)", display)
    cv2.imshow("Geel masker", mask)
    cv2.waitKey(1)
    return geel


tello = Tello()

print("Verbinding maken met TELLO-52D2C8...")
tello.connect()
print(f"Batterij: {tello.get_battery()}%")

if tello.get_battery() < MIN_BATTERY:
    print(f"Stop: laad de batterij eerst op tot minstens {MIN_BATTERY}%.")
else:
    tello.streamon()
    camera = tello.get_frame_read()

    print("Controleer eerst het beeld terwijl de drone op de grond blijft.")
    print("Geel moet zichtbaar zijn in het camerabeeld. Druk Q in het cameravenster om te stoppen.")
    time.sleep(2)

    beeld_ok = False
    for _ in range(30):
        beeld_ok = toon_camera(camera)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
        time.sleep(0.1)

    if beeld_ok:
        start = input("Geel wordt herkend. Maak de ruimte vrij en typ START: ").strip()

        if start == "START":
            print("Opstijgen...")
            tello.takeoff()
            time.sleep(3)

            print(f"{FORWARD_CM} cm naar voren...")
            tello.move_forward(FORWARD_CM)
            time.sleep(3)

            print("Even wachten voordat de drone draait...")
            time.sleep(5)
            print("180 graden draaien...")
            tello.rotate_clockwise(180)
            time.sleep(3)

            print("Nu in stappen van 20 cm dalen tot geel wordt herkend.")
            geel_gevonden = False

            for stap in range(MAX_DESCENT_STEPS):
                if toon_camera(camera):
                    print("Geel kruis herkend. Stoppen met zoeken.")
                    geel_gevonden = True
                    break

                print(f"Dalen: stap {stap + 1}/{MAX_DESCENT_STEPS}, {DESCEND_STEP_CM} cm.")
                tello.move_down(DESCEND_STEP_CM)
                time.sleep(2)

            if geel_gevonden:
                input("Controleer de positie. Druk op Enter om op de huidige plek te landen: ")
            else:
                print("Geel niet gevonden binnen de ingestelde zoekafstand.")

            tello.land()
            print("Test afgerond.")
        else:
            print("Gestopt; de drone is niet opgestegen.")
    else:
        print("Geel werd niet herkend in het camerabeeld. De drone blijft op de grond.")

    cv2.destroyAllWindows()
    tello.streamoff()

tello.end()
