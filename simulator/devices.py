import base64
import json
import random
import time

# =========================================================
# LIGHT
# =========================================================
class LightDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_id
        self.name = device_name or device_id
        self.domain = "light"

        self.online = True

        self.power = False

        self.brightness = 0
        self.target_brightness = 0

        self.fade_speed = 180

    def handle_command(self, payload):

        print(f"[LIGHT] {self.id} <- {payload}")

        try:
            data = json.loads(payload)

        except:
            return

        if "state" in data:

            self.power = data["state"] == "ON"

            if self.power and self.target_brightness == 0:
                self.target_brightness = 255

            if not self.power:
                self.target_brightness = 0

        if "brightness" in data:

            self.target_brightness = data["brightness"]

            if self.target_brightness > 0:
                self.power = True

    def tick(self, dt):

        if self.brightness < self.target_brightness:

            self.brightness += self.fade_speed * dt

            if self.brightness > self.target_brightness:
                self.brightness = self.target_brightness

        elif self.brightness > self.target_brightness:

            self.brightness -= self.fade_speed * dt

            if self.brightness < self.target_brightness:
                self.brightness = self.target_brightness

    def state_payload(self):

        return json.dumps({
            "state": "ON" if self.power else "OFF",
            "brightness": int(self.brightness),
            "online": self.online
        })


# =========================================================
# CLIMATE
# =========================================================
class ClimateDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_id
        self.name = device_name or device_id
        self.domain = "climate"

        self.online = True

        self.mode = "cool"

        self.current_temperature = 28.0
        self.target_temperature = 22.0

        self.hvac_action = "idle"

        self.cooling_power = 0.5

    def handle_command(self, payload):

        print(f"[CLIMATE] {self.id} <- {payload}")

        try:
            data = json.loads(payload)

        except:
            return

        if "mode" in data:
            self.mode = data["mode"]

        if "target_temperature" in data:
            self.target_temperature = float(
                data["target_temperature"]
            )

    def tick(self, dt):

        if self.mode == "off":

            self.hvac_action = "idle"

            return

        delta = (
            self.target_temperature
            - self.current_temperature
        )

        if abs(delta) < 0.3:

            self.hvac_action = "idle"

        elif delta < 0:

            self.hvac_action = "cooling"

            self.current_temperature -= (
                self.cooling_power * dt
            )

        else:

            self.hvac_action = "heating"

            self.current_temperature += (
                self.cooling_power * dt
            )

        self.current_temperature += (
            random.uniform(-0.02, 0.02)
        )

    def state_payload(self):

        return json.dumps({
            "mode": self.mode,
            "current_temperature": round(
                self.current_temperature,
                1
            ),
            "target_temperature": self.target_temperature,
            "hvac_action": self.hvac_action,
            "online": self.online
        })

# =========================================================
# SWITCH
# =========================================================

class SwitchDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_name or device_id
        self.name = device_id
        self.domain = "switch"

        self.online = True

        self.state = False

    def handle_command(self, payload):

        print(f"[SWITCH] {self.id} <- {payload}")

        try:
            data = json.loads(payload)
        except:
            return

        if "state" in data:

            self.state = (
                data["state"].upper() == "ON"
            )

    def tick(self, dt):
        pass

    def state_payload(self):

        return json.dumps({
            "state": "ON" if self.state else "OFF",
            "online": self.online
        })


# =========================================================
# FAN
# =========================================================

class FanDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_name or device_id
        self.name = device_id
        self.domain = "fan"

        self.online = True

        self.power = False

        self.speed = 0
        self.target_speed = 0

        self.acceleration = 80

    def handle_command(self, payload):

        print(f"[FAN] {self.id} <- {payload}")

        try:
            data = json.loads(payload)
        except:
            return

        if "state" in data:

            self.power = (
                data["state"].upper() == "ON"
            )

            if not self.power:
                self.target_speed = 0

        if "speed" in data:

            self.target_speed = int(data["speed"])

            if self.target_speed > 0:
                self.power = True

    def tick(self, dt):

        if self.speed < self.target_speed:

            self.speed += self.acceleration * dt

            if self.speed > self.target_speed:
                self.speed = self.target_speed

        elif self.speed > self.target_speed:

            self.speed -= self.acceleration * dt

            if self.speed < self.target_speed:
                self.speed = self.target_speed

    def state_payload(self):

        return json.dumps({
            "state": "ON" if self.power else "OFF",
            "speed": int(self.speed),
            "online": self.online
        })


# =========================================================
# SENSOR
# =========================================================

class SensorDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_name or device_id
        self.name = device_id
        self.domain = "sensor"

        self.online = True

        self.value = 20.0

        self.drift_speed = 0.1

    def handle_command(self, payload):

        print(f"[SENSOR] {self.id} <- {payload}")

        try:
            data = json.loads(payload)

            if "value" in data:
                self.value = float(data["value"])

        except:
            pass

    def tick(self, dt):

        self.value += random.uniform(
            -self.drift_speed,
            self.drift_speed
        ) * dt

    def state_payload(self):

        return json.dumps({
            "value": round(self.value, 2),
            "online": self.online
        })


# =========================================================
# BINARY SENSOR
# =========================================================

class BinarySensorDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_name or device_id
        self.name = device_id
        self.domain = "binary_sensor"

        self.online = True

        self.state = False

    def handle_command(self, payload):

        print(f"[BINARY_SENSOR] {self.id} <- {payload}")

        try:
            data = json.loads(payload)

            if "state" in data:

                self.state = (
                    data["state"].upper() == "ON"
                )

        except:
            pass

    def tick(self, dt):
        pass

    def state_payload(self):

        return json.dumps({
            "state": "ON" if self.state else "OFF",
            "online": self.online
        })


# =========================================================
# COVER
# =========================================================

class CoverDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_id
        self.name = device_name or device_id
        self.domain = "cover"

        self.online = True

        self.position = 0
        self.target_position = 0

        self.motor_speed = 35

        self.state = "closed"

    def handle_command(self, payload):

        print(f"[COVER] {self.id} <- {payload}")

        try:
            data = json.loads(payload)

        except:
            return

        if "position" in data:

            self.target_position = int(
                data["position"]
            )

        if "state" in data:

            cmd = data["state"].upper()

            if cmd == "OPEN":
                self.target_position = 100

            elif cmd == "CLOSE":
                self.target_position = 0

    def tick(self, dt):

        if self.position < self.target_position:

            self.position += (
                self.motor_speed * dt
            )

            self.state = "opening"

            if self.position >= self.target_position:

                self.position = self.target_position

        elif self.position > self.target_position:

            self.position -= (
                self.motor_speed * dt
            )

            self.state = "closing"

            if self.position <= self.target_position:

                self.position = self.target_position

        else:

            if self.position == 0:
                self.state = "closed"

            elif self.position == 100:
                self.state = "open"

            else:
                self.state = "stopped"

    def state_payload(self):

        return json.dumps({
            "state": self.state,
            "position": int(self.position),
            "online": self.online
        })


# =========================================================
# LOCK
# =========================================================

class LockDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_id
        self.name = device_name or device_id
        self.domain = "lock"

        self.online = True

        self.locked = True

        self.transition = 0

    def handle_command(self, payload):

        print(f"[LOCK] {self.id} <- {payload}")

        try:
            data = json.loads(payload)

        except:
            return

        if "state" in data:

            cmd = data["state"].upper()

            if cmd == "LOCK":
                self.transition = 1

            elif cmd == "UNLOCK":
                self.transition = -1

    def tick(self, dt):

        if self.transition != 0:

            time.sleep(0.8)

            self.locked = self.transition == 1

            self.transition = 0

    def state_payload(self):

        return json.dumps({
            "state":
                "LOCKED"
                if self.locked
                else "UNLOCKED",

            "online": self.online
        })


