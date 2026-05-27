import cv2
import numpy as np
import json
import datetime
import time

DISPLAY_WIDTH  = 1024
DISPLAY_HEIGHT = 600
PANEL_WIDTH    = 300
EXIT_BTN       = (20, 20, 120, 50)
RESULTS_FILE   = "results_log.json"
SAVE_FILE      = "rois.json"

exit_requested     = False
last_saved_results = None
freeze_until       = 0

# GPIO — 8 outputs (one per ROI) + 1 input from UR5 via level shifter
OUTPUT_PIN_NUMBERS = [17, 18, 27, 22, 23, 24, 25, 5]
TRIGGER_PIN        = 4

try:
    from gpiozero import OutputDevice, DigitalInputDevice
except ImportError:
    class OutputDevice:
        def __init__(self, pin): pass
        def on(self): pass
        def off(self): pass
        def close(self): pass
    class DigitalInputDevice:
        def __init__(self, pin, pull_up=True): self.is_active = False
        def close(self): pass

output_pins        = [OutputDevice(pin) for pin in OUTPUT_PIN_NUMBERS]
trigger            = DigitalInputDevice(TRIGGER_PIN, pull_up=False)  # active-high
trigger_last_state = False

rois    = []
drawing = False
ix, iy  = -1, -1

camera_index = 0


def update_gpio_outputs(results):
    for device, res in zip(output_pins, results):
        device.on() if res == "GOOD" else device.off()


def open_camera(index):
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return cap


def classify_color(roi_img):
    hsv  = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (100, 100, 50), (130, 255, 255))
    red1 = cv2.inRange(hsv, (  0, 100, 50), ( 10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 100, 50), (180, 255, 255))
    red  = red1 | red2  # red wraps around 0° in HSV, needs two ranges
    return "GOOD" if cv2.countNonZero(blue) > cv2.countNonZero(red) else "BAD"


def save_results(results):
    global last_saved_results, freeze_until
    data = {"timestamp": datetime.datetime.now().isoformat(), "results": results}
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


def draw_rois(display_frame, original_frame):
    results = []
    sx = (DISPLAY_WIDTH - PANEL_WIDTH) / 1920
    sy = DISPLAY_HEIGHT / 1080
    for i, (x, y, w, h) in enumerate(rois):
        roi = original_frame[y:y+h, x:x+w]
        if roi.size == 0:
            continue
        result = classify_color(roi)
        results.append(result)
        color = (255, 0, 0) if result == "GOOD" else (0, 0, 255)
        dx, dy, dw, dh = int(x*sx), int(y*sy), int(w*sx), int(h*sy)
        cv2.rectangle(display_frame, (dx, dy), (dx+dw, dy+dh), color, 2)
        cv2.putText(display_frame, f"{i}:{result}", (dx, dy-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return results


def draw_status_panel(frame, results):
    panel = np.zeros((frame.shape[0], PANEL_WIDTH, 3), dtype=np.uint8)
    cv2.putText(panel, "CURRENT", (10,  30), 0, 0.7, (255, 255, 255), 2)
    for i, r in enumerate(results):
        c = (255, 0, 0) if r == "GOOD" else (0, 0, 255)
        cv2.putText(panel, f"{i}:{r}", (10, 60 + i*25), 0, 0.6, c, 2)
    cv2.putText(panel, "SAVED", (10, 270), 0, 0.7, (255, 255, 255), 2)
    if last_saved_results:
        for i, r in enumerate(last_saved_results):
            c = (255, 0, 0) if r == "GOOD" else (0, 0, 255)
            cv2.putText(panel, f"{i}:{r}", (10, 300 + i*25), 0, 0.6, c, 2)
    return np.hstack((frame, panel))


def draw_pass_fail(frame, results):
    if len(results) != 8:
        return frame
    good = all(r == "GOOD" for r in results)
    cv2.putText(frame, "PASS" if good else "FAIL", (20, 60), 0, 2,
                (0, 255, 0) if good else (0, 0, 255), 4)
    return frame


def draw_exit_button(frame):
    x, y, w, h = EXIT_BTN
    cv2.rectangle(frame, (x, y), (x+w, y+h), (50, 50, 50), -1)
    cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 255, 255), 2)
    cv2.putText(frame, "EXIT", (x+20, y+30), 0, 0.7, (255, 255, 255), 2)


def mouse_callback(event, x, y, flags, param):
    global ix, iy, drawing, rois, exit_requested
    sx = 1920 / (DISPLAY_WIDTH - PANEL_WIDTH)
    sy = 1080 / DISPLAY_HEIGHT
    if event == cv2.EVENT_LBUTTONDOWN:
        bx, by, bw, bh = EXIT_BTN
        if bx <= x <= bx+bw and by <= y <= by+bh:
            exit_requested = True
            return
        drawing, ix, iy = True, int(x*sx), int(y*sy)
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        x2, y2 = int(x*sx), int(y*sy)
        x_min, x_max = min(ix, x2), max(ix, x2)
        y_min, y_max = min(iy, y2), max(iy, y2)
        if x_max-x_min > 10 and y_max-y_min > 10 and len(rois) < 8:
            rois.append((x_min, y_min, x_max-x_min, y_max-y_min))


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


cap = open_camera(camera_index)
cv2.namedWindow("Camera", cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty("Camera", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.setMouseCallback("Camera", mouse_callback)

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display = cv2.resize(frame, (DISPLAY_WIDTH - PANEL_WIDTH, DISPLAY_HEIGHT))
        results = draw_rois(display, frame)  # detection runs on full-res frame
        display = draw_pass_fail(display, results)
        display = draw_status_panel(display, results)
        draw_exit_button(display)

        if time.time() < freeze_until:
            cv2.putText(display, "SAVED", (200, 100), 0, 2, (0, 255, 255), 4)

        cv2.imshow("Camera", display)
        key = cv2.waitKey(1) & 0xFF

        if key == 27 or exit_requested:
            break
        elif key == ord('c'): rois = []
        elif key == ord('s'): save_rois()
        elif key == ord('l'): load_rois()
        elif key == ord('w') and len(results) == 8: save_results(results)
        elif key == ord('n'):
            cap.release(); camera_index += 1; cap = open_camera(camera_index)
            if not cap.isOpened(): camera_index -= 1; cap = open_camera(camera_index)
        elif key == ord('p'):
            cap.release(); camera_index = max(0, camera_index-1); cap = open_camera(camera_index)

        # UR5 trigger — save once on rising edge (LOW → 3.3V)
        trigger_state = trigger.is_active
        if trigger_state and not trigger_last_state and len(results) == 8:
            save_results(results)
        trigger_last_state = trigger_state

finally:
    cap.release()
    cv2.destroyAllWindows()
    for pin in output_pins: pin.close()
    trigger.close()
