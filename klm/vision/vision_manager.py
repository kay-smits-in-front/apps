"""Future coordinator for person and hand-gesture recognition."""

from klm.vision.face_recognition import recognize_person
from klm.vision.gesture_recognition import recognize_gesture


def analyze_frame(frame):
    """Run vision modules on a frame once those modules are implemented."""
    return {
        "person": recognize_person(frame),
        "gesture": recognize_gesture(frame),
    }
