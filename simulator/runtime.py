
from logging import log
import yaml
import paho.mqtt.client as mqtt
from typing import Optional, Any

from .mqtt import MQTTService
from .factory import DeviceFactory

from .logger import logger
# Seus imports reais do projeto (ajuste os caminhos se necessário)

# Garante que a rota global do Home Assistant está definida no escopo
BASE_ROUTE = "homeassistant"

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
        
        self.broker_host = config_data.get("broker", "localhost")
        
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
                logger.info(f"Dispositivo carregado: {device.name} ({device.domain})")
            except Exception as e:
                logger.error(f"Erro ao carregar dispositivo {dev_entry.get('id')}: {e}")

    def start(self, port: int = 1883) -> None:
        """Conecta ao broker, inicia o loop de rede e ativa os dispositivos."""
        logger.info(f"Conectando ao broker: {self.broker_host}...")
        self.client.connect(self.broker_host, port, 60)
        self.client.loop_start()
        
        logger.info("Loop de rede iniciado. Executando setups...")
        # Inicializa o setup de todos os dispositivos carregados (Discovery + State)
        for device in self.devices:
            device.setup()

    def stop(self) -> None:
        """Sinaliza 'offline' para o Home Assistant e desliga a rede MQTT."""
        logger.info("\nEncerrando Runtime de forma segura...")
        
        # 1. Avisa o HA que todos os dispositivos sumiram da rede
        for device in self.devices:
            try:
                self.service.publish(device.availability_topic(), "offline", retain=True)
            except Exception:
                pass
        
        # 2. Desliga os loops de comunicação com segurança
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("Runtime encerrada com sucesso.")

    def get_device(self, device_id: str) -> Optional[Any]:
        """Busca um dispositivo gerenciado na memória pelo ID."""
        return next((d for d in self.devices if d.id == device_id), None)
