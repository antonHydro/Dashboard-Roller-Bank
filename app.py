#!/usr/bin/env python3
"""
Flask-based dyno dashboard for RC car:
  • Displays RPM, speed (km/h), torque (Nm), and power (W)
  • Auto-detects Arduino serial port (macOS, Windows, Linux)
  • Implements dynamic zeroing below low-speed threshold
  • Filters out torque/power outliers for stability
"""
import time
import math
import threading
from pathlib import Path
from collections import deque

from flask import Flask, jsonify, render_template
import serial
import serial.tools.list_ports

# ─────────── USER SETTINGS ───────────
SERIAL_BAUD = 9600            # Baud rate for serial communication
ROLLER_DIAMETER_MM = 60.0     # Diameter of the roller in millimeters
STOP_TIMEOUT_S = 1.0          # If no new data for this many seconds, zero all outputs

# PHYSICS CONSTANTS
J = 0.002572                  # Rotor moment of inertia (kg·m²)
WINDOW_S = 5.0                # Time window (s) for angular acceleration calculation

# DYNAMIC ZEROING SETTINGS
ZERO_SPEED_THRESH = 5.0       # Speeds below this (km/h) may be forced to zero
ZERO_DURATION_S = 2.0         # Duration (s) over which speed must stay low to zero
ZERO_VARIATION_THRESH = 0.2   # Allowed speed variation (km/h) to consider it "constant"

# SERIAL AUTO-DETECT SETTINGS
PORT_KEYWORDS = [             # Keywords to look for in port name/description
    'Arduino', 'ttyACM', 'ttyUSB', 'usbmodem', 'usbserial'
]
ARDUINO_VIDS = {              # Known USB Vendor IDs for Arduino/clones
    0x2341, 0x2A03, 0x1A86, 0x0403
}

# OUTLIER FILTERING SETTINGS
MAX_TORQUE = 2.0             # Full-scale torque (Nm) for spike detection
MAX_POWER = 50.0             # Full-scale power (W) for spike detection
OUTLIER_FACTOR = 0.8         # Fraction of full-scale to treat as an outlier
# ──────────────────────────────────────

# Initialize Flask app, pointing to the local 'templates' folder for index.html
app = Flask(
    __name__,
    template_folder=Path(__file__).with_suffix('').parent / 'templates'
)

# ─────────── GLOBAL STATE ───────────
# These variables are updated by the serial reader thread and read by the HTTP handler
latest_rpm = 0.0             # Most recent RPM value
latest_speed = 0.0           # Most recent speed (km/h)
latest_torque = 0.0          # Most recent torque (Nm)
latest_power = 0.0           # Most recent power (W)
_last_sample = 0.0           # Timestamp of last received data
_lock = threading.Lock()     # Mutex to protect shared state

# History buffers for calculations
speed_history = deque()      # Stores (timestamp, speed) for dynamic zeroing
omega_history = deque()      # Stores (timestamp, omega) for torque calculation
_last_pub = {'torque': 0.0, 'power': 0.0}  # Last published torque/power for filtering

# Precompute roller circumference (meters)
circ_m = ROLLER_DIAMETER_MM / 1000 * math.pi


# ─────────── SERIAL PORT DETECTION ───────────
def find_arduino_port():
    """
    Scan all available serial ports and return the first one matching known Arduino IDs or keywords.
    Falls back to the sole port if only one is present.
    """
    ports = list(serial.tools.list_ports.comports())

    # 1) Match by known USB Vendor ID
    for p in ports:
        if p.vid in ARDUINO_VIDS:
            return p.device
    # 2) Match by name or description keywords
    for p in ports:
        desc = (p.description or '').lower()
        devn = p.device.lower()
        if any(key.lower() in desc or key.lower() in devn for key in PORT_KEYWORDS):
            return p.device
    # 3) If only one port exists, use it
    if len(ports) == 1:
        return ports[0].device
    # No match found
    return None


