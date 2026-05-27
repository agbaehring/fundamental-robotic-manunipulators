"""
vision_system_documented.py
============================
Colour-based vision inspection system for a UR5 collaborative robot.

Hardware overview
-----------------
- Raspberry Pi (any model with 40-pin GPIO header)
- USB or CSI camera capable of 1920x1080
- UR5 robot controller with digital I/O
- Level shifter module (24V UR5 output → 3.3V RPi input)

How it works
------------
1. The camera captures a full 1920x1080 frame every loop iteration.
2. The operator draws up to 8 Regions of Interest (ROIs) on the live feed
   by clicking and dragging with the mouse.
3. Each ROI is cropped from the full-resolution frame and analysed in HSV
   colour space. A region is GOOD if it contains more blue pixels than red,
   BAD otherwise.
4. When the UR5 finishes positioning a part, it raises a digital output.
   That signal passes through a level shifter and arrives at RPi GPIO 4 as
   3.3 V. The rising edge triggers save_results(), which:
     a. Appends the timestamped results to results_log.json
     b. Drives 8 output GPIO pins HIGH/LOW to reflect each ROI result
5. The UR5 reads those 8 pins and decides what to do with the part.

Keyboard shortcuts
------------------
  c  — clear all ROIs from memory (does not delete the saved file)
  s  — save current ROI positions to rois.json
  l  — load ROI positions from rois.json
  w  — manually trigger a save (same as UR5 trigger, requires 8 ROIs)
  n  — switch to the next camera index
  p  — switch to the previous camera index
  ESC / EXIT button — quit the program cleanly

File outputs
------------
  results_log.json — append-only list of every saved scan with timestamp
  rois.json        — last saved ROI layout (reloaded with 'l')

GPIO pin mapping
----------------
  Output pins : BCM 17, 18, 27, 22, 23, 24, 25, 5  (ROI 0–7)
  Input pin   : BCM 4  (UR5 trigger via level shifter)
  HIGH = GOOD, LOW = BAD

Dependencies
------------
  pip install opencv-python numpy gpiozero
"""

import cv2
import numpy as np
import json
import datetime
import time

# ---------------------------------------------------------------------------
# Display configuration
# ---------------------------------------------------------------------------
# The OpenCV window runs fullscreen at 1024x600 (suited to a 7" RPi display).
# The right-hand 300px column is reserved for the status panel, leaving
# 724x600 for the camera feed.
DISPLAY_WIDTH  = 1024
DISPLAY_HEIGHT = 600
PANEL_WIDTH    = 300   # width of the right-hand status panel in pixels

# Exit button geometry: (x, y, width, height) in display pixel coordinates
EXIT_BTN = (20, 20, 120, 50)

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
RESULTS_FILE = "results_log.json"  # every save() call appends an entry here
SAVE_FILE    = "rois.json"         # ROI positions persist between runs here

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------
exit_requested     = False  # set True by mouse_callback when EXIT is clicked
last_saved_results = None   # the result list from the most recent save
freeze_until       = 0      # epoch time until the "SAVED" flash overlay shows

# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------
# Output pins drive the UR5 digital inputs. One pin per ROI (max 8).
# HIGH = GOOD (blue detected), LOW = BAD (red detected or no blue).
OUTPUT_PIN_NUMBERS = [17, 18, 27, 22, 23, 24, 25, 5]

# The UR5 digital output is 24 V. A level shifter converts it to 3.3 V
# before it reaches this input pin. pull_up=False configures an internal
# pull-down resistor so the idle (unconnected) state reads LOW.
TRIGGER_PIN = 4

try:
    from gpiozero import OutputDevice, DigitalInputDevice
    # gpiozero is available — real hardware will be used on the RPi.
    # On a non-Pi machine gpiozero raises RuntimeError on pin creation;
    # use vision_system_demo.py with MockFactory for off-Pi testing.
except ImportError:
    # gpiozero is not installed. Provide no-op stubs so the rest of the
    # code runs without modification (useful for syntax checking on Windows).
    class OutputDevice:
        """Stub that silently ignores all GPIO calls."""
        def __init__(self, pin): pass
        def on(self): pass
        def off(self): pass
        def close(self): pass

    class DigitalInputDevice:
        """Stub that always reports the pin as inactive."""
        def __init__(self, pin, pull_up=True): self.is_active = False
        def close(self): pass

# One OutputDevice object per output pin. gpiozero sets all outputs LOW at
# construction, so no explicit initialisation loop is needed.
output_pins = [OutputDevice(pin) for pin in OUTPUT_PIN_NUMBERS]

# DigitalInputDevice with pull_up=False:
#   - internal pull-down resistor keeps the pin LOW when nothing is connected
#   - is_active becomes True when 3.3 V is applied (active-high logic)
trigger            = DigitalInputDevice(TRIGGER_PIN, pull_up=False)
trigger_last_state = False  # previous frame's pin state, used for edge detection

