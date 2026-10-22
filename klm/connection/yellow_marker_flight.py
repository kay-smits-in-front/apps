"""Supervised Tello flight: search for a yellow floor marker, then cautiously approach it.

Run from the apps repository root:
    python -m klm.connection.yellow_marker_flight

IMPORTANT:
- This is experimental visual-servo code, not a certified landing system.
- The forward-facing camera cannot reliably prove that the drone is directly above a floor marker.
- Test only in a large, clear, netted/soft area, with a spotter ready to intervene.
- Press Q in the camera window to stop the automatic sequence; the script will attempt to land.
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

# Visual approach uses low-speed RC pulses, not long blind movements.
APPROACH_SPEED = 10
APPROACH_PULSE_SECONDS = 0.35
APPROACH_PAUSE_SECONDS = 0.5
MAX_APPROACH_SECONDS = 20
CENTER_TOLERANCE = 0.12
LANDING_MARKER_AREA = 7000
MAX_LOST_FRAMES = 5


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


def show_camera(frame):
    """Show the camera view and return True when Q was pressed."""
    display, mask, marker = find_yellow_marker(frame.copy())
    cv2.imshow("Tello - gele marker (Q = stoppen)", display)
    cv2.imshow("Geel masker", mask)
    return marker, (cv2.waitKey(1) & 0xFF) == ord("q")


def zoeken(tello, camera):
    """Descend 20 cm at a time until the yellow marker appears or Q is pressed."""
    for stap in range(MAX_DESCENT_STEPS):
        frame = camera.frame
        if frame is not None:
            marker, stop = show_camera(frame)
            if stop:
                print("Zoeken afgebroken met Q.")
                return None
            if marker:
                print("Geel kruis gevonden!")
                return marker

        print(f"Dalen: stap {stap + 1}/{MAX_DESCENT_STEPS} ({DESCEND_STEP_CM} cm)...")
        tello.move_down(DESCEND_STEP_CM)
        time.sleep(HOVER_SECONDS)

    print("Gele kruis niet gevonden binnen de ingestelde daalafstand.")
    return None


def nader_en_landen(tello, camera):
    """Use short, low-speed corrections to approach the marker and land when it looks large.

    This is only a cautious prototype: marker pixel area is not a reliable distance
    measurement, so the landing threshold must be validated in controlled tests.
    """
    print("Marker volgen gestart. Druk op Q in het cameravenster om te stoppen.")
    start = time.monotonic()
    lost_frames = 0

    while time.monotonic() - start < MAX_APPROACH_SECONDS:
        frame = camera.frame
        if frame is None:
            tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.1)
            continue

        marker, stop = show_camera(frame)
        if stop:
            print("Nadering afgebroken met Q.")
            tello.send_rc_control(0, 0, 0, 0)
            return False

        if marker is None:
            lost_frames += 1
            tello.send_rc_control(0, 0, 0, 0)
            print(f"Kruis niet zichtbaar ({lost_frames}/{MAX_LOST_FRAMES}); beweging gepauzeerd.")
            if lost_frames >= MAX_LOST_FRAMES:
                print("Kruis te lang kwijt. Geen autonome landing uitgevoerd.")
                return False
            time.sleep(APPROACH_PAUSE_SECONDS)
            continue

        lost_frames = 0
        center_x, center_y, area = marker
        height, width = frame.shape[:2]
        x_error = (center_x - width / 2) / width

        # First align horizontally using very short sideways RC pulses.
        if x_error < -CENTER_TOLERANCE:
            tello.send_rc_control(-APPROACH_SPEED, 0, 0, 0)
            print("Kruis links in beeld: kleine correctie naar links.")
        elif x_error > CENTER_TOLERANCE:
            tello.send_rc_control(APPROACH_SPEED, 0, 0, 0)
            print("Kruis rechts in beeld: kleine correctie naar rechts.")
        elif area >= LANDING_MARKER_AREA:
            tello.send_rc_control(0, 0, 0, 0)
            print(
                "Kruis groot en horizontaal gecentreerd. "
                "De beeldgrootte is slechts een ruwe aanwijzing; landen wordt geprobeerd."
            )
            time.sleep(0.5)
            tello.land()
            return True
        else:
            # Approach and descend together in short pulses. The marker is kept near
            # the horizontal center; this does NOT prove the drone is over the X.
            vertical = APPROACH_SPEED if center_y > height * 0.35 else 0
            tello.send_rc_control(0, APPROACH_SPEED, -vertical, 0)
            print("Kleine stap richting het kruis, met voorzichtige daling.")

        time.sleep(APPROACH_PULSE_SECONDS)
        tello.send_rc_control(0, 0, 0, 0)
        time.sleep(APPROACH_PAUSE_SECONDS)

    tello.send_rc_control(0, 0, 0, 0)
    print("Maximale naderingtijd bereikt; autonome landing niet bevestigd.")
    return False


def main():
    tello = Tello()
    connected = False
    airborne = False
    stream_started = False
    landed = False

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
        marker = zoeken(tello, camera)
        if marker is None:
            print("Geen kruis gevonden of zoeken afgebroken. Er wordt op de huidige plek geland.")
            return

        print(
            "Kruis herkend. Controleer dat de vliegzone vrij is en houd de drone in zicht. "
            "De nadering is experimenteel."
        )
        akkoord = input("Typ NADER om de korte visuele nadering en landing te starten: ").strip()
        if akkoord != "NADER":
            print("Nadering afgebroken; er wordt op de huidige plek geland.")
            return

        landed = nader_en_landen(tello, camera)
        if landed:
            airborne = False
            print("Landing-commando gegeven.")
        else:
            print("Automatische landing niet bevestigd. Er wordt op de huidige plek geland.")
            tello.land()
            airborne = False

    except KeyboardInterrupt:
        print("\nOnderbroken. Er wordt geprobeerd veilig te landen.")
    except Exception as exc:
        print(f"Fout tijdens de test: {exc}")
    finally:
        try:
            tello.send_rc_control(0, 0, 0, 0)
        except Exception:
            pass
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
