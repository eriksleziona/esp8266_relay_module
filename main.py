import gc
import dht
import machine
import network
import time
import ubinascii
import ujson
from machine import Pin
from umqtt.simple import MQTTClient

# =========================
# User configuration
# =========================
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

MQTT_BROKER = "192.168.1.100"
MQTT_PORT = 1883
MQTT_USER = "mqtt_user"
MQTT_PASSWORD = "mqtt_pass"
MQTT_KEEPALIVE = 60

DEVICE_NAME = "ESP8266 4CH Relay"
DEVICE_PREFIX = "esp8266-relay4"
DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "home/%s" % DEVICE_PREFIX
STATE_JSON_TOPIC = "%s/status" % BASE_TOPIC

# Most 4-channel ESP8266 relay boards are active LOW.
RELAY_ON_LEVEL = 0
RELAY_OFF_LEVEL = 1

WIFI_CONNECT_TIMEOUT_S = 20
RECONNECT_DELAY_S = 5
MQTT_PING_INTERVAL_MS = 30000
SENSOR_PUBLISH_INTERVAL_MS = 5000

# NodeMCU D7 = GPIO13. Keep this separate from the relay pins below.
DHT_PIN = 13

# NodeMCU pin mapping:
# D1 = GPIO5, D2 = GPIO4, D5 = GPIO14, D6 = GPIO12
#
# mode:
#   "switch" -> stays ON/OFF until commanded
#   "button" -> pulses for pulse_ms and goes back OFF
RELAYS = [
    {
        "channel": 1,
        "name": "Relay 1",
        "pin": 5,
        "mode": "switch",
        "startup": "OFF",
        "icon": "mdi:toggle-switch",
    },
    {
        "channel": 2,
        "name": "Relay 2",
        "pin": 4,
        "mode": "switch",
        "startup": "OFF",
        "icon": "mdi:toggle-switch",
    },
    {
        "channel": 3,
        "name": "Relay 3",
        "pin": 14,
        "mode": "switch",
        "startup": "OFF",
        "icon": "mdi:toggle-switch",
    },
    {
        "channel": 4,
        "name": "Relay 4",
        "pin": 12,
        "mode": "switch",
        "startup": "OFF",
        "icon": "mdi:toggle-switch",
    },
]

DEVICE_ID = "%s_%s" % (
    DEVICE_PREFIX,
    ubinascii.hexlify(machine.unique_id()).decode(),
)
CLIENT_ID = DEVICE_ID.encode()
AVAILABILITY_TOPIC = "%s/availability" % BASE_TOPIC
AVAILABILITY_TOPIC_BYTES = AVAILABILITY_TOPIC.encode()
STATE_JSON_TOPIC_BYTES = STATE_JSON_TOPIC.encode()

wlan = network.WLAN(network.STA_IF)
client = None
last_ping_ms = 0
command_topics = {}
dht_sensor = None
last_sensor_read_ms = None


def slugify(value):
    result = []
    last_was_sep = False
    for char in value.lower():
        if ("a" <= char <= "z") or ("0" <= char <= "9"):
            result.append(char)
            last_was_sep = False
        elif not last_was_sep:
            result.append("_")
            last_was_sep = True

    slug = "".join(result).strip("_")
    if slug:
        return slug
    return "relay"


def normalize_switch_state(value):
    if str(value).upper() == "ON":
        return "ON"
    return "OFF"


def normalize_mode(value):
    mode = str(value).lower()
    if mode in ("switch", "button"):
        return mode
    return "switch"


def set_relay_output(relay, is_on):
    relay["pin_obj"].value(RELAY_ON_LEVEL if is_on else RELAY_OFF_LEVEL)


def publish_bytes(topic, payload, retain=False):
    if client is None:
        return

    topic_bytes = topic if isinstance(topic, bytes) else topic.encode()
    payload_bytes = payload if isinstance(payload, bytes) else payload.encode()
    client.publish(topic_bytes, payload_bytes, retain)


def publish_json(topic, payload, retain=False):
    publish_bytes(topic, ujson.dumps(payload), retain)


def publish_board_state(retain=True):
    relays = {}
    for relay in RELAYS:
        relays[str(relay["channel"])] = relay["state"]

    payload = {
        "device_id": DEVICE_ID,
        "device_name": DEVICE_NAME,
        "availability": "online" if wlan.isconnected() else "offline",
        "relays": relays,
    }
    publish_json(STATE_JSON_TOPIC_BYTES, payload, retain)