# ---------------------------------------------------------------------------
# ROI state
# ---------------------------------------------------------------------------
# Each entry in rois is a tuple (x, y, w, h) in *original* 1920x1080 pixel
# coordinates. Storing in full resolution keeps detection independent of the
# display scale factor.
rois    = []
drawing = False   # True while the user holds the left mouse button
ix, iy  = -1, -1  # coordinates where the current drag started (original space)

camera_index = 0  # index passed to cv2.VideoCapture; incremented by 'n'/'p'


# ---------------------------------------------------------------------------
# GPIO helpers
# ---------------------------------------------------------------------------

def update_gpio_outputs(results):
    """
    Drive each output pin to reflect the corresponding ROI result.

    Parameters
    ----------
    results : list of str
        List of "GOOD" or "BAD" strings, one per ROI (up to 8).
        Index 0 → OUTPUT_PIN_NUMBERS[0], etc.
    """
    for device, res in zip(output_pins, results):
        device.on() if res == "GOOD" else device.off()


# ---------------------------------------------------------------------------
# Camera helpers
# ---------------------------------------------------------------------------

def open_camera(index):
    """
    Open a VideoCapture at the given device index and request 1920x1080.

    The resolution request is advisory — the camera may deliver a different
    resolution if it does not support 1080p. Detection scaling is based on
    the actual frame size, so this does not cause incorrect ROI placement.

    Parameters
    ----------
    index : int
        OS camera index (0 = first device, 1 = second, etc.)

    Returns
    -------
    cv2.VideoCapture
    """
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return cap


# ---------------------------------------------------------------------------
# Colour classification
# ---------------------------------------------------------------------------

def classify_color(roi_img):
    """
    Classify a BGR image crop as "GOOD" (blue dominant) or "BAD" (red dominant).

    The function converts the crop to HSV colour space, which separates
    chrominance from luminance and makes colour thresholds more robust to
    changes in lighting intensity.

    Red spans two separate hue ranges in HSV (around 0° and 180°) because
    the hue wheel wraps at 180. Both ranges are combined with a bitwise OR
    before counting pixels.

    HSV ranges used
    ---------------
    Blue : hue 100–130°, saturation 100–255, value 50–255
    Red  : hue 0–10° and 170–180°, saturation 100–255, value 50–255

    Parameters
    ----------
    roi_img : numpy.ndarray
        BGR image crop to classify.

    Returns
    -------
    str
        "GOOD" if blue pixel count exceeds red, "BAD" otherwise.
    """
    hsv  = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (100, 100, 50), (130, 255, 255))
    red1 = cv2.inRange(hsv, (  0, 100, 50), ( 10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 100, 50), (180, 255, 255))
    red  = red1 | red2  # combine both red hue ranges
    return "GOOD" if cv2.countNonZero(blue) > cv2.countNonZero(red) else "BAD"


# ---------------------------------------------------------------------------
# Results persistence
# ---------------------------------------------------------------------------

