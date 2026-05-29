from os import wait
from typing import Any, Dict, Optional, Type
import json
from .constants import *
from .mqtt import MQTTService

from .constants import *

class Device:
    domain = "switch"
    optimistic = True
    schema = None

    def __init__(self, id: str, name: str, service: MQTTService) -> None:
        self.id = id
        self.name = name or id.replace("_", " ").title()
        self.service = service

        self.options: Dict[str, Dict[str, Any]] = {
            "configurations": {},
            "attributes": {},
        }
        self.options["attributes"]["state"] = "OFF"

    def apply_base_configuration(self) -> None:
        """Monta a configuração base do Discovery incluindo o agrupamento de Device."""
        current_schema = self.schema or self.getConfiguration("schema")

        # --- LÓGICA DE AGRUPAMENTO DE DEVICE ---
        # Criamos uma estrutura de hardware que o HA reconhece na aba 'Dispositivos'
        device_info = {
            "identifiers": [f"virtual_device_{self.id}"], # ID único do hardware
            "name": f"{self.name} Hardware",              # Nome do dispositivo físico
            "model": f"Simulador MQTT v2.0 ({self.domain.title()})",
            "manufacturer": "Python IoT Labs 2026"
        }

        base_config = {
            "name": f"{self.name}",
            "unique_id": f"{self.id}",
            "discovery_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/config",
            "command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/set",
            "state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/state",
            "availability_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
            "optimistic": self.optimistic,
            "device": device_info  # Injeta o agrupamento aqui
        }

        if current_schema is not None:
            base_config["schema"] = current_schema

        if not self.optimistic:
            base_config.pop("optimistic", None)

        # Mescla garantindo que o que está no YAML possa sobrescrever os metadados do device se necessário
        user_configs = self.options["configurations"].copy()
        
        # Se o usuário já definiu chaves de 'device' customizadas no YAML, mescla de forma segura
        if "device" in user_configs:
            base_config["device"].update(user_configs["device"])
            user_configs.pop("device")

        self.options["configurations"].update(base_config)
        self.options["configurations"].update(user_configs)

    # --- Métodos de Tópicos e Gerenciamento (Mantidos iguais) ---
    def stateTopic(self) -> str:
        return self.getConfiguration("state_topic", "")

    def discoveryTopic(self) -> str:
        return self.getConfiguration("discovery_topic", "")

    def commandTopic(self) -> str:
        return self.getConfiguration("command_topic", "")

    def addAttribute(self, key: str, value: Any) -> None:
        self.options["attributes"][key] = value

    def removeAttribute(self, key: str) -> None:
        self.options["attributes"].pop(key, None)

    def getAttribute(self, key: str, default: Any = None) -> Any:
        return self.options["attributes"].get(key, default)

    def addConfiguration(self, key: str, value: Any) -> None:
        self.options["configurations"][key] = value

    def removeConfiguration(self, key: str) -> None:
        self.options["configurations"].pop(key, None)

    def getConfiguration(self, key: str, default: Any = None) -> Any:
        return self.options["configurations"].get(key, default)

    def state(self) -> Any:
        return self.getAttribute("state")

    def payload(self) -> Dict[str, Any]:
        return self.options["attributes"]

    def updateState(self, new_state: Optional[Any] = None) -> None:
        if new_state is not None:
            self.addAttribute("state", new_state)
        self.service.publish(self.stateTopic(), str(self.state()), retain=True)

    def setup(self) -> None:
        config_payload = self.options["configurations"].copy()
        config_payload.pop("discovery_topic", None)
        self.service.publish(self.discoveryTopic(), config_payload, retain=True)

        cmd_topic = self.commandTopic()
        if cmd_topic and self.domain not in ["sensor", "binary_sensor"]:
            self.service.subscribe(cmd_topic, self._on_command_received)

        avail_topic = self.getConfiguration("availability_topic")
        if avail_topic:
            self.service.publish(avail_topic, "online", retain=True)
        self.updateState()

    def _on_command_received(self, client, userdata, msg) -> None:
        command = msg.payload.decode("utf-8")
        self.updateState(new_state=command)

