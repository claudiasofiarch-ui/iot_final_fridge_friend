# Fridge Friend Repo

#!/usr/bin/env python3
import urllib.request
import RPi.GPIO as GPIO
import PCF8591 as ADC
import paho.mqtt.client as mqtt
import time
import math
 
# THINGSPEAK CREDENTIALS 
TS_CHANNEL_ID  = "3348218"
TS_MQTT_KEY    = "6Y6TB8DZOB123DSX"     
TS_USERNAME    = "mwa0000027749793"
TS_BROKER      = "mqtt3.thingspeak.com"
TS_PORT        = 1883
 
# ThingSpeak field mapping
# field1 = temperature (F)
# field2 = distance (cm)
# field3 = light on (1/0)
# field4 = door status code (0=closed_ok, 1=open, 2=bad_seal, 3=temp_high, 4=unknown)
 
PUBLISH_TOPIC  = f"channels/{3348218}/publish"
PUBLISH_INTERVAL = 15   
 
# GPIO SETUP
GPIO.setmode(GPIO.BCM)
TRIG  = 17
ECHO  = 18
RED   = 22
GREEN = 23
GPIO.setup(TRIG,  GPIO.OUT)
GPIO.setup(ECHO,  GPIO.IN)
GPIO.setup(RED,   GPIO.OUT)
GPIO.setup(GREEN, GPIO.OUT)
ADC.setup(0x48)
 
# MQTT SETUP
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected to ThingSpeak")
    else:
        print(f"[MQTT] Connection failed (rc={rc})")
 
def on_publish(client, userdata, mid, reason_codes, properties):
    print(f"[MQTT] Published message id={mid}")
 
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fridge_{3348218}")
mqtt_client.username_pw_set(TS_USERNAME, TS_MQTT_KEY)
mqtt_client.on_connect = on_connect
mqtt_client.on_publish = on_publish
 
try:
    mqtt_client.connect(TS_BROKER, TS_PORT, keepalive=60)
    mqtt_client.loop_start()
    print(f"[MQTT] Connecting to {TS_BROKER}...")
except Exception as e:
    print(f"[MQTT] Could not connect: {e}. Sensor loop will still run.")
    mqtt_client = None
 
# SENSOR FUNCTIONS 
def get_distance():
    GPIO.output(TRIG, 0)
    time.sleep(0.000002)
    GPIO.output(TRIG, 1)
    time.sleep(0.00001)
    GPIO.output(TRIG, 0)
    while GPIO.input(ECHO) == 0:
        pulse_start = time.time()
    while GPIO.input(ECHO) == 1:
        pulse_end = time.time()
    duration = pulse_end - pulse_start
    return duration * 340 / 2 * 100
 
def get_temperature_f():
    analogVal = ADC.read(1)  # AIN1
    Vr = 5 * float(analogVal) / 255
    Rt = 10000 * Vr / (5 - Vr)
    tempK = 1 / (((math.log(Rt / 10000)) / 3950) + (1 / (273.15 + 25)))
    tempC = tempK - 273.15
    return tempC * 9/5 + 32
 
def is_light_on():
    return ADC.read(2) < 100  # AIN2 — tune threshold if needed
 
def set_led(red=False, green=False):
    GPIO.output(RED,   red)
    GPIO.output(GREEN, green)
 
def blink_red():
    GPIO.output(GREEN, False)
    GPIO.output(RED,   True)
    time.sleep(0.3)
    GPIO.output(RED,   False)
    time.sleep(0.3)
 
# MQTT PUBLISH HELPER
def publish_to_thingspeak(temp_f, distance, light_on, status_code):
    url = (
        f"https://api.thingspeak.com/update"
        f"?api_key={'ZG8Y23145ZO0NF8U'}"
        f"&field1={round(temp_f, 2)}"
        f"&field2={round(distance, 2)}"
        f"&field3={int(light_on)}"
        f"&field4={status_code}"
    )       
    try:
        response = urllib.request.urlopen(url)
        result = response.read().decode()
        print(f"[ThingSpeak] Entry ID: {result}")
    except Exception as e:
        print(f"[ThingSpeak] HTTP error: {e}")
 
# Status codes for field4
STATUS_CLOSED_OK  = 0
STATUS_OPEN       = 1
STATUS_BAD_SEAL   = 2
STATUS_TEMP_HIGH  = 3
STATUS_UNKNOWN    = 4
 
# MAIN LOOP
try:
    last_publish = 0.0
    blink_phase  = False
 
    while True:
        distance = get_distance()
        tempF    = get_temperature_f()
        light_on = is_light_on()
 
        door_closed = 0.5 <= distance <= 5.0
        door_far    = distance > 5.0
 
        # ── LED logic + determine status code
        if tempF > 60:
            status_code  = STATUS_TEMP_HIGH
            status_label = "TEMP_HIGH"
            blink_phase  = not blink_phase
            set_led(red=blink_phase, green=False)
 
        elif door_closed and not light_on and 34 <= tempF <= 60:
            status_code  = STATUS_CLOSED_OK
            status_label = "CLOSED_OK"
            set_led(red=False, green=True)
 
        elif door_far and light_on:
            status_code  = STATUS_OPEN
            status_label = "OPEN"
            set_led(red=True, green=False)
 
        elif door_closed and light_on:
            status_code  = STATUS_BAD_SEAL
            status_label = "BAD_SEAL"
            set_led(red=True, green=False)
 
        else:
            status_code  = STATUS_UNKNOWN
            status_label = "UNKNOWN"
            set_led(red=True, green=False)
 
        print(f"[{status_label}] {tempF:.2f}F | dist:{distance:.2f}cm | light:{light_on}")
 
        # ── Publish to ThingSpeak 
        now = time.time()
        if now - last_publish >= PUBLISH_INTERVAL:
            publish_to_thingspeak(tempF, distance, light_on, status_code)
            last_publish = now
 
        time.sleep(0.2)
 
except KeyboardInterrupt:
    print("\n[INFO] Shutting down...")
    GPIO.cleanup()
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("[MQTT] Disconnected")
 

 