def publish_sensor_discovery():
    sensors = [
        {
            "key": "temperature",
            "name": "Temperature",
            "device_class": "temperature",
            "unit": "°C",
        },
        {
            "key": "humidity",
            "name": "Humidity",
            "device_class": "humidity",
            "unit": "%",
        },
    ]

    for sensor in sensors:
        object_id = "%s_%s" % (DEVICE_PREFIX, sensor["key"])
        unique_id = "%s_%s" % (DEVICE_ID, sensor["key"])
        state_topic = "%s/sensor/%s/state" % (BASE_TOPIC, sensor["key"])
        topic = "%s/sensor/%s/config" % (DISCOVERY_PREFIX, object_id)
        payload = {
            "name": sensor["name"],
            "unique_id": unique_id,
            "object_id": object_id,
            "state_topic": state_topic,
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device_class": sensor["device_class"],
            "state_class": "measurement",
            "unit_of_measurement": sensor["unit"],
            "device": device_payload(),
        }
        publish_json(topic, payload, True)
        time.sleep_ms(100)
        gc.collect()


def publish_sensor_readings():
    global last_sensor_read_ms

    try:
        dht_sensor.measure()
        temperature = dht_sensor.temperature()
        humidity = dht_sensor.humidity()
    except Exception as error:
        print("DHT11 read error:", error)
        last_sensor_read_ms = time.ticks_ms()
        return

    publish_bytes(
        "%s/sensor/temperature/state" % BASE_TOPIC,
        str(temperature),
        True,
    )
    publish_bytes(
        "%s/sensor/humidity/state" % BASE_TOPIC,
        str(humidity),
        True,
    )
    print("DHT11:", temperature, "°C,", humidity, "%")

    last_sensor_read_ms = time.ticks_ms()


def publish_state(relay, retain=True, publish_snapshot=True):
    publish_bytes(relay["state_topic"], relay["state"], retain)
    if publish_snapshot:
        publish_board_state(retain)
    print("State:", relay["name"], relay["state"])


def set_switch_state(relay, state, publish=True, retain=True):
    relay["state"] = normalize_switch_state(state)
    set_relay_output(relay, relay["state"] == "ON")
    if publish:
        publish_state(relay, retain)


def pulse_relay(relay):
    pulse_ms = int(relay.get("pulse_ms", 700))
    print("Pulse:", relay["name"], pulse_ms, "ms")

    relay["state"] = "ON"
    set_relay_output(relay, True)
    publish_state(relay, False)

    time.sleep_ms(pulse_ms)

    relay["state"] = "OFF"
    set_relay_output(relay, False)
    publish_state(relay, False)


def device_payload():
    return {
        "identifiers": [DEVICE_ID],
        "name": DEVICE_NAME,
        "model": "ESP8266 4CH Relay",
        "manufacturer": "DIY",
        "sw_version": "MicroPython",
    }


def publish_discovery():
    for relay in RELAYS:
        object_id = "%s_ch%d_%s" % (
            DEVICE_PREFIX,
            relay["channel"],
            relay["slug"],
        )
        unique_id = "%s_ch%d" % (DEVICE_ID, relay["channel"])
        mode = relay["mode"]

        if mode == "button":
            topic = "%s/button/%s/config" % (DISCOVERY_PREFIX, object_id)
            payload = {
                "name": relay["name"],
                "unique_id": unique_id,
                "object_id": object_id,
                "command_topic": relay["command_topic_text"],
                "payload_press": "PRESS",
                "availability_topic": AVAILABILITY_TOPIC,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device_payload(),
            }
        else:
            topic = "%s/switch/%s/config" % (DISCOVERY_PREFIX, object_id)
            payload = {
                "name": relay["name"],
                "unique_id": unique_id,
                "object_id": object_id,
                "command_topic": relay["command_topic_text"],
                "state_topic": relay["state_topic_text"],
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
                "availability_topic": AVAILABILITY_TOPIC,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device_payload(),
            }

        if relay.get("icon"):
            payload["icon"] = relay["icon"]

        publish_json(topic, payload, True)
        time.sleep_ms(100)
        gc.collect()


def publish_all_states():
    for relay in RELAYS:
        publish_state(relay, True, False)
        time.sleep_ms(50)
    publish_board_state(True)


