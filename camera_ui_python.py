import cv2
import numpy as np
import json
import datetime
import time

RESULTS_FILE = "results_log.json"
SAVE_FILE = "rois.json"

last_saved_results = None
freeze_until = 0

# pin out setup for 8 outputs (GPIO 17, 18, 27, 22, 23, 24, 25, 5)
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    REAL_GPIO = True
    print("Running on Raspberry Pi (real GPIO)")
except ImportError:
    REAL_GPIO = False
    print("Running on Windows (GPIO emulated)")

    class FakeGPIO:
        BCM = "BCM"
        OUT = "OUT"
        HIGH = 1
        LOW = 0

        def setmode(self, mode):
            pass

        def setup(self, pin, mode):
            print(f"[GPIO SETUP] Pin {pin}")

        def output(self, pin, value):
            state = "HIGH" if value else "LOW"
            print(f"[GPIO OUTPUT] Pin {pin} -> {state}")

        def cleanup(self):
            print("[GPIO CLEANUP]")

    GPIO = FakeGPIO()

GPIO_PINS = [17, 18, 27, 22, 23, 24, 25, 5]

for pin in GPIO_PINS:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

#function to update GPIO outputs based on results
def update_gpio_outputs(results):
    for i, res in enumerate(results):
        if i >= len(GPIO_PINS):
            break

        if res == "GOOD":
            GPIO.output(GPIO_PINS[i], GPIO.HIGH)
        else:
            GPIO.output(GPIO_PINS[i], GPIO.LOW)

# --- Camera setup ---
def open_camera(index):
    cap = cv2.VideoCapture(index)
    return cap

camera_index = 0
cap = open_camera(camera_index)

# --- ROI ---
rois = []
drawing = False
ix, iy = -1, -1

def classify_color(roi_img):
    hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)

    blue_mask = cv2.inRange(hsv, (100, 100, 50), (130, 255, 255))

    red_mask1 = cv2.inRange(hsv, (0, 100, 50), (10, 255, 255))
    red_mask2 = cv2.inRange(hsv, (170, 100, 50), (180, 255, 255))
    red_mask = red_mask1 + red_mask2

    blue_pixels = cv2.countNonZero(blue_mask)
    red_pixels = cv2.countNonZero(red_mask)

    return "GOOD" if blue_pixels > red_pixels else "BAD"

def save_results(results):
    global last_saved_results, freeze_until

    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "results": results
    }

    try:
        with open(RESULTS_FILE, "r") as f:
            existing = json.load(f)
    except:
        existing = []

    existing.append(data)

    with open(RESULTS_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    last_saved_results = results.copy()

    update_gpio_outputs(results)  # 🔥 THIS LINE

    freeze_until = time.time() + 1.0

def draw_rois(frame):
    results = []
    for i, (x, y, w, h) in enumerate(rois):
        roi = frame[y:y+h, x:x+w]
        if roi.size == 0:
            continue

        result = classify_color(roi)
        results.append(result)

        color = (255, 0, 0) if result == "GOOD" else (0, 0, 255)

        cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
        cv2.putText(frame, f"{i}:{result}", (x, y-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    return results

def draw_status_panel(frame, current_results):
    h, w, _ = frame.shape
    panel = np.zeros((h, 300, 3), dtype=np.uint8)

    # CURRENT
    cv2.putText(panel, "CURRENT", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    for i, res in enumerate(current_results):
        color = (255, 0, 0) if res == "GOOD" else (0, 0, 255)
        cv2.putText(panel, f"{i}: {res}", (10, 60 + i*25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # SAVED
    cv2.putText(panel, "SAVED", (10, 270),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    if last_saved_results:
        for i, res in enumerate(last_saved_results):
            color = (255, 0, 0) if res == "GOOD" else (0, 0, 255)
            cv2.putText(panel, f"{i}: {res}", (10, 300 + i*25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    else:
        cv2.putText(panel, "None", (10, 330),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)

    return np.hstack((frame, panel))

def draw_pass_fail(frame, results):
    if len(results) != 8:
        return frame

    all_good = all(r == "GOOD" for r in results)

    text = "PASS" if all_good else "FAIL"
    color = (0, 255, 0) if all_good else (0, 0, 255)

    cv2.putText(frame, text, (20, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 2, color, 4)

    return frame

def mouse_callback(event, x, y, flags, param):
    global ix, iy, drawing, rois

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        ix, iy = x, y

    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False

        x1, y1 = ix, iy
        x2, y2 = x, y

        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)

        w = x_max - x_min
        h = y_max - y_min

        if w < 10 or h < 10:
            return

        if len(rois) < 8:
            rois.append((x_min, y_min, w, h))

def save_rois():
    with open(SAVE_FILE, "w") as f:
        json.dump(rois, f)

def load_rois():
    global rois
    try:
        with open(SAVE_FILE, "r") as f:
            rois = json.load(f)
    except:
        pass

cv2.namedWindow("Camera")
cv2.setMouseCallback("Camera", mouse_callback)

# --- Main loop ---
while True:
    ret, frame = cap.read()
    if not ret:
        break

    display = frame.copy()

    results = draw_rois(display)

    display = draw_pass_fail(display, results)
    display = draw_status_panel(display, results)

    # Freeze effect after save
    if time.time() < freeze_until:
        overlay = display.copy()
        cv2.putText(overlay, "SAVED", (200, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (0,255,255), 4)
        display = overlay

    cv2.imshow("Camera", display)

    key = cv2.waitKey(1) & 0xFF

    if key == 27:
        break

    elif key == ord('c'):
        rois = []

    elif key == ord('s'):
        save_rois()

    elif key == ord('l'):
        load_rois()

    elif key == ord('w'):
        if len(results) == 8:
            save_results(results)

    elif key == ord('n'):
        cap.release()
        camera_index += 1
        cap = open_camera(camera_index)

    elif key == ord('p'):
        cap.release()
        camera_index = max(0, camera_index - 1)
        cap = open_camera(camera_index)

cap.release()
cv2.destroyAllWindows()