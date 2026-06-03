import json
from logging import log, logMultiprocessing
from .logger import logger

from typing import Any, Dict, Optional

BASE_ROUTE = "homeassistant"  # Ajuste conforme suas variáveis globais

class Device:
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        self.id: str = id
        self.domain: str = ""
        self.name: str = name or id.replace("_", " ").title()
        self.service: Any = service  # MQTTService
        
        # Estrutura isolada conforme o YAML
        self.options: Dict[str, Any] = options
        self.configurations: Dict[str, Any] = options.get("configurations", {})
        self.attributes: Dict[str, Any] = options.get("attributes", {})
        self.triggers: list = options.get("triggers", [])

        # Garante estado inicial padrão se omitido no YAML
        #if "state" not in self.attributes:
        #    self.attributes["state"] = "OFF"

    # --- Gerenciamento de Tópicos (Fora do Payload) ---
    def discovery_topic(self) -> str:
        return f"{BASE_ROUTE}/{self.domain}/{self.id}/config"

    def state_topic(self) -> str:
        return f"{BASE_ROUTE}/{self.domain}/{self.id}/state"

    def command_topic(self) -> str:
        return f"{BASE_ROUTE}/{self.domain}/{self.id}/set"

    def availability_topic(self) -> str:
        return f"{BASE_ROUTE}/{self.domain}/{self.id}/availability"

    # --- Contrato de Manipulação de Atributos Internos ---
    def add_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def remove_attribute(self, key: str) -> None:
        self.attributes.pop(key, None)

    def get_attribute(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    # --- Ciclo de Vida do MQTT ---
    def setup(self) -> None:
        """Executa o Discovery e se inscreve nos comandos recebidos."""
        # 1. Monta o payload de descoberta baseado estritamente nas configurações do YAML
        discovery_payload = {
            "name": self.name,
            "unique_id": self.id,
            "state_topic": self.state_topic(),
            "availability_topic": self.availability_topic(),
            "payload_available": "online",
            "payload_not_available": "offline"
        }
        
        # Se for um dispositivo que aceita comandos, injeta o command_topic
        if self.domain not in ["sensor", "binary_sensor"]:
            discovery_payload["command_topic"] = self.command_topic()

        # Mescla com as configurações específicas do HA declaradas no YAML (Ex: schema, brightness, device)
        discovery_payload.update(self.configurations)

        # 2. Publica o Discovery
        self.service.publish(self.discovery_topic(), discovery_payload, retain=True)

        # 3. Publica a disponibilidade online
        self.service.publish(self.availability_topic(), "online", retain=True)

        # 4. Se inscreve no canal de comandos vindos do Home Assistant
        if "command_topic" in discovery_payload:
            self.service.subscribe(self.command_topic(), self.on_message)

        # 5. Publica o estado inicial da aplicação
        self.update()

    def set_value(self, key: str, value: Any) -> None:
        """Altera um atributo interno da aplicação e sincroniza com o Home Assistant."""
        self.add_attribute(key, value)
        self.update()

    def update(self) -> None:
        """Publica o estado atual respeitando o formato do schema configurado."""
        is_json_schema = self.configurations.get("schema") == "json"

        if is_json_schema:
            # Envia o dicionário completo em formato JSON
            payload_ha = json.dumps(self.attributes)
        else:
            # Envia apenas a string pura "ON" ou "OFF"
            payload_ha = str(self.get_attribute("state", "OFF"))

        self.service.publish(self.state_topic(), payload_ha, retain=True)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Contrato do Paho MQTT. Será estendido pela classe filha."""
        pass

    def print_state(self):
        logger.info(f"[Device]: {self.domain}.{self.id} -> {self.attributes['state']}")

    def print_attributes(self):
        attr_str = json.dumps(self.attributes)
        logger.info(f"[Device]: {self.domain}.{self.id} -> {attr_str}")

### LIGHT
class Light(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "light"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

    def turn_on(self) -> None:
        """Liga a lâmpada mantendo seus atributos anteriores."""
        self.set_value("state", "ON")
        self.print_state()

    def turn_off(self) -> None:
        """Desliga a lâmpada."""
        self.set_value("state", "OFF")
        self.print_state()


    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Manipula as mensagens recebidas via Paho MQTT, aceitando JSON ou Texto Puro."""

        try:
            payload_str = msg.payload.decode("utf-8").strip()
            
            # 1. Verifica qual é o schema configurado para esta lâmpada
            is_json_schema = self.configurations.get("schema") == "json"

            if is_json_schema:
                data = json.loads(payload_str)

                if not isinstance(data, dict):
                    return

                logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {data}")

                if "state" in data:
                    self.add_attribute("state", str(data["state"]).upper())
                if "brightness" in data and self.configurations.get("brightness"):
                    self.add_attribute("brightness", int(data["brightness"]))
                if "color" in data:
                    self.add_attribute("color", data["color"])
                if "color_temp" in data:
                    self.add_attribute("color_temp", int(data["color_temp"]))

                logger.info(f"[Device]: {self.domain}.{self.id} -> {payload_str}")
            
            else:
                state_str = payload_str.upper()
                if state_str in ["ON", "OFF"]:
                    logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {state_str}")
                    self.add_attribute("state", state_str)
                    self.print_state()
                else:
                    return

            # 2. Sincroniza o novo estado de volta com o Home Assistant
            self.update()

        except json.JSONDecodeError as e:
            logger.error(f"Erro de JSON na lâmpada '{self.id}' (Esperava JSON devido ao schema): {e}")
        except (TypeError, ValueError) as e:
            logger.error(f"Erro ao processar payload na lâmpada '{self.id}': {e}")
    


class Switch(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "switch"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

    def turn_on(self) -> None:
        self.set_value("state", "ON")
        self.print_state()

    def turn_off(self) -> None:
        self.set_value("state", "OFF")
        self.print_state()

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8").strip().upper()
            if payload_str in ["ON", "OFF"]:
                logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {payload_str}")
                self.add_attribute("state", payload_str)
                self.print_state()
                self.update()

        except Exception as e:
            logger.error(f"Erro no switch '{self.id}': {e}")


class Climate(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "climate"
        
        # Garante que os atributos essenciais existam na memória
        if "mode" not in self.attributes: 
            self.attributes["mode"] = "off"
        if "temperature" not in self.attributes: 
            self.attributes["temperature"] = 22.0
        if "current_temperature" not in self.attributes: 
            self.attributes["current_temperature"] = 25.0

    def mode_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/mode/set"

    def temperature_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/temperature/set"

    def setup(self) -> None:
        # Configuração simplificada e direta. Removemos os templates complexos do Jinja
        # e deixamos o HA ler diretamente as chaves do JSON enviado.
        defaults = {
            "mode_command_topic": self.mode_command_topic(),
            "mode_state_topic": self.state_topic(),
            "mode_state_template": "{{ value_json.mode }}",
            
            "temperature_command_topic": self.temperature_command_topic(),
            "temperature_state_topic": self.state_topic(),
            "temperature_state_template": "{{ value_json.temperature }}",
            
            "current_temperature_topic": self.state_topic(),
            "current_temperature_template": "{{ value_json.current_temperature }}",
            
            "modes": ["off", "heat", "cool", "fan_only"]
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()
        self.service.subscribe(self.mode_command_topic(), self.on_mode_message)
        self.service.subscribe(self.temperature_command_topic(), self.on_temp_message)

    def update(self) -> None:
        """✨ TRATAMENTO ESPECIAL: Sobrescreve o update para garantir o envio do JSON limpo."""
        payload_data = {
            "mode": self.attributes.get("mode", "off"),
            "temperature": float(self.attributes.get("temperature", 22.0)),
            "current_temperature": float(self.attributes.get("current_temperature", 25.0))
        }
        # Transmite o JSON stringificado de forma idêntica ao que o HA espera ler
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        pass

    def on_mode_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Modo) -> {payload}")
            
            # Atualiza o atributo interno e força o envio da confirmação
            self.add_attribute("mode", payload)
            self.update() 
        except Exception as e:
            logger.error(f"Erro ao mudar modo do climate '{self.id}': {e}")

    def on_temp_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = msg.payload.decode("utf-8").strip()
            temp = float(payload)
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Temp Alvo) -> {temp}°C")
            
            # Atualiza o atributo interno e força o envio da confirmação
            self.add_attribute("temperature", temp)
            self.update()
        except Exception as e:
            logger.error(f"Erro ao setar temperatura do climate '{self.id}': {e}")


class Fan(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "fan"
        if "state" not in self.attributes: self.attributes["state"] = "OFF"
        if "percentage" not in self.attributes: self.attributes["percentage"] = 0

    def percentage_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/percentage/set"

    def setup(self) -> None:
        # Configura as chaves de leitura baseadas estritamente no nosso JSON payload
        if "percentage_command_topic" not in self.configurations:
            self.configurations["percentage_command_topic"] = self.percentage_command_topic()
            self.configurations["percentage_state_topic"] = self.state_topic()
            self.configurations["percentage_value_template"] = "{{ value_json.percentage }}"
            
            # Diz ao HA para buscar o estado liga/desliga dentro da chave .state do JSON
            self.configurations["state_topic"] = self.state_topic()
            self.configurations["state_value_template"] = "{{ value_json.state }}"
            
        super().setup()
        self.service.subscribe(self.percentage_command_topic(), self.on_percentage_message)

    def update(self) -> None:
        """✨ TRATAMENTO ESPECIAL: Garante o envio exclusivo do formato JSON esperado."""
        payload_data = {
            "state": str(self.attributes.get("state", "OFF")).upper(),
            "percentage": int(self.attributes.get("percentage", 0))
        }
        # Envia sempre o dicionário limpo estruturado como string JSON válida
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Trata o comando básico de Liga/Desliga vindo do HA."""
        try:
            payload = msg.payload.decode("utf-8").strip().upper()
            if payload in ["ON", "OFF"]:
                logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Power) -> {payload}")
                
                self.add_attribute("state", payload)
                if payload == "OFF":
                    self.add_attribute("percentage", 0)
                elif payload == "ON" and self.attributes.get("percentage", 0) == 0:
                    self.add_attribute("percentage", 33) # Liga na velocidade baixa se estava em zero
                
                self.update()
        except Exception as e:
            logger.error(f"Erro no power do fan '{self.id}': {e}")

    def on_percentage_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Trata a alteração do Slider de velocidade (0-100%)."""
        try:
            payload = msg.payload.decode("utf-8").strip()
            pct = int(payload)
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Speed) -> {pct}%")
            
            self.add_attribute("percentage", pct)
            self.add_attribute("state", "OFF" if pct == 0 else "ON")
            
            self.update()
        except Exception as e:
            logger.error(f"Erro na velocidade do fan '{self.id}': {e}")


class Sensor(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "sensor"

        if "state" not in self.attributes:
            self.attributes["state"] = "N/A"

    def simulate_topic(self) -> str:
        """Define o tópico de simulação: homeassistant/sensor/id/simulate"""
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        # Configura as propriedades do Discovery padrão do HA
        if "state_value_template" not in self.configurations:
            self.configurations["state_value_template"] = "{{ value_json.state }}"
            
        super().setup()
        
        # 📡 Se inscreve no tópico de simulação
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        # Continua ignorando os comandos normais do HA
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Injetor de dados de simulação via terminal."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            logger.info(f"[SIMULAÇÃO]: Sensor '{self.id}' injetado com -> {payload_str}")
            
            # Tenta converter para número (int/float) se aplicável, senão mantém string
            try:
                if "." in payload_str:
                    val = float(payload_str)
                else:
                    val = int(payload_str)
            except ValueError:
                val = payload_str
                
            self.add_attribute("state", val)
            self.update() # Envia para o HA ler o novo valor gerado
        except Exception as e:
            logger.error(f"Erro ao processar simulação no sensor '{self.id}': {e}")

class BinarySensor(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "binary_sensor"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

        self.configurations["schema"] = "json"

    def simulate_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        if "value_template" not in self.configurations:
            self.configurations["value_template"] = "{{ value_json.state }}"
            
        super().setup()
        
        # 📡 Se inscreve no tópico de simulação
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Injetor de estados binários (ON/OFF) via terminal."""
        try:
            payload_str = msg.payload.decode("utf-8").strip().upper()
            
            if payload_str in ["ON", "OFF"]:
                logger.info(f"[SIMULAÇÃO]: Binary Sensor '{self.id}' alterado para -> {payload_str}")
                self.add_attribute("state", payload_str)
                self.update()
            else:
                logger.warning(f"Payload de simulação inválido para binary_sensor: {payload_str}. Use ON ou OFF.")
        except Exception as e:
            logger.error(f"Erro ao processar simulação no binary_sensor '{self.id}': {e}")


class Energy(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "sensor"  # No HA MQTT Discovery, energy é uma subclasse de sensor
        if "state" not in self.attributes: self.attributes["state"] = 0.0  # kWh
        if "power" not in self.attributes: self.attributes["power"] = 0.0    # W

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        pass

class Cover(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "cover"

        if "state" not in self.attributes: self.attributes["state"] = "closed"
        if "position" not in self.attributes: self.attributes["position"] = 0

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8").strip().upper()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {payload_str}")
            
            if payload_str == "OPEN":
                self.add_attribute("state", "open")
                self.add_attribute("position", 100)
                self.print_attributes()
            elif payload_str == "CLOSE":
                self.add_attribute("state", "closed")
                self.add_attribute("position", 0)
                self.print_attributes()
            elif payload_str == "STOP":
                self.add_attribute("state", "stopped")
                self.print_attributes()
                
            self.update()
        except Exception as e:
            logger.error(f"Erro no cover '{self.id}': {e}")

    def open(self):
        self.add_attribute("state", "open")
        self.add_attribute("position", 100)
        self.print_attributes()
        self.update()

    def close(self):
        self.add_attribute("state", "closed")
        self.add_attribute("position", 0)
        self.print_attributes()
        self.update()

    def stop(self):
        self.add_attribute("state", "stopped")
        self.print_attributes()
        self.update()

class Lock(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "lock"

        if "state" not in self.attributes:
            self.attributes["state"] = "LOCKED"

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8").strip().upper()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {payload_str}")
            
            if payload_str in ["LOCK", "UNLOCK"]:
                # Traduz comando em estado estável do HA (Locked / Unlocked)
                target_state = "LOCKED" if payload_str == "LOCK" else "UNLOCKED"
                self.add_attribute("state", target_state)
                self.print_state()
                self.update()
        except Exception as e:
            logger.error(f"Erro no lock '{self.id}': {e}")

    def lock(self):
        if (self.get_attribute("state") == "LOCKED"):
            return

        self.set_value("state", "LOCKED")
        self.print_state()

    def unlock(self):
        if (self.get_attribute("state") == "UNLOCKED"):
            return

        self.set_value("state", "UNLOCKED")
        self.print_state()

class Button(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "button"

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {payload_str}")
            # Botões respondem instantaneamente a um pulso, sem guardar estado fixo interno.
            if hasattr(self, "on_press") and callable(getattr(self, "on_press")):
                self.on_press()

        except Exception as e:
            logger.error(f"Erro no button '{self.id}': {e}")

    def on_press(self):
        logger.info(f"[Device]: {self.domain}.{self.id} -> PRESSED")

class Vacuum(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "vacuum"
        self.configurations["schema"] = "json"

        if "state" not in self.attributes: self.attributes["state"] = "docked"
        if "battery_level" not in self.attributes: self.attributes["battery_level"] = 100


    def setup(self) -> None:
        # Define os recursos e mapeamentos que liberam os botões no painel do HA
        if "supported_features" not in self.configurations:
            self.configurations["supported_features"] = [
                "start", "pause", "stop", "return_home", "status"
            ]

            self.configurations["state_topic"] = self.state_topic()
            # Mapeia onde o HA vai ler a string de estado pura dentro do nosso JSON de atributos
            #self.configurations["state_template"] = "{{ value_json.state }}"
            #self.configurations["battery_level_topic"] = self.state_topic()
            #self.configurations["battery_level_template"] = "{{ value_json.battery_level }}"

        super().setup()

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Intercepta os comandos de ação enviados pelos botões do painel do HA."""
        try:
            payload = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Comando Vacuum) -> {payload}")
            
            # Máquina de estados básica de transição do aspirador robô
            if payload == "start":
                self.add_attribute("state", "cleaning")
            elif payload == "pause":
                self.add_attribute("state", "paused")
            elif payload == "stop":
                self.add_attribute("state", "idle")
            elif payload == "return_to_base":
                self.add_attribute("state", "returning")
                
            self.print_state()

            self.update()
        except Exception as e:
            logger.error(f"Erro ao processar comando no vacuum '{self.id}': {e}")

    def start(self):
        self.set_value("state", "cleaning")
        self.print_state()

    def pause(self):
        self.set_value("state", "paused")
        self.print_state()

    def stop(self):
        self.set_value("state", "idle")
        self.print_state()

    def return_home(self):
        self.set_value("state", "returning")
        self.print_state()

    def print_state(self):
        logger.info(f"[Device]: {self.domain}.{self.id} -> {self.attributes['state']}")

class Siren(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "siren"

        self.configurations["schema"] = "json"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            decoded_payload = msg.payload.decode("utf-8").strip() #.upper()
            payload = json.loads(decoded_payload)
            payload_str = payload.get("state", "")

            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {payload_str}")

            if payload_str in ["ON", "OFF"]:
                self.add_attribute("state", payload_str)
                self.print_state()
                self.update()
        except Exception as e:
            logger.error(f"Erro na siren '{self.id}': {e}")

    def turn_on(self):
        self.set_value("state", "ON")
        self.print_state()

    def turn_off(self):
        self.set_value("state", "OFF")
        self.print_state()

class Alarm(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "alarm_control_panel"
        if "state" not in self.attributes:
            self.attributes["state"] = "disarmed"

    def setup(self) -> None:
        # Configurações obrigatórias para o painel de alarme do HA
        if "state_topic" not in self.configurations:
            self.configurations["state_topic"] = self.state_topic()
            self.configurations["state_template"] = "{{ value_json.state }}"
            
            # ✨ Remove a obrigatoriedade de digitar código/senha na interface do HA
            self.configurations["code_arm_required"] = False
            self.configurations["code_disarm_required"] = False
            
        super().setup()
    
    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> Solicitado: {payload_str}")
            
            # Mapeamento padrão de comandos recebidos para estados do HA
            alarm_states = {
                "disarm": "disarmed", "arm_home": "armed_home", 
                "arm_away": "armed_away", "arm_night": "armed_night"
            }
            if payload_str in alarm_states:
                self.add_attribute("state", alarm_states[payload_str])
                self.update()
        except Exception as e:
            logger.error(f"Erro no alarme '{self.id}': {e}")

class DeviceTracker(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "device_tracker"
        if "state" not in self.attributes:
            self.attributes["state"] = "not_home"

    def simulate_topic(self) -> str:
        """Define o canal de simulação: homeassistant/device_tracker/id/simulate"""
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        # Configurações do Discovery para monitoramento de estado textual puro
        if "state_topic" not in self.configurations:
            self.configurations["state_topic"] = self.state_topic()
            
            # Mapeia explicitamente as strings que o HA deve interpretar
            self.configurations["payload_home"] = "home"
            self.configurations["payload_not_home"] = "not_home"
            
        super().setup()
        
        # 📡 Escuta a rota de simulação dedicada
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)

    def update(self) -> None:
        """✨ TRATAMENTO ESPECIAL: Envia apenas a string pura de estado.
        
        Diferente de outros dispositivos que usam JSON, o device_tracker de estado 
        estático do HA prefere receber o payload textual bruto no state_topic.
        """
        state_str = str(self.attributes.get("state", "not_home")).lower()
        self.service.publish(self.state_topic(), state_str, retain=True)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        # Ignora comandos normais do HA
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Muda o estado de presença baseado no comando do terminal."""
        try:
            payload_str = msg.payload.decode("utf-8").strip().lower()
            
            if payload_str in ["home", "not_home"]:
                logger.info(f"[SIMULAÇÃO PRESENÇA]: Tracker '{self.id}' alterado para -> {payload_str}")
                self.add_attribute("state", payload_str)
                self.update()
            else:
                logger.warning(f"Payload inválido para device_tracker. Use apenas 'home' ou 'not_home'.")
        except Exception as e:
            logger.error(f"Erro ao processar simulação no device_tracker '{self.id}': {e}")


class Humidifier(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "humidifier"
        if "state" not in self.attributes: 
            self.attributes["state"] = "OFF"
        if "target_humidity" not in self.attributes: 
            self.attributes["target_humidity"] = 40

    def target_humidity_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/target_humidity/set"

    def target_humidity_state_topic(self) -> str:
        """✨ NOVO: Tópico exclusivo para o estado da umidade, evitando conflito no HA."""
        return f"homeassistant/{self.domain}/{self.id}/target_humidity/state"

    def setup(self) -> None:
        # Chaves corrigidas seguindo estritamente a documentação MQTT Humidifier do HA
        if "target_humidity_command_topic" not in self.configurations:
            self.configurations["target_humidity_command_topic"] = self.target_humidity_command_topic()
            
            # Aponta para o tópico exclusivo de umidade e usa a chave de template CORRETA
            self.configurations["target_humidity_state_topic"] = self.target_humidity_state_topic()
            self.configurations["target_humidity_state_template"] = "{{ value_json.target_humidity }}"
            
            # Configuração do Power (Liga/Desliga) no tópico principal
            self.configurations["state_topic"] = self.state_topic()
            self.configurations["state_value_template"] = "{{ value_json.state }}"
            
        super().setup()
        
        self.service.subscribe(self.command_topic(), self.on_message)
        self.service.subscribe(self.target_humidity_command_topic(), self.on_humidity_message)

    def update(self) -> None:
        """✨ TRATAMENTO ESPECIAL: Publica nos dois tópicos de forma isolada."""
        payload_power = {
            "state": str(self.attributes.get("state", "OFF")).upper()
        }
        payload_humidity = {
            "target_humidity": int(self.attributes.get("target_humidity", 40))
        }
        
        # Envia o estado de energia para o state_topic
        self.service.publish(self.state_topic(), json.dumps(payload_power), retain=True)
        
        # Envia o estado do slider para o target_humidity_state_topic
        self.service.publish(self.target_humidity_state_topic(), json.dumps(payload_humidity), retain=True)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = msg.payload.decode("utf-8").strip().upper()
            if payload in ["ON", "OFF"]:
                logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Power) -> {payload}")
                self.add_attribute("state", payload)
                self.update()
        except Exception as e:
            logger.error(f"Erro no controle de energia do humidifier '{self.id}': {e}")

    def on_humidity_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = msg.payload.decode("utf-8").strip()
            humidity_val = int(payload)
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Umidade Alvo) -> {humidity_val}%")
            
            self.add_attribute("target_humidity", humidity_val)
            self.update()
        except Exception as e:
            logger.error(f"Erro ao mudar umidade alvo no humidifier '{self.id}': {e}")

class WaterHeater(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "water_heater"
        # Atributos internos padrão esperados pelo HA
        #if "state" not in self.attributes: 
        #    self.attributes["state"] = "eco"  # No water_heater, o estado principal é o modo
        if "operation_mode" not in self.attributes: 
            self.attributes["operation_mode"] =  "eco"  # No water_heater, o estado principal é o modo
        if "temperature" not in self.attributes: 
            self.attributes["temperature"] = 45.0
        if "current_temperature" not in self.attributes: 
            self.attributes["current_temperature"] = 39.0

    def mode_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/mode/set"

    def temperature_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/temperature/set"

    def setup(self) -> None:
        # Chaves oficiais da documentação MQTT Water Heater do Home Assistant
        defaults = {
            "mode_command_topic": self.mode_command_topic(),
            "mode_state_topic": self.state_topic(),
            "mode_state_template": "{{ value_json.state }}",
            
            "temperature_command_topic": self.temperature_command_topic(),
            "temperature_state_topic": self.state_topic(),
            "temperature_state_template": "{{ value_json.temperature }}",
            
            "current_temperature_topic": self.state_topic(),
            "current_temperature_template": "{{ value_json.current_temperature }}",
            
            # Lista de modos que aparecerão no seletor do painel do HA
            "modes": ["off", "eco", "electric", "gas", "heat_pump", "high_demand", "performance"]
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()
        
        # 📡 Se inscreve nos tópicos específicos criados para o HA interagir
        self.service.subscribe(self.mode_command_topic(), self.on_mode_message)
        self.service.subscribe(self.temperature_command_topic(), self.on_temp_message)

    def update(self) -> None:
        """✨ TRATAMENTO ESPECIAL: Envia o payload JSON perfeitamente limpo."""
        payload_data = {
            #"state": str(self.attributes.get("state", "eco")).lower(),
            "state": str(self.attributes.get("operation_mode", "eco")).lower(),
            "temperature": float(self.attributes.get("temperature", 45.0)),
            "current_temperature": float(self.attributes.get("current_temperature", 39.0))
        }
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        # Desativado pois o water_heater usa sub-tópicos granulares mapeados abaixo
        pass

    def on_mode_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Captura a mudança de modo (ex: ECO, GAS, OFF) enviada pelo HA."""
        try:
            payload = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Modo) -> {payload}")
            
            #self.add_attribute("state", payload)
            self.add_attribute("operation_mode", payload)
            self.update() # Devolve o JSON confirmando para o botão fixar na tela
        except Exception as e:
            logger.error(f"Erro ao mudar modo do water_heater '{self.id}': {e}")

    def on_temp_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Captura o ajuste de temperatura do termostato enviado pelo HA."""
        try:
            payload = msg.payload.decode("utf-8").strip()
            temp = float(payload)
            logger.info(f"[HA IN]: '{self.domain}.{self.id}' (Temp Alvo) -> {temp}°C")
            
            self.add_attribute("temperature", temp)
            self.update() # Devolve a confirmação de temperatura para fixar o slider
        except Exception as e:
            logger.error(f"Erro ao mudar temperatura do water_heater '{self.id}': {e}")

    def set_temperature(self):
        pass

    def turn_away_mode_on(self):
        pass

    def turn_away_mode_off(self):
        pass

    def set_operation_mode(self):
        pass

    def turn_on(self):
        pass

    def turn_off(self):
        pass


#class MediaPlayer(Device):
#    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
#        super().__init__(id, name, service, options)
#        self.domain = "media_player"
#        if "state" not in self.attributes: self.attributes["state"] = "off"
#        if "volume_level" not in self.attributes: self.attributes["volume_level"] = 0.5
#
#    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
#        try:
#            payload_str = msg.payload.decode("utf-8").strip()
#            if payload_str.startswith("{"):
#                data = json.loads(payload_str)
#                if "state" in data: self.add_attribute("state", str(data["state"]).lower())
#                if "volume_level" in data: self.add_attribute("volume_level", float(data["volume_level"]))
#            else:
#                cmd = payload_str.lower()
#                if cmd in ["off", "on", "play", "pause"]:
#                    self.add_attribute("state", "idle" if cmd == "on" else cmd)
#            
#            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> {self.attributes}")
#            self.update()
#        except Exception as e:
#            logger.error(f"Erro no media_player '{self.id}': {e}")

#class Select(Device):
#    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
#        super().__init__(id, name, service, options)
#        self.domain = "select"
#        if "state" not in self.attributes:
#            self.attributes["state"] = "Opção 1"
#
#    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
#        try:
#            payload_str = msg.payload.decode("utf-8").strip()
#            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> Selecionado: {payload_str}")
#            self.add_attribute("state", payload_str)
#            self.update()
#        except Exception as e:
#            logger.error(f"Erro no select '{self.id}': {e}")

#class Number(Device):
#    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
#        super().__init__(id, name, service, options)
#        self.domain = "number"
#        if "state" not in self.attributes:
#            self.attributes["state"] = 0.0
#
#    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
#        try:
#            payload_str = msg.payload.decode("utf-8").strip()
#            logger.info(f"[HA IN]: '{self.domain}.{self.id}' -> Novo Valor: {payload_str}")
#            val = float(payload_str)
#            self.add_attribute("state", int(val) if val.is_integer() else val)
#            self.update()
#        except Exception as e:
#            logger.error(f"Erro no number '{self.id}': {e}")
#