# =========================================================
# BUTTON
# =========================================================

class ButtonDevice:

    def __init__(self, device_id, device_name = None):

        self.id = device_id
        self.name = device_name or device_id
        self.domain = "button"

        self.online = True

        self.last_pressed = 0

    def handle_command(self, payload):

        print(f"[BUTTON] {self.id} pressed")

        self.last_pressed = time.time()

    def tick(self, dt):
        pass

    def state_payload(self):

        return json.dumps({
            "last_pressed": self.last_pressed,
            "online": self.online
        })


# =========================================================
# ENERGY
# =========================================================
class EnergyDevice:

    def __init__(self, device_id, name=None, base_power=100):

        self.id = device_id
        self.name = name or device_id
        self.domain = "sensor"

        self.online = True

        # potência instantânea (W)
        self.power_w = 0.0

        # energia acumulada (kWh)
        self.energy_kwh = 0.0

        # consumo base (ex: geladeira, AC idle, etc)
        self.base_power = base_power

        # estado opcional (ligado/desligado)
        self.state = "ON"

        self.last_update = time.time()

    def tick(self, dt):

        if self.state == "OFF":
            self.power_w = 0
            return

        # variação natural de carga elétrica
        fluctuation = random.uniform(-10, 10)

        self.power_w = self.base_power + fluctuation

        if self.power_w < 0:
            self.power_w = 0

        # integração para kWh
        hours = dt / 3600
        self.energy_kwh += self.power_w * hours

    def handle_command(self, payload):

        cmd = payload.strip().upper()

        if cmd == "ON":
            self.state = "ON"

        elif cmd == "OFF":
            self.state = "OFF"

        else:
            try:
                # permite setar potência manual
                self.base_power = float(payload)

            except:
                pass

    def state_payload(self):

        return {
            "power_w": round(self.power_w, 2),
            "energy_kwh": round(self.energy_kwh, 4),
            "state": self.state,
            "online": self.online
        }



# =========================================================
# CAMERA
# =========================================================
class PersonDevice:

    def __init__(self, device_id, name=None):

        self.id = device_id
        self.name = name or device_id
        self.domain = "device_tracker"

        self.online = True

        self.state = "not_home"

        # posição fake (casa = centro fixo)
        self.latitude = -23.5505
        self.longitude = -46.6333

        self.moving = False

        self.last_change = time.time()

    def handle_command(self, payload):
        pass

    def tick(self, dt):

        # muda estado aleatoriamente (simulação simples)
        if random.random() < 0.01:

            self.state = (
                "home"
                if self.state == "not_home"
                else "not_home"
            )

        # se estiver "home", fica fixo
        if self.state == "home":

            self.latitude = -23.5505
            self.longitude = -46.6333

        else:

            # simula movimento fora de casa
            self.latitude += random.uniform(-0.001, 0.001)
            self.longitude += random.uniform(-0.001, 0.001)

    def state_payload(self):

        return {
            "state": self.state,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "online": self.online
        }

# =========================================================
# CAMERA
# =========================================================
class CameraDevice:

    def __init__(self, device_id, name=None):

        self.id = device_id
        self.name = name or device_id
        self.domain = "camera"

        self.online = True

        self.image_url = ""

        self.last_update = 0

        self.update_interval = 5  # segundos

    def generate_image_url(self):

        # aqui você simula “mudança de imagem”
        # pode ser arquivo local, HTTP fake, etc

        fake_seed = random.randint(1, 5)

        return f"http://localhost:8000/camera/{self.id}/{fake_seed}.jpg"

    def tick(self, dt):

        now = time.time()

        if now - self.last_update > self.update_interval:

            self.image_url = self.generate_image_url()

            self.last_update = now

    def handle_command(self, payload):
        pass

    def state_payload(self):

        return {
            "image_url": self.image_url,
            "online": self.online
        }

