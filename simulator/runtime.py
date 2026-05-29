import paho.mqtt.client as mqtt
import yaml

from .mqtt import MQTTService
from .factory import DeviceFactory

class Runtime:
    def __init__(self):
        self.client = mqtt.Client()
        self.service = MQTTService(self.client)
        self.devices = []
        self.broker_host = "localhost"

    def load_config(self, filepath: str) -> None:
        """Carrega o arquivo YAML e gera os dispositivos através da Factory."""
        with open(filepath, "r", encoding="utf-8") as file:
            config_data = yaml.safe_load(file)
        
        # Lê o broker do arquivo (com fallback para localhost)
        self.broker_host = config_data.get("broker", "localhost")
        
        # Percorre a lista de dispositivos listados no arquivo
        for dev_entry in config_data.get("devices", []):
            try:
                device = DeviceFactory.create(
                    device_type=dev_entry.get("type"),
                    id=dev_entry.get("id"),
                    name=dev_entry.get("name"),
                    service=self.service,
                    raw_data=dev_entry
                )
                self.devices.append(device)
                print(f"Dispositivo carregado: {device.name} ({device.domain})")
            except Exception as e:
                print(f"Erro ao carregar dispositivo {dev_entry.get('id')}: {e}")

    def start(self, port=1883):
        print(f"Conectando ao broker: {self.broker_host}...")
        self.client.connect(self.broker_host, port, 60)
        self.client.loop_start()
        
        # Inicializa o setup de todos os dispositivos carregados
        for device in self.devices:
            device.setup()

