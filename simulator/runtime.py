import threading
import time
import json

import paho.mqtt.client as mqtt

BROKER = "localhost"

# =========================================================
# RUNTIME
# =========================================================
class Runtime:

    def __init__(self):

        self.devices = []

        self.client = mqtt.Client()

        self.client.on_message = self.on_message

    def add(self, device):
        self.devices.append(device)

    def start(self):

        self.client.connect(BROKER, 1883, 60)

        for device in self.devices:

            topic = (
                f"lab/"
                f"{device.domain}/"
                f"{device.id}/set"
            )

            self.client.subscribe(topic)

            print(f"[MQTT] subscribe {topic}")

        self.client.loop_start()

        threading.Thread(
            target=self.loop,
            daemon=True
        ).start()

        threading.Thread(
            target=self.publisher_loop,
            daemon=True
        ).start()

        print("[RUNTIME] started")



    def on_message(self, client, userdata, msg):

        topic = msg.topic

        payload = msg.payload.decode()

        print(f"[MQTT] {topic} -> {payload}")

        parts = topic.split("/")

        if len(parts) < 4:
            return

        device_id = parts[2]

        for device in self.devices:

            if device.id == device_id:

                device.handle_command(payload)

                break

    def to_payload(self, data):

        if isinstance(data, dict):
            return json.dumps(data)

        return str(data)
    
    def publish_discovery(self):

        for device in self.devices:

            discovery_topic = (
                f"homeassistant/"
                f"{device.domain}/"
                f"{device.id}/config"
            )

            payload = {
                "name": device.name,
                "unique_id": device.id,

                "command_topic":
                    f"lab/{device.domain}/{device.id}/set",

                "state_topic":
                    f"lab/{device.domain}/{device.id}/state",

                "availability_topic":
                    f"lab/{device.domain}/{device.id}/availability",

                "payload_available": "online",
                "payload_not_available": "offline"
            }

            # =========================================
            # LIGHT
            # =========================================

            if device.domain == "light":

                payload["schema"] = "json"

                payload["brightness"] = True

            # =========================================
            # CLIMATE
            # =========================================

            elif device.domain == "climate":

                payload["schema"] = "json"

                payload["modes"] = [
                    "off",
                    "cool",
                    "heat"
                ]

                payload["mode_state_topic"] = (
                    f"lab/climate/{device.id}/state"
                )

                payload["mode_command_topic"] = (
                    f"lab/climate/{device.id}/set"
                )

                payload["temperature_state_topic"] = (
                    f"lab/climate/{device.id}/state"
                )

                payload["temperature_command_topic"] = (
                    f"lab/climate/{device.id}/set"
                )

                payload["current_temperature_topic"] = (
                    f"lab/climate/{device.id}/state"
                )

            self.client.publish(
                discovery_topic,
                json.dumps(payload),
                retain=True
            )

            print(f"[DISCOVERY] {device.id}")


    def publisher_loop(self):

        while True:

            for device in self.devices:

                state_topic = (
                    f"lab/"
                    f"{device.domain}/"
                    f"{device.id}/state"
                )

                availability_topic = (
                    f"lab/{device.domain}/{device.id}/availability"
                )

                self.client.publish(
                    availability_topic,
                    "online",
                    retain=True
                )

                self.client.publish(
                    state_topic,
                    self.to_payload(device.state_payload()),
                    retain=True
                )

            time.sleep(1)

    def loop(self):

        last = time.time()

        while True:

            now = time.time()

            dt = now - last

            last = now

            for device in self.devices:

                device.tick(dt)

            time.sleep(0.05)