class LightDevice(Device):
    domain = "light"

    def post_init(self) -> None:
        """Lógica executada após a Factory injetar os dados do YAML."""
        self.is_json_schema = self.getConfiguration("schema") == "json"

        if self.is_json_schema:
            self.options["attributes"].setdefault("state", "OFF")
            self.options["attributes"].setdefault("brightness", 255)
            self.options["attributes"].setdefault(
                "color", {"r": 255, "g": 255, "b": 255}
            )

    def updateState(self, new_state: Optional[Any] = None) -> None:
        if self.is_json_schema:
            if new_state is not None:
                if isinstance(new_state, dict):
                    if "state" in new_state:
                        self.addAttribute("state", new_state["state"])
                    if "brightness" in new_state:
                        self.addAttribute(
                            "brightness", new_state["brightness"]
                        )
                    if "color" in new_state:
                        self.addAttribute("color", new_state["color"])
                else:
                    self.addAttribute("state", str(new_state).upper())

            payload_ha = {
                "state": self.getAttribute("state"),
                "brightness": self.getAttribute("brightness"),
            }
            if self.getAttribute("color"):
                payload_ha["color"] = self.getAttribute("color")

            self.service.publish(self.stateTopic(), payload_ha, retain=True)
        else:
            if new_state is not None:
                self.addAttribute("state", str(new_state).upper())
            self.service.publish(
                self.stateTopic(), str(self.state()), retain=True
            )

    def _on_command_received(self, client, userdata, msg) -> None:
        payload_str = msg.payload.decode("utf-8")
        if self.is_json_schema:
            try:
                command_data = json.loads(payload_str)
                self.updateState(new_state=command_data)
            except json.JSONDecodeError:
                self.updateState(new_state=payload_str)
        else:
            self.updateState(new_state=payload_str)


# --- SENSORES (Apenas Leitura - Sem Tópico de Comando) ---
class SensorDevice(Device):
    domain = "sensor"
    optimistic = False

    def apply_base_configuration(self) -> None:
        super().apply_base_configuration()
        # Sensores não recebem comandos do HA, apenas enviam dados
        self.removeConfiguration("command_topic")


class BinarySensorDevice(SensorDevice):
    domain = "binary_sensor"

    def post_init(self) -> None:
        # Sensores binários no HA costumam usar ON/OFF por padrão
        self.options["attributes"].setdefault("state", "OFF")


class EnergyDevice(SensorDevice):
    domain = "sensor"

    def post_init(self) -> None:
        # Força as configurações recomendadas do HA para monitoramento de energia
        self.addConfiguration("device_class", "energy")
        self.addConfiguration("state_class", "total_increasing")
        self.addConfiguration("unit_of_measurement", "kWh")
        self.options["attributes"].setdefault("state", 0.0)


