"""Show whether the Tello camera can see the yellow and green markers.

Run from the apps repository root:
    python -m klm.vision.marker_test

This is a camera-only test. It does not take off or control flight.
"""

import cv2
from djitellopy import Tello


tello = Tello()
tello.connect()
tello.streamon()
camera = tello.get_frame_read()

while True:
    beeld = camera.frame.copy()

    # The Tello frame appears to be RGB; convert it for correct display.
    hsv = cv2.cvtColor(beeld, cv2.COLOR_RGB2HSV)
    scherm = cv2.cvtColor(beeld, cv2.COLOR_RGB2BGR)

    # Initial colour ranges. Lighting may mean we need to adjust these.
    geel_masker = cv2.inRange(hsv, (18, 70, 70), (40, 255, 255))
    groen_masker = cv2.inRange(hsv, (35, 45, 40), (90, 255, 255))

    geel_vormen, _ = cv2.findContours(geel_masker, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    groen_vormen, _ = cv2.findContours(groen_masker, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for vorm in geel_vormen:
        if cv2.contourArea(vorm) > 100:
            x, y, w, h = cv2.boundingRect(vorm)
            cv2.rectangle(scherm, (x, y), (x + w, y + h), (0, 255, 255), 2)
            cv2.putText(scherm, "GEEL", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    for vorm in groen_vormen:
        if cv2.contourArea(vorm) > 100:
            x, y, w, h = cv2.boundingRect(vorm)
            cv2.rectangle(scherm, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(scherm, "GROEN", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    cv2.imshow("Tello - herkenning geel en groen", scherm)
    cv2.imshow("Geel masker", geel_masker)
    cv2.imshow("Groen masker", groen_masker)

    if cv2.waitKey(1) == ord("q"):
        break


tello.streamoff()
tello.end()
cv2.destroyAllWindows()
