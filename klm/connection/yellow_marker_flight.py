"""Tello: live geelherkenning, opstijgen, 60 cm vooruit, draaien en dalen tot geel wordt gezien.

Start vanuit de map apps:
    python klm/connection/yellow_marker_flight.py
"""

import threading
import time

import cv2
from djitellopy import Tello

MIN_BATTERY = 40
FORWARD_CM = 60
DESCEND_STEP_CM = 20


tello = Tello()
print("Verbinding maken met TELLO-52D2C8...")
tello.connect()
battery = tello.get_battery()
print(f"Batterij: {battery}%")

if battery >= MIN_BATTERY:
    tello.streamon()
    camera = tello.get_frame_read()
    geel_gevonden = threading.Event()

    def toon_live_beeld():
        while not stop_beeld.is_set():
            beeld = camera.frame
            if beeld is None:
                continue

            # Zelfde RGB- en kleurherkenning als klm/vision/marker_test.py.
            hsv = cv2.cvtColor(beeld, cv2.COLOR_RGB2HSV)
            scherm = cv2.cvtColor(beeld, cv2.COLOR_RGB2BGR)
            geel_masker = cv2.inRange(hsv, (18, 70, 70), (40, 255, 255))
            geel_vormen, _ = cv2.findContours(
                geel_masker, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for vorm in geel_vormen:
                if cv2.contourArea(vorm) > 100:
                    x, y, w, h = cv2.boundingRect(vorm)
                    cv2.rectangle(scherm, (x, y), (x + w, y + h), (0, 255, 255), 2)
                    cv2.putText(
                        scherm, "GEEL", (x, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2
                    )
                    geel_gevonden.set()

            cv2.imshow("Tello - live herkenning geel (Q = stoppen)", scherm)
            cv2.imshow("Geel masker", geel_masker)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_beeld.set()

    stop_beeld = threading.Event()
    beeld_thread = threading.Thread(target=toon_live_beeld, daemon=True)
    beeld_thread.start()

    print("Live camerabeeld gestart; geel hoeft nog niet zichtbaar te zijn.")
    input("Leg de drone vlak neer, maak de ruimte vrij en druk Enter om op te stijgen: ")

    print("Opstijgen...")
    tello.takeoff()
    time.sleep(3)

    print(f"{FORWARD_CM} cm vooruit...")
    tello.move_forward(FORWARD_CM)
    time.sleep(4)

    print("Wachten tot de IMU stabiel is...")
    time.sleep(5)
    print("180 graden draaien...")
    tello.rotate_clockwise(180)
    time.sleep(3)

    print("Dalen in stappen van 20 cm; live herkenning blijft draaien.")
    while not geel_gevonden.is_set() and not stop_beeld.is_set():
        print(f"{DESCEND_STEP_CM} cm dalen...")
        tello.move_down(DESCEND_STEP_CM)
        time.sleep(1)

    tello.send_rc_control(0, 0, 0, 0)
    if geel_gevonden.is_set():
        print("Geel herkend. Stoppen met zoeken.")
    else:
        print("Zoeken gestopt met Q.")

    input("Controleer de situatie en druk op Enter om te landen: ")
    tello.land()

    stop_beeld.set()
    beeld_thread.join()
    tello.streamoff()
    tello.end()
    cv2.destroyAllWindows()
else:
    print(f"Niet opgestegen: minimaal {MIN_BATTERY}% batterij vereist.")
    tello.end()
