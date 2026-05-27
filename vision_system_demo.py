import cv2
import numpy as np
import json
import datetime
import time

# ============================================================
#  DEMO MODE — runs on any PC without a Raspberry Pi
#  GPIO is fully simulated. Press SPACE to simulate the UR5
#  sending a 3.3V trigger signal to the Pi.
# ============================================================

DISPLAY_WIDTH  = 1024
DISPLAY_HEIGHT = 600
PANEL_WIDTH    = 300

EXIT_BTN = (20, 20, 120, 50)

RESULTS_FILE = "results_log.json"
SAVE_FILE    = "rois.json"

exit_requested     = False
last_saved_results = None
freeze_until       = 0

# --- Mock GPIO ---
# Tries to use gpiozero's built-in mock pin factory.
# Falls back to simple dummy classes if gpiozero is not installed.
OUTPUT_PIN_NUMBERS = [17, 18, 27, 22, 23, 24, 25, 5]
TRIGGER_PIN        = 4

try:
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory
    Device.pin_factory = MockFactory()          # force mock — no real hardware used
    from gpiozero import OutputDevice, DigitalInputDevice

    output_pins  = [OutputDevice(pin) for pin in OUTPUT_PIN_NUMBERS]
    trigger      = DigitalInputDevice(TRIGGER_PIN, pull_up=False)
    mock_trigger = Device.pin_factory.pin(TRIGGER_PIN)  # direct handle to drive the pin
    USE_GPIOZERO_MOCK = True
    print("[DEMO] gpiozero MockFactory active")

except ImportError:
    USE_GPIOZERO_MOCK = False
    print("[DEMO] gpiozero not installed — using dummy classes")

    class OutputDevice:
        def __init__(self, pin):
            self.pin   = pin
            self._state = False
        def on(self):
            if not self._state:
                print(f"  GPIO {self.pin} → HIGH (GOOD)")
            self._state = True
        def off(self):
            if self._state:
                print(f"  GPIO {self.pin} → LOW  (BAD)")
            self._state = False
        def close(self): pass

    class DigitalInputDevice:
        def __init__(self, pin, pull_up=True): self.is_active = False
        def close(self): pass

    output_pins  = [OutputDevice(pin) for pin in OUTPUT_PIN_NUMBERS]
    trigger      = DigitalInputDevice(TRIGGER_PIN, pull_up=False)
    mock_trigger = None

trigger_last_state  = False
simulated_high      = False   # True for one frame when SPACE is pressed


def simulate_ur5_trigger():
    # Drive the mock trigger pin HIGH for one frame to simulate the UR5 pulse
    global simulated_high
    simulated_high = True
    if USE_GPIOZERO_MOCK:
        mock_trigger.drive_high()
    else:
        trigger.is_active = True
    print("[DEMO] UR5 trigger pulse sent (3.3V)")


def release_ur5_trigger():
    global simulated_high
    simulated_high = False
    if USE_GPIOZERO_MOCK:
        mock_trigger.drive_low()
    else:
        trigger.is_active = False


def update_gpio_outputs(results):
    print("[DEMO] GPIO outputs updated:")
    for device, res in zip(output_pins, results):
        device.on() if res == "GOOD" else device.off()


# --- Camera ---
def open_camera(index):
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return cap

camera_index = 0
cap = open_camera(camera_index)

rois    = []
drawing = False
ix, iy  = -1, -1


def classify_color(roi_img):
    hsv  = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (100, 100,  50), (130, 255, 255))
    red1 = cv2.inRange(hsv, (  0, 100,  50), ( 10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 100,  50), (180, 255, 255))
    red  = red1 | red2
    return "GOOD" if cv2.countNonZero(blue) > cv2.countNonZero(red) else "BAD"


