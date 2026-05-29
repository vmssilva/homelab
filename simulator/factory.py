from typing import Dict, Optional, Type
from .devices import *

class DeviceFactory:
    _registry: Dict[str, Type[Device]] = {
        "switch": SwitchDevice,
        "light": LightDevice,
        "climate": ClimateDevice,
        "fan": FanDevice,
        "sensor": SensorDevice,
        "binary_sensor": BinarySensorDevice,
        "energy": EnergyDevice,
        "cover": CoverDevice,
        "lock": LockDevice,
        "button": ButtonDevice,
        "vacuum": VacuumDevice,
        "siren": SirenDevice,
        "alarm": AlarmDevice,
        "device_tracker": DeviceTrackerDevice,
        "media_player": MediaPlayerDevice,
        "select": SelectDevice,         # Adicionado
        "number": NumberDevice,         # Adicionado
        "humidifier": HumidifierDevice, # Adicionado
        "water_heater": WaterHeaterDevice # Adicionado
    }

    @classmethod
    def create(
        cls,
        device_type: str,
        id: str,
        name: Optional[str],
        service: MQTTService,
        raw_data: dict,
    ) -> Device:
        device_class = cls._registry.get(device_type.lower())

        if not device_class:
            raise ValueError(
                f"Tipo de dispositivo desconhecido de fábrica: '{device_type}'"
            )

        # 1. Trata o nome amigável
        final_name: str = (
            name if name is not None else id.replace("_", " ").title()
        )

        # 2. Instancia o dispositivo de forma limpa (sem passar o dicionário options)
        device = device_class(id=id, name=final_name, service=service)

        # 3. Alimenta as configurações vindas do bloco 'configurations' do YAML
        user_configs = raw_data.get("configurations", {})
        for k, v in user_configs.items():
            device.addConfiguration(k, v)

        # 4. Alimenta os atributos vindos do bloco 'attributes' do YAML
        user_attributes = raw_data.get("attributes", {})
        for k, v in user_attributes.items():
            device.addAttribute(k, v)

        # 5. Move chaves soltas na raiz do YAML para dentro de 'attributes'
        reserved_keys = ["type", "id", "name", "configurations", "attributes"]
        for key, value in raw_data.items():
            if key not in reserved_keys:
                device.addAttribute(key, value)

        # 6. Aplica a mesclagem da configuração base do Home Assistant
        device.apply_base_configuration()

        # 7. Se a subclasse tiver uma inicialização customizada pós-configuração (como a LightDevice)
        if hasattr(device, "post_init"):
            device.post_init()  # type: ignore

        return device

