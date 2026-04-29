from flask import Flask, jsonify, render_template_string
import threading
import time
import math
import smtplib
import json
import os

import PCF8591 as ADC
import RPi.GPIO as GPIO
ON_PI = True
print("[INFO] Running on Raspberry Pi — real sensors active")
    
EMAIL_ENABLED   = True          # Set True to enable email alerts
EMAIL_SENDER    = "mcgillivrayjulia@gmail.com"
EMAIL_PASSWORD  = "pmbs qcnm xnmm ccqm"   # Gmail App Password (not your real password)
EMAIL_RECIPIENT = "claudiasofiarch@gwu.edu"

TEMP_MAX        = 33.0   # °C  — alert if ABOVE this
LIGHT_MAX       = 400    # ADC value — alert if BELOW this
MOISTURE_MAX    = 45000  # Raw ADC — alert if ABOVE this (high = dry for your sensor)

DO_PIN          = 17     # GPIO pin for temperature module digital out
ADC_ADDR        = 0x48   # PCF8591 I2C address

# ──────────────────────────────────────────────
# SHARED STATE
# ──────────────────────────────────────────────
sensor_data = {
    "temperature": None,
    "light": None,
    "moisture_raw": None,
    "moisture_pct": None,
    "moisture_level": "UNKNOWN",
    "timestamp": None
}
alerts_sent = {"temp": False, "light": False, "moisture": False}

# ──────────────────────────────────────────────
# SENSOR READING
# ──────────────────────────────────────────────
def read_temperature():
    """Reads thermistor on ADC channel 0 via PCF8591"""
    try:
        analog_val = ADC.read(1)
        if analog_val in (0, 255):   # Sensor not connected / maxed out
            return None
        Vr   = 3.3 * float(analog_val) / 255
        Rt   = 10000 * Vr / (3.3 - Vr)
        temp = 1 / (((math.log(Rt / 10000)) / 3950) + (1 / (273.15 + 25)))
        return round(temp - 273.15, 2)
    except Exception as e:
        print(f"[TEMP ERROR] {e}")
        return None

def read_light():
    """Reads photoresistor on ADC channel 1 via PCF8591 (0–255)"""
    try:
        raw = ADC.read(2)
        # Map 0–255 to approximate lux (0–1000). Adjust multiplier for your sensor.
        lux = round(raw * (1000 / 255), 1)
        return lux
    except Exception as e:
        print(f"[LIGHT ERROR] {e}")
        return None

def read_moisture():
    """
    Reads soil moisture on ADC channel 3 via PCF8591.
    Your sensor: HIGH raw value = DRY, LOW = WET
    """
    try:
        # If using ADS1115 (your original code), use channel A3
        # If using PCF8591, channel 0 shown here
        raw = ADC.read(3)
        raw = ADC.read(3)  # throw away first read
        # Scale raw (0-255 for PCF8591) to percentage
        # For PCF8591: invert so 100% = wet, 0% = dry
        pct  = round((1 - raw / 255) * 100, 1)
        level = "DRY" if raw > (MOISTURE_MAX / 257) else "WET"  # Scaled threshold
        return raw, pct, level
    except Exception as e:
        print(f"[MOISTURE ERROR] {e}")
        return None, None, "UNKNOWN"

# ──────────────────────────────────────────────
# EMAIL ALERTS
# ──────────────────────────────────────────────
def send_email(subject, body):
    if not EMAIL_ENABLED:
        print(f"[ALERT] (email disabled) {subject}: {body}")
        return
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            message = f"Subject: {subject}\n\n{body}"
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, message)
        print(f"[EMAIL SENT] {subject}")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

def check_and_alert(temp, light, moisture_raw, moisture_level):
    global alerts_sent

    # Temperature too high
    if temp is not None:
        if temp > TEMP_MAX and not alerts_sent["temp"]:
            send_email(
                "PlantWatch: High Temperature Alert",
                f"Temperature is {temp}C - above your threshold of {TEMP_MAX}C.Check on your plant!"
            )
            alerts_sent["temp"] = True
        elif temp <= TEMP_MAX:
            alerts_sent["temp"] = False

    # Light too low
    if light is not None:
        if light > LIGHT_MAX and not alerts_sent["light"]:
            send_email(
                "PlantWatch: Low Light Alert",
                f"Light level is {light} lux - above your minimum of {LIGHT_MAX} lux.Your plant may need more light!"
            )
            alerts_sent["light"] = True
        elif light <= LIGHT_MAX:
            alerts_sent["light"] = False
#your plant might need n=more light!!
    # Soil too dry
    if moisture_level == "DRY" and not alerts_sent["moisture"]:
        send_email(
            "PlantWatch: Soil Dry Alert",
            f"Soil moisture sensor reads DRY (raw: {moisture_raw}).Time to water your plant!"
        )
        alerts_sent["moisture"] = True
    elif moisture_level == "WET":
        alerts_sent["moisture"] = False

# ──────────────────────────────────────────────
# DEMO MODE (simulated data when not on Pi)
# ──────────────────────────────────────────────
import random
# ──────────────────────────────────────────────
# BACKGROUND SENSOR LOOP
# ──────────────────────────────────────────────
def sensor_loop():
    if ON_PI:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(DO_PIN, GPIO.IN)
        ADC.setup(ADC_ADDR)

    while True:
        try:
            temp  = read_temperature()
            light = read_light()
            raw_m, pct_m, level_m = read_moisture()

            sensor_data["temperature"]    = temp
            sensor_data["light"]          = light
            sensor_data["moisture_raw"]   = raw_m
            sensor_data["moisture_pct"]   = pct_m
            sensor_data["moisture_level"] = level_m
            sensor_data["timestamp"]      = time.time()

            print(f"[DATA] Temp={temp}°C  Light={light}lux  Moisture={pct_m}% ({level_m})")
            check_and_alert(temp, light, raw_m, level_m)

        except Exception as e:
            print(f"[SENSOR LOOP ERROR] {e}")

        time.sleep(3)   # Read every 3 seconds

# ──────────────────────────────────────────────
# FLASK APP
# ──────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def dashboard():
    # Serve the HTML file (put index.html in templates/ folder)
    try:
        with open("templates/index.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return "<h2>Error: templates/index.html not found</h2><p>Make sure index.html is in a 'templates' folder next to app.py</p>", 404

@app.route("/data")
def data():
    """JSON endpoint the dashboard polls every 5 seconds"""
    return jsonify({
        "temperature": sensor_data["temperature"],
        "light":       sensor_data["light"],
        "moisture":    sensor_data["moisture_pct"],
        "moisture_raw": sensor_data["moisture_raw"],
        "moisture_level": sensor_data["moisture_level"],
        "timestamp":   sensor_data["timestamp"],
        "demo_mode":   not ON_PI
    })

@app.route("/status")
def status():
    return jsonify({
        "on_pi": ON_PI,
        "email_enabled": EMAIL_ENABLED,
        "thresholds": {
            "temp_max": TEMP_MAX,
            "light_max": LIGHT_MAX,
            "moisture_threshold": MOISTURE_MAX
        }
    })

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # Start sensor reading in background thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()

    print("\n====================================")
    print("  PlantWatch running!")
    print("  Open browser → http://localhost:5000")
    print("  On same WiFi → http://128.164.137.135:5000")
    print("  Get Pi IP with: hostname -I")
    print("====================================\n")
    
    #Join Hotspot Named: iPhone 10110010
    #Password: holaguyz222

    app.run(host="0.0.0.0", port=5000, debug=False)