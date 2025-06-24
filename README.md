# RC Car Dyno Dashboard

A lightweight Flask application that reads wheel rotation data from an Arduino and displays live:

* **RPM** (revolutions per minute)
* **Speed** (km/h)
* **Torque** (Nm)
* **Power** (W)

It automatically detects the Arduino serial port on macOS, Windows, or Linux, applies dynamic zeroing to suppress low-speed noise, and filters out torque/power outliers for a stable dashboard.

---

## File Structure

```
project-root/
├── app.py                  # Main Flask application and serial reader
├── requirements.txt        # Python dependencies
├── templates/
│   └── index.html          # Dashboard frontend (HTML + Chart.js)
└── README.md               # This documentation
```

### `app.py`

* **Serial detection**: Uses `pyserial.tools.list_ports` to find an Arduino by USB Vendor ID or port keywords (`Arduino`, `ttyACM`, etc.).
* **Data reader thread**: Reads CSV-formatted lines from the Arduino, where field #3 is the period between wheel revolutions (µs).
* **Calculations**:

  * **RPM** = 60 000 000 / period\_us
  * **Speed** = RPM/60 × roller circumference × 3.6
  * **Torque** = J × α, with α computed over a sliding window of `WINDOW_S` seconds
  * **Power** = ω × Torque
* **Zeroing logic**: Monitors recent speeds; if speed remains below `ZERO_SPEED_THRESH` for `ZERO_DURATION_S` seconds with minimal variation, speed/RPM are forced to zero.
* **Outlier filtering**: Suppresses sudden jumps in torque/power beyond `OUTLIER_FACTOR` of full-scale.
* **Flask endpoints**:

  * `GET /` serves the static dashboard page
  * `GET /data` returns JSON `{ rpm, speed, torque, power }`

### `templates/index.html`

* **Layout**: Three Chart.js gauges displaying speed, torque, and power, plus numeric readouts.
* **Dynamic update**: Polls `/data` every 200 ms, updates gauges and text.
* **Needle plugin**: Custom Chart.js plugin draws a needle for each gauge.

---

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/antonHydro/Dashboard-Roller-Bank.git
   cd Dashboard-Roller-Bank
   ```

2. **Create a Python virtual environment** (optional but recommended):

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # macOS/Linux
   venv\\Scripts\\activate  # Windows
   ```

3. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```


---

## Usage

1. **Plug in** your Arduino (running a sketch that prints `timestamp, last_rev_timestamp, period_us, ...`).
2. **Run the app**:

   ```bash
   python app.py
   ```
3. **Open** your browser to `http://localhost:8080/`. The dashboard will auto-detect the serial port.

---

## Configuration

You can tweak behavior via constants at the top of `app.py`:

* `SERIAL_BAUD`: Serial baud rate (default 9600).
* `ROLLER_DIAMETER_MM`: Roller diameter in mm (update for your setup).
* `STOP_TIMEOUT_S`: Time to wait before zeroing if data stops.
* `WINDOW_S`: Window (s) for torque calculation.
* `ZERO_SPEED_THRESH`, `ZERO_DURATION_S`, `ZERO_VARIATION_THRESH`: Controls dynamic zeroing on low speeds.
* `MAX_TORQUE`, `MAX_POWER`, `OUTLIER_FACTOR`: Controls spike filtering for torque/power.

---

## License

MIT License. Feel free to adapt and extend!

