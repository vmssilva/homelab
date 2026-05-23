import time
import yaml

from .runtime import Runtime
from .devices import *


# =========================================================
# MAIN
# =========================================================

DEVICE_TYPES = {
    "light": LightDevice,
    "switch": SwitchDevice,
    "fan": FanDevice,
    "climate": ClimateDevice,
    "sensor": SensorDevice,
    "binary_sensor": BinarySensorDevice,
    "cover": CoverDevice,
    "lock": LockDevice,
    "button": ButtonDevice,
}


def load_config(path):

    with open(path, "r") as f:

        return yaml.safe_load(f)

if __name__ == "__main__":

    config = load_config(
        "simulator/config/devices.yml"
    )

    runtime = Runtime()

    for device_cfg in config["devices"]:

        device_type = device_cfg["type"]

        if device_type == "energy":
            id = device_cfg.get("id")
            name = device_cfg.get("name", id)
            base_power = device_cfg.get("base_power", 100)
            device = EnergyDevice(id, name, base_power)

            runtime.add(device)

            continue

        cls = DEVICE_TYPES[device_type]

        device_class = DEVICE_TYPES.get(
            device_type
        )

        if not device_class:

            print(
                f"[ERROR] unknown device type "
                f"{device_type}"
            )

            continue

        device_id = device_cfg["id"]
        device_name = device_cfg.get("name", device_id)

        device = cls(device_id, device_name)

        runtime.add(device)

        print(
            f"[DEVICE] loaded "
            f"{device_type}:"
            f"{device.id}"
        )

    runtime.start()
    runtime.publish_discovery()

    print("[SYSTEM] running")

    while True:

        time.sleep(1)
