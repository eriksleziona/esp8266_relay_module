# ESP8266 4-Channel Relay Module

MicroPython firmware for an ESP8266 4-channel relay board with:

- WiFi connection
- MQTT control
- Home Assistant MQTT discovery
- Automatic reconnect after WiFi or broker loss
- Per-relay `switch` or momentary `button` mode

This is useful for normal relay switching and also for short trigger actions like remote start, gate open, or pulse inputs.

## Hardware

- ESP8266 / NodeMCU
- 4-channel relay board
- MQTT broker such as Mosquitto
- Home Assistant with the MQTT integration enabled

## Default Pin Mapping

- Relay 1 -> GPIO5 (`D1`)
- Relay 2 -> GPIO4 (`D2`)
- Relay 3 -> GPIO14 (`D5`)
- Relay 4 -> GPIO12 (`D6`)

The script assumes an active LOW relay module, which is the most common type for ESP8266 relay boards.

## Files

- `main.py` - upload this to the ESP8266 as `main.py`

## Configuration

Edit the values at the top of `main.py`:

```python
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

MQTT_BROKER = "192.168.1.100"
MQTT_PORT = 1883
MQTT_USER = "mqtt_user"
MQTT_PASSWORD = "mqtt_pass"

DEVICE_NAME = "ESP8266 4CH Relay"
DEVICE_PREFIX = "esp8266-relay4"
BASE_TOPIC = "home/%s" % DEVICE_PREFIX
```

Use a different `DEVICE_PREFIX` for each physical board so MQTT topics and Home Assistant entities stay unique.

### Relay Modes

Each relay can be configured inside the `RELAYS` list:

- `mode = "switch"` keeps the relay latched ON or OFF
- `mode = "button"` turns the relay ON for `pulse_ms` and then back OFF

Example momentary relay:

```python
{
    "channel": 1,
    "name": "Gate Trigger",
    "pin": 5,
    "mode": "button",
    "pulse_ms": 700,
    "icon": "mdi:gate",
}
```

For a normal retained output, keep it as:

```python
{
    "channel": 2,
    "name": "Pump Relay",
    "pin": 4,
    "mode": "switch",
    "startup": "OFF",
    "icon": "mdi:pump",
}
```

## MQTT Topics

Base topic:

```text
home/esp8266-relay4
```

Per relay topics:

- `home/esp8266-relay4/1/set`
- `home/esp8266-relay4/1/state`
- `home/esp8266-relay4/2/set`
- `home/esp8266-relay4/2/state`
- `home/esp8266-relay4/3/set`
- `home/esp8266-relay4/3/state`
- `home/esp8266-relay4/4/set`
- `home/esp8266-relay4/4/state`
- `home/esp8266-relay4/availability`

### Supported Commands

For `switch` relays:

- `ON`
- `OFF`
- `TOGGLE`

For `button` relays:

- `PRESS`
- `ON`
- `TOGGLE`

## Home Assistant

The script automatically publishes MQTT discovery config to:

- `homeassistant/switch/.../config` for `switch` relays
- `homeassistant/button/.../config` for `button` relays

After the ESP8266 connects to WiFi and MQTT, Home Assistant should discover the entities automatically.

## Install

1. Flash MicroPython to the ESP8266.
2. Upload `main.py` to the board.
3. Make sure `umqtt.simple` is available on the device.
4. Reset the ESP8266.

If your firmware does not already include `umqtt.simple`, upload that module too.

## Notes

- The script republishes Home Assistant discovery on reconnect.
- Relay states are published with retained MQTT messages.
- The availability topic uses MQTT last will, so Home Assistant can show the device offline if it disconnects unexpectedly.