def save_results(results):
    """
    Persist the current scan results, update GPIO outputs, and trigger the
    on-screen "SAVED" confirmation overlay.

    The results are appended (not overwritten) to RESULTS_FILE so that a
    full history of every scan is available for later analysis.

    Side effects
    ------------
    - Writes to RESULTS_FILE (creates the file if it does not exist).
    - Calls update_gpio_outputs() to immediately reflect results on hardware.
    - Sets freeze_until so the "SAVED" text appears for ~1 second.
    - Updates the global last_saved_results shown in the status panel.

    Parameters
    ----------
    results : list of str
        Exactly 8 "GOOD"/"BAD" strings, one per ROI.
    """
    global last_saved_results, freeze_until

    data = {"timestamp": datetime.datetime.now().isoformat(), "results": results}

    try:
        with open(RESULTS_FILE) as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []  # first run or corrupted file — start a fresh log

    existing.append(data)

    with open(RESULTS_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    last_saved_results = results.copy()
    update_gpio_outputs(results)
    freeze_until = time.time() + 1


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def draw_rois(display_frame, original_frame):
    """
    Classify each ROI and draw labelled rectangles on the display frame.

    Detection is intentionally performed on the full-resolution original_frame
    rather than the downscaled display_frame. Downscaling before detection
    would reduce the number of colour pixels available, making thresholds
    less reliable — especially for small ROIs.

    The rectangle coordinates are scaled down to match the display frame size
    only for drawing purposes.

    Parameters
    ----------
    display_frame : numpy.ndarray
        Resized (724x600) frame that will be shown on screen. Modified in place.
    original_frame : numpy.ndarray
        Full-resolution frame used for colour detection.

    Returns
    -------
    list of str
        "GOOD" or "BAD" for each ROI in rois order.
    """
    results = []
    sx = (DISPLAY_WIDTH - PANEL_WIDTH) / 1920
    sy = DISPLAY_HEIGHT / 1080

    for i, (x, y, w, h) in enumerate(rois):
        roi = original_frame[y:y+h, x:x+w]
        if roi.size == 0:
            continue

        result = classify_color(roi)
        results.append(result)

        color = (255, 0, 0) if result == "GOOD" else (0, 0, 255)  # blue / red
        dx, dy, dw, dh = int(x*sx), int(y*sy), int(w*sx), int(h*sy)
        cv2.rectangle(display_frame, (dx, dy), (dx+dw, dy+dh), color, 2)
        cv2.putText(display_frame, f"{i}:{result}", (dx, dy-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    return results


def draw_status_panel(frame, results):
    """
    Build and attach the right-hand status panel to the camera frame.

    The panel has two sections:
    - CURRENT: live classification results updated every frame.
    - SAVED:   the results from the most recent save_results() call.
      These persist on screen until the next save, giving the operator and
      the UR5 a stable reference even as the live feed changes.

    Parameters
    ----------
    frame : numpy.ndarray
        The 724x600 display frame (camera feed with ROI overlays).
    results : list of str
        Current live results to show in the CURRENT section.

    Returns
    -------
    numpy.ndarray
        1024x600 composite frame (camera feed + panel side by side).
    """
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
    """
    Overlay a large PASS or FAIL label on the frame.

    Only shown when exactly 8 ROIs have been evaluated. PASS requires all
    8 results to be GOOD; a single BAD result produces FAIL.

    Parameters
    ----------
    frame : numpy.ndarray
        Display frame to draw on (modified in place and returned).
    results : list of str
        Current classification results.

    Returns
    -------
    numpy.ndarray
        The same frame, with the label added if applicable.
    """
    if len(results) != 8:
        return frame
    good = all(r == "GOOD" for r in results)
    cv2.putText(frame, "PASS" if good else "FAIL", (20, 60), 0, 2,
                (0, 255, 0) if good else (0, 0, 255), 4)
    return frame


def draw_exit_button(frame):
    """Draw a clickable EXIT button in the top-left corner of the frame."""
    x, y, w, h = EXIT_BTN
    cv2.rectangle(frame, (x, y), (x+w, y+h), (50, 50, 50), -1)
    cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 255, 255), 2)
    cv2.putText(frame, "EXIT", (x+20, y+30), 0, 0.7, (255, 255, 255), 2)


# ---------------------------------------------------------------------------
# Mouse interaction
# ---------------------------------------------------------------------------

def mouse_callback(event, x, y, flags, param):
    """
    Handle mouse events for ROI drawing and exit button clicks.

    All mouse coordinates from OpenCV are in display-frame pixels (724x600).
    They are scaled back to original-frame pixels (1920x1080) before being
    stored in rois, so that ROI positions are display-resolution independent.

    ROI drawing workflow
    --------------------
    1. User presses left button → record start position (ix, iy).
    2. User releases left button → compute bounding box, validate size,
       append to rois if fewer than 8 ROIs exist.

    Minimum ROI size of 10x10 pixels (in original resolution) prevents
    accidental single-click registrations.

    Parameters
    ----------
    event : int
        OpenCV mouse event constant.
    x, y : int
        Cursor position in display-frame pixels.
    flags, param : ignored
    """
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


# ---------------------------------------------------------------------------
# ROI file I/O
# ---------------------------------------------------------------------------

def save_rois():
    """Write the current ROI list to SAVE_FILE as JSON."""
    with open(SAVE_FILE, "w") as f:
        json.dump(rois, f)


def load_rois():
    """
    Replace the current ROI list with positions loaded from SAVE_FILE.

    Silently does nothing if the file does not exist or contains invalid JSON,
    leaving the existing rois list unchanged.
    """
    global rois
    try:
        with open(SAVE_FILE) as f:
            rois = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

cap = open_camera(camera_index)
cv2.namedWindow("Camera", cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty("Camera", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
cv2.setMouseCallback("Camera", mouse_callback)

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Resize only for display — full-res frame is passed to draw_rois
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
        elif key == ord('c'): rois = []
        elif key == ord('s'): save_rois()
        elif key == ord('l'): load_rois()
        elif key == ord('w') and len(results) == 8: save_results(results)
        elif key == ord('n'):
            cap.release(); camera_index += 1; cap = open_camera(camera_index)
            if not cap.isOpened(): camera_index -= 1; cap = open_camera(camera_index)
        elif key == ord('p'):
            cap.release(); camera_index = max(0, camera_index-1); cap = open_camera(camera_index)

        # UR5 trigger: save once on rising edge (LOW → 3.3 V).
        # trigger_last_state ensures only one save per pulse, regardless of
        # how many frames the signal stays HIGH.
        trigger_state = trigger.is_active
        if trigger_state and not trigger_last_state and len(results) == 8:
            save_results(results)
        trigger_last_state = trigger_state

finally:
    # Runs on clean exit, ESC, or any unhandled exception.
    cap.release()
    cv2.destroyAllWindows()
    for pin in output_pins: pin.close()
    trigger.close()