def save_results(results):
    global last_saved_results, freeze_until

    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "results":   results,
    }

    try:
        with open(RESULTS_FILE) as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing.append(data)

    with open(RESULTS_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    last_saved_results = results.copy()
    update_gpio_outputs(results)
    freeze_until = time.time() + 1
    print(f"[DEMO] Results saved: {results}")


def draw_rois(display_frame, original_frame):
    results = []
    scale_x = (DISPLAY_WIDTH - PANEL_WIDTH) / original_frame.shape[1]
    scale_y = DISPLAY_HEIGHT / original_frame.shape[0]

    for i, (x, y, w, h) in enumerate(rois):
        roi = original_frame[y:y+h, x:x+w]
        if roi.size == 0:
            continue

        result = classify_color(roi)
        results.append(result)

        dx = int(x * scale_x)
        dy = int(y * scale_y)
        dw = int(w * scale_x)
        dh = int(h * scale_y)

        color = (255, 0, 0) if result == "GOOD" else (0, 0, 255)
        cv2.rectangle(display_frame, (dx, dy), (dx+dw, dy+dh), color, 2)
        cv2.putText(display_frame, f"{i}:{result}", (dx, dy-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    return results


def draw_status_panel(frame, results):
    h     = frame.shape[0]
    panel = np.zeros((h, PANEL_WIDTH, 3), dtype=np.uint8)

    # Demo label at the top of the panel
    cv2.putText(panel, "-- DEMO --", (10, 20), 0, 0.5, (0, 200, 255), 1)

    cv2.putText(panel, "CURRENT", (10,  45), 0, 0.7, (255, 255, 255), 2)
    for i, r in enumerate(results):
        c = (255, 0, 0) if r == "GOOD" else (0, 0, 255)
        cv2.putText(panel, f"{i}:{r}", (10, 75 + i*25), 0, 0.6, c, 2)

    cv2.putText(panel, "SAVED", (10, 280), 0, 0.7, (255, 255, 255), 2)
    if last_saved_results:
        for i, r in enumerate(last_saved_results):
            c = (255, 0, 0) if r == "GOOD" else (0, 0, 255)
            cv2.putText(panel, f"{i}:{r}", (10, 310 + i*25), 0, 0.6, c, 2)

    # Hint at the bottom of the panel
    cv2.putText(panel, "SPACE=UR5 trigger", (5, h-10), 0, 0.4, (150, 150, 150), 1)

    return np.hstack((frame, panel))


def draw_pass_fail(frame, results):
    if len(results) != 8:
        return frame
    good  = all(r == "GOOD" for r in results)
    label = "PASS" if good else "FAIL"
    color = (0, 255, 0) if good else (0, 0, 255)
    cv2.putText(frame, label, (20, 60), 0, 2, color, 4)
    return frame


def draw_exit_button(frame):
    x, y, w, h = EXIT_BTN
    cv2.rectangle(frame, (x, y), (x+w, y+h), (50, 50, 50), -1)
    cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 255, 255), 2)
    cv2.putText(frame, "EXIT", (x+20, y+30), 0, 0.7, (255, 255, 255), 2)


def mouse_callback(event, x, y, flags, param):
    global ix, iy, drawing, rois, exit_requested

    # Scale from display coords back to original frame coords
    scale_x = cap.get(cv2.CAP_PROP_FRAME_WIDTH)  / (DISPLAY_WIDTH - PANEL_WIDTH)
    scale_y = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) / DISPLAY_HEIGHT

    if event == cv2.EVENT_LBUTTONDOWN:
        bx, by, bw, bh = EXIT_BTN
        if bx <= x <= bx+bw and by <= y <= by+bh:
            exit_requested = True
            return
        drawing = True
        ix = int(x * scale_x)
        iy = int(y * scale_y)

    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        x2 = int(x * scale_x)
        y2 = int(y * scale_y)
        x_min, x_max = min(ix, x2), max(ix, x2)
        y_min, y_max = min(iy, y2), max(iy, y2)
        if x_max - x_min > 10 and y_max - y_min > 10 and len(rois) < 8:
            rois.append((x_min, y_min, x_max - x_min, y_max - y_min))


def save_rois():
    with open(SAVE_FILE, "w") as f:
        json.dump(rois, f)


def load_rois():
    global rois
    try:
        with open(SAVE_FILE) as f:
            rois = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass


# --- Main loop ---
print("[DEMO] Starting vision system demo")
print("[DEMO] Keys: c=clear ROIs  s=save ROIs  l=load ROIs  w=manual save  SPACE=UR5 trigger  ESC=exit")

cv2.namedWindow("Camera", cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty("Camera", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.setMouseCallback("Camera", mouse_callback)

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display = cv2.resize(frame, (DISPLAY_WIDTH - PANEL_WIDTH, DISPLAY_HEIGHT))

        results = draw_rois(display, frame)
        display = draw_pass_fail(display, results)
        display = draw_status_panel(display, results)
        draw_exit_button(display)

        if time.time() < freeze_until:
            cv2.putText(display, "SAVED", (200, 100), 0, 2, (0, 255, 255), 4)

        cv2.imshow("Camera", display)

        key = cv2.waitKey(1) & 0xFF

        if key == 27 or exit_requested:
            break
        elif key == ord('c'):
            rois = []
        elif key == ord('s'):
            save_rois()
        elif key == ord('l'):
            load_rois()
        elif key == ord('w') and len(results) == 8:
            save_results(results)
        elif key == ord('n'):
            cap.release()
            camera_index += 1
            cap = open_camera(camera_index)
            if not cap.isOpened():
                camera_index -= 1
                cap = open_camera(camera_index)
        elif key == ord('p'):
            cap.release()
            camera_index = max(0, camera_index - 1)
            cap = open_camera(camera_index)
        elif key == ord(' '):
            # Simulate UR5 sending a 3.3V pulse to GPIO 4
            simulate_ur5_trigger()

        # UR5 trigger — rising edge detection (same logic as production)
        trigger_state = trigger.is_active if USE_GPIOZERO_MOCK else trigger.is_active
        if trigger_state and not trigger_last_state and len(results) == 8:
            save_results(results)
        trigger_last_state = trigger_state

        # Release the simulated trigger after one frame so it acts as a pulse
        if simulated_high:
            release_ur5_trigger()

finally:
    cap.release()
    cv2.destroyAllWindows()
    for pin in output_pins:
        pin.close()
    trigger.close()
    print("[DEMO] Closed cleanly")