# --- ATUADORES E CONTROLES (Com Tópico de Comando) ---
class FanDevice(Device):
    domain = "fan"

    def post_init(self) -> None:
        # Suporta controle de velocidade opcional se configurado no YAML
        if self.getConfiguration("percentage"):
            self.addConfiguration(
                "percentage_command_topic",
                f"{BASE_ROUTE}/{self.domain}/{self.id}/percentage/set",
            )
            self.addConfiguration(
                "percentage_state_topic",
                f"{BASE_ROUTE}/{self.domain}/{self.id}/percentage/state",
            )
            self.options["attributes"].setdefault("percentage", 0)

    def updateState(self, new_state: Optional[Any] = None) -> None:
        if new_state is not None:
            if isinstance(new_state, dict):
                if "state" in new_state:
                    self.addAttribute("state", new_state["state"])
                if "percentage" in new_state:
                    self.addAttribute(
                        "percentage", int(new_state["percentage"])
                    )
            else:
                self.addAttribute("state", str(new_state).upper())

        # Publica o estado principal
        self.service.publish(self.stateTopic(), str(self.state()), retain=True)

        # Se tiver controle de porcentagem ativo, publica também
        pct_topic = self.getConfiguration("percentage_state_topic")
        if pct_topic:
            self.service.publish(
                pct_topic, str(self.getAttribute("percentage")), retain=True
            )

    def _on_command_received(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8")
        # Identifica se o comando veio do tópico de porcentagem ou do botão liga/desliga
        if "percentage" in msg.topic:
            print(f"🌀 [{self.name}] Alterar velocidade para: {payload}%")
            self.updateState(new_state={"percentage": payload})
        else:
            print(f"🌀 [{self.name}] Alterar estado para: {payload}")
            self.updateState(new_state=payload)


class CoverDevice(Device):
    """Controle de Cortinas, Persianas ou Portões de Garagem."""

    domain = "cover"
    optimistic = False

    def apply_base_configuration(self) -> None:
        super().apply_base_configuration()
        # Covers usam 'state_topic' para posição/estado, mas o HA mapeia comandos específicos
        # open, close, stop
        self.options["attributes"].setdefault("state", "closed")

    def _on_command_received(self, client, userdata, msg) -> None:
        command = msg.payload.decode("utf-8").lower()  # open | close | stop
        print(f" garage [{self.name}] Comando de cobertura: {command}")

        if command == "open":
            self.updateState(new_state="open")
        elif command == "close":
            self.updateState(new_state="closed")
        elif command == "stop":
            print(f" garage [{self.name}] Movimento interrompido.")


class LockDevice(Device):
    """Fechaduras Eletrônicas."""

    domain = "lock"
    optimistic = False

    def apply_base_configuration(self) -> None:
        super().apply_base_configuration()
        self.options["attributes"].setdefault("state", "LOCKED")

    def _on_command_received(self, client, userdata, msg) -> None:
        command = msg.payload.decode(
            "utf-8"
        ).upper()  # LOCK | UNLOCK do Home Assistant
        print(f"🔒 [{self.name}] Tranca recebendo ordem de: {command}")

        if command == "LOCK":
            self.updateState(new_state="LOCKED")
        elif command == "UNLOCK":
            self.updateState(new_state="UNLOCKED")

class ButtonDevice(Device):
    """Botões/Gatilhos (Apenas recebem comando do HA para acionar algo)."""

    domain = "button"
    optimistic = False

    def apply_base_configuration(self) -> None:
        super().apply_base_configuration()
        # Botões não têm estado persistente no HA (não usam state_topic)
        self.removeConfiguration("state_topic")

    def updateState(self, new_state: Optional[Any] = None) -> None:
        """Sobrescreve para evitar que o botão tente publicar estados inválidos no MQTT."""
        # Botões não atualizam nem publicam estados, deixamos o método vazio (pass)
        pass

    def _on_command_received(self, client, userdata, msg) -> None:
        payload = msg.payload.decode("utf-8")
        print(f"🔔 [{self.name}] Botão pressionado via Home Assistant!")
        # Aqui é onde o seu código agiria para disparar uma ação física real.

class SwitchDevice(Device):
    """Interruptor simples (ON/OFF).

    Como a classe base Device já se comporta como um switch por padrão, basta
    mapear o domínio correto aqui.
    """

    domain = "switch"


class ClimateDevice(Device):
    """Dispositivo de Climatização (Ar Condicionado/Termostato)."""

    domain = "climate"
    optimistic = False

    def post_init(self) -> None:
        # Atributos padrão iniciais
        self.options["attributes"].setdefault("state", "off")
        self.options["attributes"].setdefault("temperature", 22.0)

        # Configurações específicas de Clima para o HA Discovery
        climate_configs = {
            "mode_cmd_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/mode/set",
            "mode_stat_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/mode/state",
            "temperature_command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/temp/set",
            "temperature_state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/temp/state",
            "modes": ["off", "cool", "heat", "fan_only"],
            "min_temp": 16,
            "max_temp": 30,
            "temp_step": 1,
        }

        # Remove tópicos genéricos da classe base
        self.removeConfiguration("command_topic")
        self.removeConfiguration("state_topic")

        self.options["configurations"].update(climate_configs)

    def modeCommandTopic(self) -> str:
        return self.getConfiguration("mode_cmd_topic", "")

    def modeStateTopic(self) -> str:
        return self.getConfiguration("mode_stat_topic", "")

    def tempCommandTopic(self) -> str:
        return self.getConfiguration("temperature_command_topic", "")

    def tempStateTopic(self) -> str:
        return self.getConfiguration("temperature_state_topic", "")

    def updateState(
        self,
        new_state: Optional[Any] = None,
        new_temp: Optional[float] = None,
    ) -> None:
        if new_state is not None:
            self.addAttribute("state", str(new_state).lower())
        if new_temp is not None:
            self.addAttribute("temperature", float(new_temp))

        # Envia as confirmações em tópicos separados conforme o HA espera
        self.service.publish(
            self.modeStateTopic(), str(self.getAttribute("state")), retain=True
        )
        self.service.publish(
            self.tempStateTopic(),
            str(self.getAttribute("temperature")),
            retain=True,
        )

    def setup(self) -> None:
        config_payload = self.options["configurations"].copy()
        config_payload.pop("discovery_topic", None)
        self.service.publish(self.discoveryTopic(), config_payload, retain=True)

        # Assina os dois tópicos de comando do clima
        if self.modeCommandTopic():
            self.service.subscribe(self.modeCommandTopic(), self._on_mode_received)
        if self.tempCommandTopic():
            self.service.subscribe(self.tempCommandTopic(), self._on_temp_received)

        avail_topic = self.getConfiguration("availability_topic")
        if avail_topic:
            self.service.publish(avail_topic, "online", retain=True)
        self.updateState()

    def _on_mode_received(self, client, userdata, msg) -> None:
        mode = msg.payload.decode("utf-8")
        print(f"❄️ [{self.name}] Alterar MODO para: {mode}")
        self.updateState(new_state=mode)

    def _on_temp_received(self, client, userdata, msg) -> None:
        temp_str = msg.payload.decode("utf-8")
        print(f"🌡️ [{self.name}] Alterar TEMPERATURA para: {temp_str}°C")
        try:
            self.updateState(new_state=None, new_temp=float(temp_str))
        except ValueError:
            print(f"[Erro] Temperatura inválida: {temp_str}")


class VacuumDevice(Device):
    """Aspirador de Pó Robô (MQTT Vacuum)."""

    domain = "vacuum"
    optimistic = False

    def post_init(self) -> None:
        # Atributos padrão (estados válidos do HA: cleaning, docked, paused, idle, returning, error)
        self.options["attributes"].setdefault("state", "docked")
        self.options["attributes"].setdefault("battery_level", 100)

        vacuum_configs = {
            "command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/command",
            "state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/state",
            # Lista de recursos que o robô suporta (enviar comandos do painel)
            "supported_features": [
                "start",
                "stop",
                "pause",
                "return_home",
                "status",
                "battery",
            ],
        }
        self.options["configurations"].update(vacuum_configs)

    def updateState(self, new_state: Optional[Any] = None) -> None:
        """Envia o estado do aspirador no formato JSON esperado pelo HA."""
        if new_state is not None:
            if isinstance(new_state, dict):
                if "state" in new_state:
                    self.addAttribute("state", new_state["state"])
                if "battery_level" in new_state:
                    self.addAttribute(
                        "battery_level", int(new_state["battery_level"])
                    )
            else:
                self.addAttribute("state", str(new_state).lower())

        # O Vacuum no HA lê um JSON com 'status' (ou 'state') e 'battery_level'
        payload_ha = {
            "state": self.getAttribute("state"),
            "battery_level": self.getAttribute("battery_level"),
        }
        self.service.publish(self.stateTopic(), payload_ha, retain=True)

    def _on_command_received(self, client, userdata, msg) -> None:
        command = msg.payload.decode("utf-8").lower()
        print(f"🧹 [{self.name}] Comando recebido: {command}")

        # Mapeia as ações disparadas pelos botões do Home Assistant
        if command == "start":
            self.updateState(new_state="cleaning")
        elif command == "stop" or command == "pause":
            self.updateState(new_state="paused")
        elif command == "return_home":
            self.updateState(new_state="returning")

class SirenDevice(Device):
    """Controle de Sirenes e Beepers."""

    domain = "siren"

    def apply_base_configuration(self) -> None:
        super().apply_base_configuration()
        # Estado inicial padrão da sirene (ON/OFF)
        self.options["attributes"].setdefault("state", "OFF")


class AlarmDevice(Device):
    """Painel de Controle de Alarme (Alarm Control Panel)."""

    domain = "alarm_control_panel"
    optimistic = False

    def post_init(self) -> None:
        # Estados válidos do HA: disarmed, armed_home, armed_away, armed_night, triggering, pending
        self.options["attributes"].setdefault("state", "disarmed")

        alarm_configs = {
            "command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/set",
            "state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/state",
            # Define se o alarme exige senha no Home Assistant para ser armado/desarmado
            # Modifique para 'true' se quiser que o teclado numérico apareça no HA
            "code_arm_required": False,
            "code_disarm_required": False,
            # Se code estiver ativo, você pode definir uma senha estática aqui (ex: "1234")
            # "code": "1234"
        }
        self.options["configurations"].update(alarm_configs)

    def _on_command_received(self, client, userdata, msg) -> None:
        command = msg.payload.decode("utf-8").upper()
        # O HA envia comandos como: ARM_HOME, ARM_AWAY, DISARM
        print(f"🚨 [{self.name}] Comando de segurança recebido: {command}")

        if command == "ARM_HOME":
            self.updateState(new_state="armed_home")
        elif command == "ARM_AWAY":
            self.updateState(new_state="armed_away")
        elif command == "DISARM":
            self.updateState(new_state="disarmed")


class DeviceTrackerDevice(Device):
    """Rastreador de Presença/Dispositivo (Device Tracker)."""

    domain = "device_tracker"
    optimistic = False

    def apply_base_configuration(self) -> None:
        super().apply_base_configuration()
        # Estados válidos padrão do HA: home, not_home
        self.options["attributes"].setdefault("state", "not_home")

        tracker_configs = {
            "state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/state",
            # Define o tipo de tracker para o ícone correto no HA (bluetooth, router, gps)
            "source_type": "router",
        }
        # Remove o command_topic porque a presença é enviada pelo dispositivo, não comandada pelo HA
        self.removeConfiguration("command_topic")

        self.options["configurations"].update(tracker_configs)


class MediaPlayerDevice(Device):
    """Controle de Mídia (TV, Caixa de Som, Soundbar)."""

    domain = "media_player"
    optimistic = False

    def post_init(self) -> None:
        # Atributos iniciais do player
        # Estados do HA: off, on, playing, paused, idle
        self.options["attributes"].setdefault("state", "off")
        self.options["attributes"].setdefault("volume_level", 0.5)  # De 0.0 a 1.0
        self.options["attributes"].setdefault("is_volume_muted", False)

        player_configs = {
            "command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/command",
            "state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/state",
            # Tópicos extras específicos do HA para receber valores analógicos deslizantes
            "volume_command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/volume/set",
            # Recursos visíveis no painel do HA
            "supported_features": [
                "play",
                "pause",
                "stop",
                "volume_set",
                "volume_mute",
                "turn_on",
                "turn_off",
            ],
        }
        self.options["configurations"].update(player_configs)

    def volumeCommandTopic(self) -> str:
        return self.getConfiguration("volume_command_topic", "")

    def updateState(self, new_state: Optional[Any] = None) -> None:
        """Monta o payload de estado adaptado para as propriedades do Media Player."""
        if new_state is not None:
            if isinstance(new_state, dict):
                if "state" in new_state:
                    self.addAttribute("state", new_state["state"])
                if "volume_level" in new_state:
                    self.addAttribute(
                        "volume_level", float(new_state["volume_level"])
                    )
                if "is_volume_muted" in new_state:
                    self.addAttribute(
                        "is_volume_muted", bool(new_state["is_volume_muted"])
                    )
            else:
                self.addAttribute("state", str(new_state).lower())

        # O Media Player no HA prefere receber suas propriedades unificadas em JSON
        payload_ha = {
            "state": self.getAttribute("state"),
            "volume_level": self.getAttribute("volume_level"),
            "is_volume_muted": self.getAttribute("is_volume_muted"),
        }
        self.service.publish(self.stateTopic(), payload_ha, retain=True)

    def setup(self) -> None:
        """Estende o setup para assinar também o tópico exclusivo de volume."""
        super().setup()
        if self.volumeCommandTopic():
            self.service.subscribe(
                self.volumeCommandTopic(), self._on_volume_received
            )

    def _on_command_received(self, client, userdata, msg) -> None:
        command = msg.payload.decode("utf-8").lower()
        print(f"🎬 [{self.name}] Comando de mídia recebido: {command}")

        if command == "turn_on":
            self.updateState(new_state="idle")
        elif command == "turn_off":
            self.updateState(new_state="off")
        elif command == "play":
            self.updateState(new_state="playing")
        elif command == "pause":
            self.updateState(new_state="paused")
        elif command == "stop":
            self.updateState(new_state="idle")
        elif command == "mute":
            # Inverte o estado atual do mute se receber o comando puro de alternância
            current_mute = self.getAttribute("is_volume_muted", False)
            self.updateState(new_state={"is_volume_muted": not current_mute})

    def _on_volume_received(self, client, userdata, msg) -> None:
        volume_str = msg.payload.decode("utf-8")
        print(f"🔊 [{self.name}] Ajustar volume para: {volume_str}")
        try:
            # O HA envia valores de volume de 0.0 a 1.0 (ex: 0.35 para 35%)
            self.updateState(new_state={"volume_level": float(volume_str)})
        except ValueError:
            print(f"[Erro] Volume inválido: {volume_str}")


class SelectDevice(Device):
    """Seletor de Opções (Dropdown Input Select).
    
    Útil para mudar modos de automação (ex: "Festa", "Cinema", "Trabalho").
    """
    domain = "select"
    optimistic = False

    def post_init(self) -> None:
        # Pega a lista de opções do arquivo de configuração ou deixa uma padrão
        self.options["configurations"].setdefault("options", ["Opção 1", "Opção 2"])
        self.options["attributes"].setdefault("state", self.getConfiguration("options")[0])

    def _on_command_received(self, client, userdata, msg) -> None:
        opcao_selecionada = msg.payload.decode("utf-8")
        print(f"🎛️ [{self.name}] Nova opção selecionada no HA: {opcao_selecionada}")
        
        if opcao_selecionada in self.getConfiguration("options"):
            self.updateState(new_state=opcao_selecionada)


class NumberDevice(Device):
    """Controle Deslizante Numérico (Slider / Input Number).
    
    Útil para definir variáveis como 'Tempo de tolerância do alarme' ou 'Volume do Bip'.
    """
    domain = "number"
    optimistic = False

    def post_init(self) -> None:
        self.options["attributes"].setdefault("state", 10.0)
        self.options["configurations"].setdefault("min", 0)
        self.options["configurations"].setdefault("max", 100)
        self.options["configurations"].setdefault("step", 1)

    def _on_command_received(self, client, userdata, msg) -> None:
        valor_str = msg.payload.decode("utf-8")
        print(f"🔢 [{self.name}] Slider movido para: {valor_str}")
        try:
            self.updateState(new_state=float(valor_str))
        except ValueError:
            pass


class HumidifierDevice(Device):
    """Controle de Umidificadores e Desumidificadores de Ar."""
    domain = "humidifier"
    optimistic = False

    def post_init(self) -> None:
        self.options["attributes"].setdefault("state", "off") # on / off
        self.options["attributes"].setdefault("humidity", 45)  # Alvo %
        
        humidifier_configs = {
            "mode_command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/mode/set",
            "mode_state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/mode/state",
            "target_humidity_command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/humidity/set",
            "target_humidity_state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/humidity/state",
            "modes": ["normal", "eco", "boost"],
            "min_humidity": 30,
            "max_humidity": 80
        }
        self.options["configurations"].update(humidifier_configs)

    def updateState(self, new_state: Optional[Any] = None, new_humidity: Optional[int] = None) -> None:
        if new_state is not None:
            self.addAttribute("state", str(new_state).lower())
        if new_humidity is not None:
            self.addAttribute("humidity", int(new_humidity))

        # Envia o liga/desliga e a umidade alvo em tópicos separados
        self.service.publish(self.stateTopic(), str(self.state()), retain=True)
        
        h_topic = self.getConfiguration("target_humidity_state_topic")
        if h_topic:
            self.service.publish(h_topic, str(self.getAttribute("humidity")), retain=True)

    def setup(self) -> None:
        super().setup()
        h_cmd = self.getConfiguration("target_humidity_command_topic")
        if h_cmd:
            self.service.subscribe(h_cmd, self._on_humidity_received)

    def _on_humidity_received(self, client, userdata, msg) -> None:
        h_str = msg.payload.decode("utf-8")
        print(f"💧 [{self.name}] Alterar umidade alvo para: {h_str}%")
        self.updateState(new_humidity=int(h_str))


class WaterHeaterDevice(Device):
    """Controle de Aquecedores de Água, Boilers e Banheiras de Hidromassagem."""
    domain = "water_heater"
    optimistic = False

    def post_init(self) -> None:
        self.options["attributes"].setdefault("state", "eco") # modo atual
        self.options["attributes"].setdefault("temperature", 45.0) # temperatura atual da água
        
        heater_configs = {
            "mode_command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/mode/set",
            "mode_state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/mode/state",
            "temperature_command_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/temp/set",
            "temperature_state_topic": f"{BASE_ROUTE}/{self.domain}/{self.id}/temp/state",
            "modes": ["off", "eco", "electric", "gas"],
            "min_temp": 30,
            "max_temp": 65
        }
        self.options["configurations"].update(heater_configs)

    def updateState(self, new_state: Optional[Any] = None, new_temp: Optional[float] = None) -> None:
        if new_state is not None:
            self.addAttribute("state", str(new_state).lower())
        if new_temp is not None:
            self.addAttribute("temperature", float(new_temp))

        # Publica estado e temperatura
        self.service.publish(self.getConfiguration("mode_state_topic"), str(self.state()), retain=True)
        self.service.publish(self.getConfiguration("temperature_state_topic"), str(self.getAttribute("temperature")), retain=True)

    def setup(self) -> None:
        config_payload = self.options["configurations"].copy()
        config_payload.pop("discovery_topic", None)
        self.service.publish(self.discoveryTopic(), config_payload, retain=True)

        self.service.subscribe(self.getConfiguration("mode_command_topic"), self._on_command_received)
        self.service.subscribe(self.getConfiguration("temperature_command_topic"), self._on_temp_received)

        avail_topic = self.getConfiguration("availability_topic")
        if avail_topic:
            self.service.publish(avail_topic, "online", retain=True)
        self.updateState()

    def _on_temp_received(self, client, userdata, msg) -> None:
        temp_str = msg.payload.decode("utf-8")
        print(f"🔥 [{self.name}] Ajustar temperatura do boiler para: {temp_str}°C")
        self.updateState(new_temp=float(temp_str))
