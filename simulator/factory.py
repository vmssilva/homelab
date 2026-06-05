from typing import Dict, Optional, Type, Any

from .devices import *
from .logger import logger

class DeviceFactory:
    _registry: Dict[str, Type[Device]] = {
        "light": Light,
        "switch": Switch,
        "cover": Cover,
        "number": Number,
        "fan": Fan,
        "sensor": Sensor,
        "binary_sensor": BinarySensor,
        "energy": Energy,
        "lock": Lock,
        "button": Button,
        "vacuum": Vacuum,
        "siren": Siren,
        "alarm": Alarm,
        "device_tracker": DeviceTracker,
        "humidifier": Humidifier,
        "water_heater": WaterHeater,
        "climate": Climate,
    }

    @classmethod
    def create(
        cls,
        device_type: str,
        id: str,
        name: Optional[str],
        service: Any,
        raw_data: dict,
    ) -> Device:
        device_class = cls._registry.get(device_type.lower())

        if not device_class:
            raise ValueError(
                logger.error(f"Tipo de dispositivo desconhecido de fábrica: '{device_type}'")
            )

        # 1. Trata o nome amigável se vier nulo do YAML
        final_name: str = (
            name if name is not None else id.replace("_", " ").title()
        )

        # 2. Estrutura o dicionário 'options' exatamente como a nova classe base espera
        options: Dict[str, Any] = {
            "configurations": raw_data.get("configurations", {}),
            "attributes": raw_data.get("attributes", {}),
            "adapters": raw_data.get("adapters", []),
            "children": raw_data.get("children", []),
            "sensors": raw_data.get("sensors", []),
            "variables": raw_data.get("variables", {})
        }

        # 3. Move chaves soltas na raiz do YAML para dentro de 'attributes'
        reserved_keys = ["type", "id", "name", "domain", "device_type", "configurations", "attributes", "adapters"]
        for key, value in raw_data.items():
            if key not in reserved_keys:
                options["attributes"][key] = value

        # 4. Instancia o dispositivo passando o contrato unificado
        device = device_class(
            id=id, 
            name=final_name, 
            service=service, 
            options=options
        )

        # 5. Se a subclasse tiver pós-inicialização (opcional)
        if hasattr(device, "post_init"):
            device.post_init()  # type: ignore

        return device


