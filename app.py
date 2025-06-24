#!/usr/bin/env python3
"""
Very small Flask dyno viewer (RPM + kph).

• The Arduino must print:  ts_now_us, ts_last_rev_us, rev_period_us, ...
• Only fields 0 and 2 are used; the rest can be junk.
• Browse to http://127.0.0.1:5000
"""

import time, math, threading
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template
import serial

# ─────────── USER SETTINGS ───────────
SERIAL_PORT        = "/dev/cu.usbmodem143101"     # COM5 on Windows
SERIAL_BAUD        = 9600
ROLLER_DIAMETER_MM = 60.0               # edit!
STOP_TIMEOUT_S     = 1.0                # after this with no new rev → show 0 rpm
# ──────────────────────────────────────

app = Flask(__name__, template_folder=Path(__file__).with_suffix("").parent/"templates")

# shared state
latest_rpm: float           = 0.0
latest_speed: float         = 0.0
_last_sample_time: float    = 0.0       # wall‑clock seconds
_lock = threading.Lock()

circ_m = ROLLER_DIAMETER_MM / 1000 * math.pi


def serial_reader():
    """Continuously read the Arduino and update globals."""
    global latest_rpm, latest_speed, _last_sample_time

    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.1)
    except serial.SerialException as exc:
        print(f"[ERR] {exc}")
        return

    while True:
        raw = ser.readline().decode("ascii", errors="ignore")
        if not raw:
            continue
        parts = raw.strip().split(",")
        if len(parts) < 3:
            continue
        try:
            period_us = int(parts[2])
        except ValueError:
            continue
        if period_us == 0:
            continue

        last_rev_us = int(parts[1])      #  <‑‑ we already have now_us = int(parts[0])

        # ─── NEW LINE ───  detect “stalled” roller  ──────────────────────────────
        if int(parts[0]) - last_rev_us > 2 * period_us: period_us = 0
        # ------------------------------------------------------------------------

        if period_us == 0:                      # roller stopped ⇒ rpm = 0
            rpm = 0.0
            speed = 0.0
        else:
            rpm   = 60_000_000 / period_us
            speed = rpm / 60 * circ_m * 3.6

        with _lock:
            latest_rpm = rpm
            latest_speed = speed
            _last_sample_time = time.time()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/data")
def data():
    """JSON endpoint polled by the page every 200 ms."""
    with _lock:
        rpm = latest_rpm
        speed = latest_speed
        age = time.time() - _last_sample_time

    if age > STOP_TIMEOUT_S:           # roller has stopped
        rpm = 0.0
        speed = 0.0

    return jsonify({"rpm": round(rpm, 1), "speed": round(speed, 2)})


if __name__ == "__main__":
    threading.Thread(target=serial_reader, daemon=True).start()
    app.run(debug=False, port=8080)               # 0.0.0.0 if you want LAN access
