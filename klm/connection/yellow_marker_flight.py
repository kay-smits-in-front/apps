"""Supervised first flight: take off, move forward, turn, then find the yellow marker.

Run from the apps repository root:
    python -m klm.connection.yellow_marker_flight

Safety:
- Start in a clear indoor area, with the yellow X visible on the floor.
- This is an early vision test, not a guaranteed autonomous landing system.
- The Tello's forward-facing camera cannot prove that it is directly above a floor marker.
- The script stops for user confirmation before any marker-guided approach/landing.
- Press Q in the camera window to abort; the script will attempt to land.
"""

import time

import cv2
import numpy as np
from djitellopy import Tello


MIN_BATTERY = 40
FORWARD_CM = 30
HOVER_SECONDS = 2
YELLOW_MIN_AREA = 180
CAMERA_TIMEOUT_SECONDS = 20


def find_yellow_marker(frame):
    """Return display frame and the center/area of the largest yellow region."""
    # DJITelloPy frames are RGB. Convert for HSV detection and OpenCV display.
    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    display = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    # Initial yellow range; adjust after testing with the actual room lighting.
    mask = cv2.inRange(hsv, np.array((18, 70, 70)), np.array((40, 255, 255)))
    mask = cv2.medianBlur(mask, 5)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if cv2.contourArea(c) >= YELLOW_MIN_AREA]

    if not valid:
        return display, mask, None

    largest = max(valid, key=cv2.contourArea)
    moments = cv2.moments(largest)
    if moments["m00"] == 0:
        return display, mask, None

    center_x = int(moments["m10"] / moments["m00"])
    center_y = int(moments["m01"] / moments["m00"])
    area = cv2.contourArea(largest)

    cv2.drawContours(display, [largest], -1, (0, 255, 255), 2)
    cv2.circle(display, (center_x, center_y), 7, (0, 0, 255), -1)
    cv2.putText(
        display,
        f"GEEL GEZIEN - oppervlak: {int(area)}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 255),
        2,
    )
    return display, mask, (center_x, center_y, area)


def main():
    tello = Tello()
    connected = False
    airborne = False
    stream_started = False

    try:
        print("Verbinding maken met TELLO-52D2C8...")
        tello.connect()
        connected = True

        battery = tello.get_battery()
        print(f"Batterij: {battery}%")
        if battery < MIN_BATTERY:
            print(f"Afgebroken: minimaal {MIN_BATTERY}% batterij vereist.")
            return

        akkoord = input(
            "Maak de ruimte vrij en leg het gele kruis op de vloer. "
            "Typ START om de test te beginnen: "
        ).strip()
        if akkoord != "START":
            print("Test afgebroken; de drone stijgt niet op.")
            return

        tello.streamon()
        stream_started = True
        camera = tello.get_frame_read()

        print("Opstijgen...")
        tello.takeoff()
        airborne = True
        time.sleep(HOVER_SECONDS)

        print(f"{FORWARD_CM} cm naar voren...")
        tello.move_forward(FORWARD_CM)
        time.sleep(1)

        print("180 graden draaien...")
        tello.rotate_clockwise(180)
        time.sleep(HOVER_SECONDS)

        print("Camera zoeken naar het gele kruis. Druk Q in het cameravenster om af te breken.")
        start_time = time.monotonic()
        marker_seen = False

        while time.monotonic() - start_time < CAMERA_TIMEOUT_SECONDS:
            frame = camera.frame
            if frame is None:
                time.sleep(0.1)
                continue

            display, mask, marker = find_yellow_marker(frame.copy())
            if marker:
                marker_seen = True
                cv2.putText(
                    display,
                    "Kruis gevonden - nog NIET automatisch landen",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    2,
                )
            else:
                cv2.putText(
                    display,
                    "Zoeken naar geel...",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )

            cv2.imshow("Tello - gele marker", display)
            cv2.imshow("Geel masker", mask)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("Afgebroken via Q.")
                return
            if marker_seen:
                break

        cv2.destroyAllWindows()

        if not marker_seen:
            print("Geen geel kruis gevonden binnen de zoektijd. We landen op de huidige plek.")
            return

        print(
            "Het gele kruis is zichtbaar, maar de camera kan niet bewijzen dat de drone "
            "erboven hangt."
        )
        print("De drone blijft op zijn huidige hoogte; er wordt niet automatisch naar de vloer gevlogen.")
        input(
            "Controleer de positie en de vrije ruimte. Druk op Enter om de drone "
            "op zijn huidige plek te laten landen: "
        )
        print("Landen...")
        tello.land()
        airborne = False
        print("Test afgerond.")

    except KeyboardInterrupt:
        print("\nOnderbroken. Er wordt geprobeerd veilig te landen.")
    except Exception as exc:
        print(f"Fout tijdens de test: {exc}")
    finally:
        cv2.destroyAllWindows()
        if connected:
            if airborne:
                try:
                    tello.land()
                except Exception as exc:
                    print(f"Automatisch landen lukte niet: {exc}")
            if stream_started:
                try:
                    tello.streamoff()
                except Exception:
                    pass
            try:
                tello.end()
            except Exception:
                pass


if __name__ == "__main__":
    main()