# ─────────── SERIAL READER THREAD ───────────
def serial_reader():
    """
    Thread function: opens serial port, reads lines, parses period_us,
    then computes RPM, speed, torque, and power and updates global state.
    """
    global latest_rpm, latest_speed, latest_torque, latest_power, _last_sample

    port = find_arduino_port()
    if not port:
        # If detection fails, list all ports for debugging
        print("[ERR] Arduino port not found. Available ports:")
        for p in serial.tools.list_ports.comports():
            vid = hex(p.vid) if p.vid else '?'
            pid = hex(p.pid) if p.pid else '?'
            print(f"  - {p.device}: {p.description} (VID:PID={vid}:{pid})")
        return

    print(f"Opening serial port {port}@{SERIAL_BAUD}")
    try:
        ser = serial.Serial(port, SERIAL_BAUD, timeout=0.1)
    except serial.SerialException as e:
        print(f"[ERR] {e}")
        return

    while True:
        # Read a line from Arduino: expected CSV with at least 3 fields
        line = ser.readline().decode('ascii', errors='ignore').strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 3:
            continue

        # Third field is period between revolutions in µs
        try:
            period_us = int(parts[2])
        except ValueError:
            continue

        # --- Compute RPM & Speed ---
        if period_us <= 0:
            rpm = 0.0
            speed = 0.0
        else:
            rpm = 60_000_000 / period_us  # convert µs period to rev/min
            speed = rpm / 60 * circ_m * 3.6  # m/s → km/h factor

        # --- Compute Torque & Power ---
        now = time.time()
        omega = 2 * math.pi * rpm / 60  # rad/s

        # Maintain sliding window of omega values
        omega_history.append((now, omega))
        old = None
        # Pop entries older than WINDOW_S seconds
        while omega_history and omega_history[0][0] <= now - WINDOW_S:
            old = omega_history.popleft()

        # Angular acceleration = Δω / Δt
        if old:
            t_old, w_old = old
            alpha = (omega - w_old) / (now - t_old)
            torque = max(J * alpha, 0.0)  # clamp negative
        else:
            torque = 0.0
        power = max(omega * torque, 0.0)

        # Update global state under lock
        with _lock:
            latest_rpm = rpm
            latest_speed = speed
            latest_torque = torque
            latest_power = power
            _last_sample = now


# ─────────── FLASK ENDPOINTS ───────────
@app.route('/')
def index():
    """Serve the main dashboard page."""
    return render_template('index.html')


@app.route('/data')
def data():
    """
    JSON endpoint polled by the frontend every ~200ms.
    Applies dynamic zeroing for low speeds and filters out spikes.
    """
    global _last_pub
    with _lock:
        rpm = latest_rpm
        speed = latest_speed
        torque = latest_torque
        power = latest_power
        age = time.time() - _last_sample

    # If data is stale, zero everything
    if age > STOP_TIMEOUT_S:
        rpm = speed = torque = power = 0.0

    # Record recent speeds for dynamic zeroing
    now = time.time()
    speed_history.append((now, speed))
    # Remove entries older than ZERO_DURATION_S
    while speed_history and speed_history[0][0] < now - ZERO_DURATION_S:
        speed_history.popleft()

    # If speed has been consistently low and flat, zero it out
    recent_speeds = [s for _, s in speed_history]
    if (recent_speeds
        and max(recent_speeds) < ZERO_SPEED_THRESH
        and (max(recent_speeds) - min(recent_speeds)) < ZERO_VARIATION_THRESH):
        speed = 0.0
        rpm = 0.0

    # Filter out torque spikes
    if torque and abs(torque - _last_pub['torque']) > MAX_TORQUE * OUTLIER_FACTOR:
        torque = _last_pub['torque']
    # Filter out power spikes
    if power and abs(power - _last_pub['power']) > MAX_POWER * OUTLIER_FACTOR:
        power = _last_pub['power']

    # Save for next filtering
    _last_pub['torque'] = torque
    _last_pub['power'] = power

    # Round to desired precision and return
    return jsonify({
        'rpm': round(rpm, 1),
        'speed': round(speed, 2),
        'torque': round(torque, 2),
        'power': round(power, 1),
    })


# ─────────── ENTRY POINT ───────────
if __name__ == '__main__':
    # Start the background thread for serial reading
    threading.Thread(target=serial_reader, daemon=True).start()
    # Launch Flask on port 8080
    app.run(debug=False, port=8080)