def prepare_relays():
    command_topics.clear()

    for relay in RELAYS:
        relay["mode"] = normalize_mode(relay.get("mode", "switch"))
        relay["slug"] = slugify(relay["name"])
        relay["pin_obj"] = Pin(relay["pin"], Pin.OUT, value=RELAY_OFF_LEVEL)
        relay["command_topic_text"] = "%s/%d/set" % (BASE_TOPIC, relay["channel"])
        relay["state_topic_text"] = "%s/%d/state" % (BASE_TOPIC, relay["channel"])
        relay["command_topic"] = relay["command_topic_text"].encode()
        relay["state_topic"] = relay["state_topic_text"].encode()

        if relay["mode"] == "switch":
            relay["state"] = normalize_switch_state(relay.get("startup", "OFF"))
        else:
            relay["state"] = "OFF"

        set_relay_output(relay, relay["state"] == "ON")
        command_topics[relay["command_topic"]] = relay


def prepare_sensor():
    global dht_sensor
    dht_sensor = dht.DHT11(Pin(DHT_PIN))


def mqtt_callback(topic, msg):
    relay = command_topics.get(topic)
    if relay is None:
        print("Unknown topic:", topic)
        return

    try:
        command = msg.decode().strip().upper()
        print("Command:", relay["name"], command)

        if relay["mode"] == "button":
            if command in ("PRESS", "ON", "TOGGLE"):
                pulse_relay(relay)
            else:
                print("Unsupported button command:", command)
            return

        if command == "TOGGLE":
            command = "OFF" if relay["state"] == "ON" else "ON"

        if command in ("ON", "OFF"):
            set_switch_state(relay, command)
        else:
            print("Unsupported switch command:", command)
    except Exception as error:
        print("Callback error:", error)


def connect_wifi():
    wlan.active(True)
    try:
        wlan.config(dhcp_hostname=DEVICE_PREFIX)
    except Exception:
        pass

    if wlan.isconnected():
        return

    print("Connecting to WiFi...")
    try:
        wlan.disconnect()
    except Exception:
        pass

    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    started = time.ticks_ms()

    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), started) > (WIFI_CONNECT_TIMEOUT_S * 1000):
            raise OSError("WiFi timeout")
        time.sleep_ms(250)

    print("WiFi connected:", wlan.ifconfig()[0])


def close_mqtt():
    global client

    if client is None:
        return

    try:
        client.disconnect()
    except Exception:
        pass

    client = None


def connect_mqtt():
    global client
    global last_ping_ms

    close_mqtt()
    gc.collect()

    client = MQTTClient(
        CLIENT_ID,
        MQTT_BROKER,
        port=MQTT_PORT,
        user=MQTT_USER or None,
        password=MQTT_PASSWORD or None,
        keepalive=MQTT_KEEPALIVE,
    )
    client.set_callback(mqtt_callback)
    client.set_last_will(AVAILABILITY_TOPIC_BYTES, b"offline", True)
    client.connect()

    for relay in RELAYS:
        client.subscribe(relay["command_topic"])

    publish_bytes(AVAILABILITY_TOPIC_BYTES, b"online", True)
    publish_discovery()
    publish_sensor_discovery()
    publish_all_states()
    last_ping_ms = time.ticks_ms()

    print("MQTT connected:", MQTT_BROKER)


def ensure_connections():
    if not wlan.isconnected():
        close_mqtt()
        connect_wifi()

    if client is None:
        connect_mqtt()


def main():
    global last_ping_ms

    prepare_relays()
    prepare_sensor()
    print("Device ID:", DEVICE_ID)

    while True:
        try:
            ensure_connections()
            client.check_msg()

            now = time.ticks_ms()
            if (
                last_sensor_read_ms is None
                or time.ticks_diff(now, last_sensor_read_ms)
                >= SENSOR_PUBLISH_INTERVAL_MS
            ):
                publish_sensor_readings()

            if time.ticks_diff(now, last_ping_ms) >= MQTT_PING_INTERVAL_MS:
                client.ping()
                last_ping_ms = now

            time.sleep_ms(100)
        except OSError as error:
            print("Connection error:", error)
            close_mqtt()
            time.sleep(RECONNECT_DELAY_S)
        except Exception as error:
            print("Runtime error:", error)
            time.sleep_ms(500)


main()
