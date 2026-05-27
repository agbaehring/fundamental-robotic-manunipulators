# UR5 Vision Inspection System

A colour-based vision inspection system running on a Raspberry Pi, designed to work alongside a UR5 collaborative robot. The camera analyses up to 8 regions of interest (ROIs) on a part and classifies each one as GOOD (blue) or BAD (red). Results are sent back to the UR5 via GPIO digital outputs.

---

## Hardware Requirements

| Component | Details |
|---|---|
| Raspberry Pi | Any model with a 40-pin GPIO header |
| Camera | USB or CSI, capable of 1920x1080 |
| Display | 7" touchscreen or monitor (1024x600 recommended) |
| Level shifter | Converts UR5 24V digital output → 3.3V RPi input |
| UR5 robot | CB3 or e-Series with digital I/O |

### Wiring

```
UR5 Digital Output (24V) → Level Shifter → RPi GPIO 4 (trigger input)

RPi GPIO 17 → UR5 Digital Input 0  (ROI 0 result)
RPi GPIO 18 → UR5 Digital Input 1  (ROI 1 result)
RPi GPIO 27 → UR5 Digital Input 2  (ROI 2 result)
RPi GPIO 22 → UR5 Digital Input 3  (ROI 3 result)
RPi GPIO 23 → UR5 Digital Input 4  (ROI 4 result)
RPi GPIO 24 → UR5 Digital Input 5  (ROI 5 result)
RPi GPIO  6 → UR5 Digital Input 6  (ROI 6 result)
RPi GPIO  5 → UR5 Digital Input 7  (ROI 7 result)
```

---

## Installation

```bash
pip install opencv-python numpy gpiozero
```

---

## Files

### `vision_system.py` — Production file

This is the file that runs on the Raspberry Pi in normal operation. It is kept as short and clean as possible so it is easy to deploy and modify.

**When to use:** Deploy this on the RPi connected to the UR5.

**How to run:**
```bash
python vision_system.py
```

**What it does:**
1. Opens the camera at 1920x1080
2. Displays a live feed in a fullscreen window (1024x600)
3. Lets the operator draw up to 8 ROIs by clicking and dragging
4. Classifies each ROI every frame as GOOD (blue) or BAD (red)
5. When the UR5 sends a 3.3V pulse to GPIO 4, it saves the current results:
   - Appends a timestamped entry to `results_log.json`
   - Sets the 8 output GPIO pins HIGH (GOOD) or LOW (BAD)
6. The UR5 reads those pins to decide what to do with the part

**Keyboard shortcuts:**

| Key | Action |
|---|---|
| `c` | Clear all ROIs |
| `s` | Save ROI positions to `rois.json` |
| `l` | Load ROI positions from `rois.json` |
| `w` | Manually trigger a save (requires 8 ROIs) |
| `n` | Switch to next camera |
| `p` | Switch to previous camera |
| `ESC` | Exit |

**Output files:**

| File | Description |
|---|---|
| `results_log.json` | Append-only log of every saved scan with timestamp |
| `rois.json` | Saved ROI positions, reloaded with `l` |

---

### `vision_system_demo.py` — Demo / development file

A version of the production file that runs on any Windows or Mac PC without a Raspberry Pi or any GPIO hardware. GPIO is fully simulated using gpiozero's MockFactory (or no-op dummy classes if gpiozero is not installed). The UR5 trigger is simulated by pressing the spacebar.

**When to use:**
- Testing the vision logic on a development PC before deploying to the RPi
- Demonstrating the system without the robot present
- Verifying camera and ROI behaviour without needing GPIO hardware

**How to run:**
```bash
python vision_system_demo.py
```

**What is different from the production file:**
- GPIO is mocked — no real pins are used
- Press **SPACE** to simulate the UR5 sending a 3.3V trigger pulse
- GPIO output state changes are printed to the terminal so you can see what the real hardware would do
- A `-- DEMO --` label and `SPACE=UR5 trigger` hint are shown in the status panel

**Terminal output example:**
```
[DEMO] Starting vision system demo
[DEMO] UR5 trigger pulse sent (3.3V)
[DEMO] GPIO outputs updated:
  GPIO 17 → HIGH (GOOD)
  GPIO 18 → LOW  (BAD)
  ...
[DEMO] Results saved: ['GOOD', 'BAD', 'GOOD', 'GOOD', 'GOOD', 'GOOD', 'GOOD', 'GOOD']
```

---

### `vision_system_documented.py` — Reference / documentation file

An identical copy of the production file with full docstrings and in-depth comments on every function, constant, and non-obvious decision. Intended as a reference for understanding how and why the system works.

**When to use:**
- Learning how the system works
- Onboarding a new team member
- Understanding why a specific design decision was made before changing it
- As a starting point if you need to extend the system

**What is documented:**
- Module-level docstring covering the full hardware overview, data flow, GPIO pin map, keyboard shortcuts, and file outputs
- Every function has a docstring explaining its purpose, parameters, return values, and any non-obvious behaviour
- Inline comments explain things like why red requires two HSV ranges, why detection runs on the full-resolution frame instead of the display frame, and how the rising edge detection prevents multiple saves per pulse

**This file is not intended to be deployed.** Use `vision_system.py` on the RPi. This file exists purely as documentation.

---

## How the trigger flow works

```
UR5 finishes positioning part
        │
        ▼
UR5 raises digital output (24V)
        │
        ▼
Level shifter converts to 3.3V
        │
        ▼
RPi GPIO 4 goes HIGH (rising edge detected)
        │
        ▼
save_results() called once
        │
        ├── Appends to results_log.json
        ├── Updates 8 output GPIO pins (HIGH=GOOD / LOW=BAD)
        └── Shows "SAVED" overlay on screen for 1 second
                │
                ▼
        UR5 reads the 8 GPIO input pins
        and decides what to do with the part
```

---

## Colour thresholds

Detection uses HSV colour space. Thresholds can be adjusted in `classify_color()` in any of the three files.

| Colour | Hue | Saturation | Value |
|---|---|---|---|
| Blue (GOOD) | 100–130° | 100–255 | 50–255 |
| Red (BAD) | 0–10° and 170–180° | 100–255 | 50–255 |

> Red requires two ranges because it wraps around 0° on the HSV hue wheel.
