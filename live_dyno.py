#!/usr/bin/env python3
"""
live_rpm_speed.py  –  real‑time RPM & speed plotter for a Hall‑sensor roller
--------------------------------------------------------------------------
• Requires the Arduino to print:  ts_now_us, ts_last_rev_us, rev_period_us, ...
• Only fields 0 and 2 are used; the rest can be junk.
"""

import argparse, sys
from collections import deque

import numpy as np
import matplotlib
matplotlib.use("TkAgg")   
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import serial


# ─────────────────── USER SETTINGS ───────────────────
ROLLER_DIAMETER_MM = 60.0          # edit to your roller
SERIAL_BAUD        = 9600
WINDOW_SAMPLES     = 1500          # on‑screen history (~75 s at 20 Hz)
ANIMATION_INTERVAL = 200            # ms between plot refreshes
# ─────────────────────────────────────────────────────


def default_port() -> str:
    return "COM3" if sys.platform.startswith("win") else "/dev/cu.usbmodem143101"


def parse_line(line: str):
    """Return (time_s, rpm) or None if the CSV is malformed."""
    parts = line.strip().split(",")
    if len(parts) < 3:
        return None
    try:
        ts_now_us     = int(parts[0])
        rev_period_us = int(parts[2])
    except ValueError:
        return None
    if rev_period_us == 0:
        return None
    rpm     = 60_000_000 / rev_period_us
    time_s  = ts_now_us / 1e6
    return time_s, rpm


def main():
    ap = argparse.ArgumentParser(description="Live RPM & speed viewer")
    ap.add_argument("-p", "--port", default=default_port())
    ap.add_argument("-b", "--baud", type=int, default=SERIAL_BAUD)
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.01)
    except serial.SerialException as e:
        sys.exit(f"Serial error: {e}")

    # rolling buffers
    t_buf, rpm_buf, spd_buf = (deque(maxlen=WINDOW_SAMPLES) for _ in range(3))
    t0 = None
    circ_m = (ROLLER_DIAMETER_MM / 1000) * np.pi

    fig, (ax_rpm, ax_spd) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    ln_rpm, = ax_rpm.plot([], [], lw=1.5)
    ln_spd, = ax_spd.plot([], [], lw=1.5)

    for ax, ttl, ylab in (
        (ax_rpm, "RPM", "RPM"),
        (ax_spd, "Speed", "km/h"),
    ):
        ax.set_title(ttl, loc="left")
        ax.set_ylabel(ylab)
        ax.grid(True, ls="--", alpha=0.4)
    ax_spd.set_xlabel("Time (s)")

    def update(_):
        nonlocal t0
        # read EVERYTHING waiting in the buffer
        while True:
            try:
                raw = ser.readline().decode("ascii", errors="ignore")
            except serial.SerialException:
                break
            if not raw:
                break
            parsed = parse_line(raw)
            if parsed is None:
                continue
            ts, rpm = parsed
            if t0 is None:
                t0 = ts
            t_rel = ts - t0
            speed_kph = rpm / 60 * circ_m * 3.6

            t_buf.append(t_rel)
            rpm_buf.append(rpm)
            spd_buf.append(speed_kph)

        # nothing new?
        if not t_buf:
            return ln_rpm, ln_spd

        ln_rpm.set_data(t_buf, rpm_buf)
        ln_spd.set_data(t_buf, spd_buf)
        for ax in (ax_rpm, ax_spd):
            ax.relim()
            ax.autoscale_view()
        return ln_rpm, ln_spd

    # keep a reference to avoid garbage collection & suppress frame‑cache warning
    ani = FuncAnimation(
        fig, update,
        interval=ANIMATION_INTERVAL,
        blit=False,
        cache_frame_data=True,
    )

    try:
        plt.tight_layout()
        plt.show()
    finally:
        ser.close()


if __name__ == "__main__":
    main()
