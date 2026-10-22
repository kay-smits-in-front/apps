"""Supervised first flight: take off, move forward, turn around, then descend until yellow is seen.

Run from the apps repository root:
    python -m klm.connection.yellow_marker_flight

Safety:
- Start in a clear indoor area, with the yellow X visible on the floor.
- This is an early vision test, not a guaranteed autonomous landing system.
- The Tello's forward-facing camera may still not see a floor marker.
- Descent happens in small steps, stopping when yellow is detected or the safe search limit is reached.
- The script stops for user confirmation before any marker-guided approach/landing.
- Press Q in the camera window to abort; the script will attempt to land.
"""

import time

import cv2
import numpy as np
from djitellopy import Tello


MIN_BATTERY = 40
FORWARD_CM = 30
DESCEND_STEP_CM = 20
MAX_DESCENT_STEPS = 5
HOVER_SECONDS = 2
YELLOW_MIN_AREA = 180


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


def zoeken(tello, camera):
    """Descend 20 cm at a time until the yellow marker appears."""
    for stap in range(MAX_DESCENT_STEPS):
        print(f"Dalen: stap {stap + 1}/{MAX_DESCENT_STEPS} ({DESCEND_STEP_CM} cm)...")
        tello.move_down(DESCEND_STEP_CM)
        time.sleep(HOVER_SECONDS)

        # After each small descent, check the live image for the yellow marker.
        frame = camera.frame
        if frame is None:
            continue

        display, mask, marker = find_yellow_marker(frame.copy())
        cv2.imshow("Tello - gele marker", display)
        cv2.imshow("Geel masker", mask)
        cv2.waitKey(1)

        if marker:
            print("Geel kruis gevonden!")
            return marker

    print("Gele kruis niet gevonden binnen de ingestelde daalafstand.")
    return None


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

        print("Dalen in stappen van 20 cm tot het gele kruis wordt herkend.")
        print("Druk op Q in het cameravenster om de zoekactie af te breken.")
        marker = zoeken(tello, camera)
        cv2.destroyAllWindows()

        if marker is None:
            print("Geen geel kruis gevonden, of zoeken afgebroken. We landen op de huidige plek.")
            return

        print(
            "Het gele kruis is zichtbaar, maar de camera kan niet bewijzen dat de drone "
            "erboven hangt."
        )
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
