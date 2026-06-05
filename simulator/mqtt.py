import json
from typing import Any
from typing import Callable

from .logger import logger

class MQTTService:
    """Serviço responsável por encapsular as operações do MQTT com Logs."""

    def __init__(self, client) -> None:
        self.client = client

    # Atalho inteligente para ler/escrever o on_message direto no cliente Paho
    @property
    def on_message(self) -> Any:
        return self.client.on_message

    @on_message.setter
    def on_message(self, callback: Callable[[Any, Any, Any], None]) -> None:
        self.client.on_message = callback

    def publish(
        self, topic: str, payload: Any, retain: bool = True, qos: int = 0
    ) -> None:
        if isinstance(payload, (dict, list)):
            payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
            log_payload = f"\n{payload_str}"
        else:
            payload_str = str(payload)
            log_payload = payload_str

        logger.debug(f"[MQTT OUT] -> Tópico: {topic}")
        logger.debug(f"               Payload: {log_payload}")
        logger.debug(f"               Retain: {retain} | QoS: {qos}")
        logger.debug("-" * 50)

        self.client.publish(topic, payload_str, qos=qos, retain=retain)

    def subscribe(self, topic: str, callback: Callable[[Any, Any, Any], None]) -> None:
        logger.debug(f"[MQTT SUB] -> Inscrito no tópico de comando: {topic}")
        # ROTEAMENTO POR DISPOSITIVO!
        self.client.message_callback_add(topic, callback)
        self.client.subscribe(topic)


