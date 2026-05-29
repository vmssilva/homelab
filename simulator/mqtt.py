from typing import Any, Callable

import json

class MQTTService:
    """Serviço responsável por encapsular as operações do MQTT com Logs."""

    def __init__(self, client) -> None:
        self.client = client

    def publish(
        self, topic: str, payload: Any, retain: bool = False, qos: int = 0
    ) -> None:
        # Se for um dicionário (como o Discovery), formata como string JSON bonita
        if isinstance(payload, (dict, list)):
            payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
            log_payload = f"\n{payload_str}"  # Quebra linha para JSONs grandes
        else:
            payload_str = str(payload)
            log_payload = payload_str

        # Print do Log de Saída (Outbound)
        print(f"📡 [MQTT OUT] ➡️ Tópico: {topic}")
        print(f"               Payload: {log_payload}")
        print(f"               Retain: {retain} | QoS: {qos}")
        print("-" * 50)

        self.client.publish(topic, payload_str, qos=qos, retain=retain)

    def subscribe(self, topic: str, callback: Callable[[Any, Any, Any], None]) -> None:
        print(f"📥 [MQTT SUB] 🔄 Inscrito no tópico de comando: {topic}")
        self.client.message_callback_add(topic, callback)
        self.client.subscribe(topic)
