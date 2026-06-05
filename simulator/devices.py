from os import device_encoding
import threading
import subprocess
import json
import time
from typing import Any, Dict, List
from .logger import logger
from jinja2 import Template

BASE_ROUTE = "homeassistant"  # Ajuste conforme suas variáveis globais

class Device:
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        self.id: str = id
        self.domain: str = ""
        self.name: str = name or id.replace("_", " ").title()
        self.service: Any = service
        
        # Isolated configuration data
        self.options: Dict[str, Any] = options
        self.configurations: Dict[str, Any] = options.get("configurations", {})
        self.attributes: Dict[str, Any] = options.get("attributes", {})
        self.variables: Dict[str, Any] = options.get("variables", {})
        self.adapters_config: List = options.get("adapters", [])
        
        # State tracking layers
        self._previous_attributes: Dict[str, Any] = {}
        self._previous_variables: Dict[str, Any] = {}

    # --- MQTT Topic Factory ---
    def discovery_topic(self) -> str: return f"{BASE_ROUTE}/{self.domain}/{self.id}/config"
    def state_topic(self) -> str:     return f"{BASE_ROUTE}/{self.domain}/{self.id}/state"
    def command_topic(self) -> str:   return f"{BASE_ROUTE}/{self.domain}/{self.id}/set"
    def availability_topic(self) -> str: return f"{BASE_ROUTE}/{self.domain}/{self.id}/availability"

    # --- Property/Attribute State Handlers ---
    def add_attribute(self, key: str, value: Any) -> None:
        current_value = self.attributes.get(key)
        if current_value != value:
            self._previous_attributes[key] = current_value
            self.attributes[key] = value

    def set_variable(self, key: str, value: Any) -> None:
        current_value = self.variables.get(key)
        if current_value != value:
            self._previous_variables[key] = current_value
            self.variables[key] = value
            self.update()

    def device_info(self) -> Dict[str, Any] | None:
        return self.configurations.get("device", { "identifiers": [] })

    def get_property(self, key: str) -> Any:
        return self.attributes[key] if key in self.attributes else self.variables.get(key)

    def get_previous_property(self, key: str) -> Any:
        return self._previous_attributes.get(key) if key in self.attributes else self._previous_variables.get(key)

    def is_attr(self, key: str, value: Any) -> bool: return self.get_property(key) == value
    def get_attr(self, key: str) -> Any:             return self.get_property(key)
    def remove_attribute(self, key: str) -> None:    self.attributes.pop(key, None)

    def is_changed(self, key: str, to_value: Any) -> bool:
        current = self.get_property(key)
        previous = self.get_previous_property(key)
        return previous is not None and current == to_value and previous != to_value

    # --- Lifecycle & Telemetry Engine ---
    def setup(self) -> None:
        """Publishes discovery payload, availability and subscribes to commands."""

        if not self.configurations.get("device", False):
            self.configurations["device"] = {
                "name": self.name,
                "model": "Unknown",
                "manufacturer": "Unknown",
                "identifiers": [f"{self.domain}.{self.id}"]
            }

        discovery_payload = {
            "name": self.name,
            "unique_id": f"{self.domain}.{self.id}",
            "state_topic": self.state_topic(),
            "availability_topic": self.availability_topic(),
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": json.dumps(self.device_info())
        }
        
        if self.domain not in ["sensor", "binary_sensor"]:
            discovery_payload["command_topic"] = self.command_topic()

        discovery_payload.update(self.configurations)

        self.service.publish(self.discovery_topic(), discovery_payload, retain=True)
        self.service.publish(self.availability_topic(), "online", retain=True)

        if "command_topic" in discovery_payload:
            self.service.subscribe(self.command_topic(), self.on_message)

        self.update()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Broadcasts current state via MQTT and processes reactive adapters."""

        is_json = self.configurations.get("schema") == "json"
        attrs = payload if payload else self.attributes
        payload_ha = json.dumps(attrs) if is_json else str(attrs.get("state", "OFF"))

        self.service.publish(self.state_topic(), payload_ha, retain=True)

        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def execute_action(self, action_name: str, payload: Any = None) -> None:
        """Dynamically invokes entity methods passing arguments if accepted."""
        method = getattr(self, action_name, None)
        if method and callable(method):
            try:
                logger.info(f"[ACTION] Executing '{action_name}' on '{self.domain}.{self.id}'")
                try:
                    method(payload)
                except TypeError:
                    method()
            except Exception as e:
                logger.error(f"[EXECUTE ERROR] Method '{action_name}' failed on '{self.id}': {e}", exc_info=True)
        else:
            logger.warning(f"[ACTION WARNING] Device '{self.domain}.{self.id}' missing method '{action_name}'")

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """MQTT input interface. Implemented by subclasses."""
        pass

    def print_state(self) -> None:
        is_json = self.attributes.get("schema", False)

        payload = json.dumps(self.attributes) if is_json else self.attributes.get("state") or self.attributes.get("value", "N/A")
        logger.info(f"[STATE] {self.domain}.{self.id} -> {payload}")

    # --- Reactive Logic Core (Adapters) ---
    def _change_adapter(self, adapter: Dict[str, Any]) -> None:
        prop = adapter.get("property", "")
        current_value = self.get_property(prop)
        previous_value = self.get_previous_property(prop)

        # 1. Controle de ciclo de boot original (ajustado para não engolir o estado)
        if previous_value is None:
            if adapter.get("to") is not None:
                # Se o estado atual do boot já for diferente do 'to', bloqueia.
                # Se for igual, deixa passar para o primeiro ciclo refletir o estado correto.
                if str(current_value).strip().upper() != str(adapter.get("to")).strip().upper():
                    return
            previous_value = current_value

        # 2. Avalia a regra de disparo baseada na mudança real de estado
        state_changed = (current_value != previous_value)
        
        # 3. VERIFICAÇÃO DO 'TO' (O pulo do gato que faltava na lógica original)
        target_to = adapter.get("to")
        if target_to is not None:
            # Só valida o gatilho se o valor atual for IGUAL ao 'to' do YAML
            is_at_target = (str(current_value).strip().upper() == str(target_to).strip().upper())
            should_trigger = state_changed and is_at_target
        else:
            # Se não tem 'to' no YAML, se comporta como um "on_change" puro
            should_trigger = state_changed

        # 4. Execução do fluxo de ações
        if should_trigger:
            action_type = adapter.get("action_type", "device") 
            raw_data = adapter.get("data")
            
            # Só processa o payload se existir dados/templates declarados no YAML
            if raw_data is not None:
                action_payload = self._parse_adapter_data(raw_data, current_value)
            else:
                action_payload = None

            if action_type == "device":
                target_id = adapter.get("target_id")
                target_action = adapter.get("target_action")
                
                registries = getattr(self, "device_registries", {})
                target_device = registries.get(target_id)
                
                if target_device and target_action:
                    # 🌟 CENÁRIO A: É o 'execute_action' dinâmico (depende obrigatoriamente do Jinja)
                    if target_action == "execute_action":
                        # Se o Jinja retornou vazio (condicional falsa), aí sim nós abortamos
                        if action_payload is None or str(action_payload).strip() == "":
                            return
                        
                        clean_action = str(action_payload).strip()
                        target_device.execute_action(clean_action)
                    
                    # 🌟 CENÁRIO B: É um método direto (ex: 'turn_off', 'set_brightness')
                    else:
                        # Se não tem 'data' no YAML (caso do turn_off), executa puramente sem argumentos
                        if raw_data is None:
                            target_device.execute_action(target_action)
                        else:
                            target_device.execute_action(target_action, payload=action_payload)
                else:
                    logger.warning(f"[ADAPTER WARNING] Target entity [{target_id}] unreachable for action [{target_action}].")

            elif action_type == "mqtt":
                if topic := adapter.get("topic"):
                    # Se não houver data, envia o valor atual do próprio dispositivo
                    payload_to_send = action_payload if raw_data is not None else current_value
                    logger.info(f"[ADAPTER MQTT] Publishing to '{topic}': {payload_to_send}")
                    self.service.publish(topic, str(payload_to_send), retain=False)

            elif action_type == "script":
                if raw_command := adapter.get("command"):
                    exec_command = self._parse_adapter_data(raw_command, current_value)
                    import subprocess
                    logger.info(f"[ADAPTER SCRIPT] Spawning: {exec_command}")
                    subprocess.Popen(exec_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    def _get_global_attribute(self, device_glob_id: str, attribute_key: str) -> Any:
        global_map = getattr(self, "device_registries", {})
        target_device = global_map.get(device_glob_id)
        if target_device:
            return target_device.attributes.get(attribute_key)
        logger.warning(f"[JINJA ERROR] Global entity '{device_glob_id}' not found.")
        return None

    def _parse_adapter_data(self, data_field: Any, current_value: Any) -> Any:
        if data_field is None or not isinstance(data_field, str):
            return data_field
            
        try:
            template = Template(data_field)
            this_context = {**self.attributes, **self.variables}
            rendered_str = template.render(value=current_value, attr=self._get_global_attribute, this=this_context)
            
            # Smart data-type conversion (Handles negative/positive ints, floats and booleans)
            try:
                if "." in rendered_str: return float(rendered_str)
                return int(rendered_str)
            except ValueError:
                if rendered_str.lower() == "true": return True
                if rendered_str.lower() == "false": return False
                return rendered_str
                
        except Exception as e:
            logger.error(f"[JINJA ERROR] Failed parsing template '{data_field}': {e}")
            return current_value

########################################
# LIGHT
########################################
class Light(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "light"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

        if "brightness" in self.attributes:
            self.configurations["brightness"] = True
            self.configurations["schema"] = "json"

    def turn_on(self) -> None:
        """Turns the light ON preserving or resetting base attributes."""
        self.add_attribute("state", "ON")
        self.update()
        self.print_state()

    def turn_off(self) -> None:
        """Turns the light OFF."""
        self.add_attribute("state", "OFF")
        self.update()
        self.print_state()

    def set_brightness(self, brightness: Any) -> None:
        """Sets brightness level and automatically ensures the light is statefully ON."""
        try:
            target_brightness = int(float(brightness))
            self.add_attribute("brightness", target_brightness)
            # Home Assistant behavior: setting brightness implies turning the light ON
            self.add_attribute("state", "ON")
            self.update()
            self.print_state()
        except (ValueError, TypeError) as e:
            logger.error(f"[LIGHT ERROR] Invalid brightness value '{brightness}' on '{self.id}': {e}")

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handles incoming MQTT messages supporting text commands or complex JSON schemas."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            is_json_schema = self.configurations.get("schema") == "json"

            if is_json_schema:
                data = json.loads(payload_str)
                if not isinstance(data, dict):
                    return

                logger.info(f"[HA IN] {self.domain}.{self.id} -> {data}")

                # Process stateful transitions within the incoming JSON object
                if "state" in data:
                    self.add_attribute("state", str(data["state"]).upper())
                if "brightness" in data and self.configurations.get("brightness"):
                    self.add_attribute("brightness", int(data["brightness"]))
                if "color" in data:
                    self.add_attribute("color", data["color"])
                if "color_temp" in data:
                    self.add_attribute("color_temp", int(data["color_temp"]))
                
                # Ensure changing parameters implicitly manages standard behavior
                if self.attributes.get("brightness", 0) > 0 and "state" not in data:
                    self.add_attribute("state", "ON")
            else:
                state_upper = payload_str.upper()
                if state_upper in ["ON", "OFF"]:
                    logger.info(f"[HA IN] {self.domain}.{self.id} -> {state_upper}")
                    self.add_attribute("state", state_upper)
                else:
                    return

            # Synchronize state mutations and trigger active entity adapters
            self.update()

        except json.JSONDecodeError as e:
            logger.error(f"[MQTT ERROR] Failed parsing JSON schema on '{self.id}': {e}")
        except Exception as e:
            logger.error(f"[MQTT ERROR] Processing payload runtime exception on '{self.id}': {e}")

########################################
# SWITCH
########################################
class Switch(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "switch"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

    def turn_on(self) -> None:
        """Turns the switch state statefully ON."""
        self.add_attribute("state", "ON")
        self.print_state()
        self.update()

    def turn_off(self) -> None:
        """Turns the switch state statefully OFF."""
        self.add_attribute("state", "OFF")
        self.print_state()
        self.update()

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handles incoming binary MQTT payloads routing actions to operational interfaces."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            payload_upper = payload_str.upper()
            
            if payload_upper in ["ON", "OFF"]:
                logger.info(f"[HA IN] {self.domain}.{self.id} -> {payload_upper}")
                
                if payload_upper == "ON":
                    self.turn_on()
                else:
                    self.turn_off()
            else:
                logger.warning(f"[SWITCH WARNING] Unsupported payload payload on '{self.id}': {payload_str}")
                
        except Exception as e:
            logger.error(f"[SWITCH ERROR] Failed processing routing loop exception on '{self.id}': {e}")

########################################
# NUMBER
########################################
class Number(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "number"
        
        if "value" not in self.attributes:
            self.attributes["value"] = 0.0

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Publishes the raw numerical input state, bypassing the default 'OFF' string telemetry."""
        is_json = self.configurations.get("schema") == "json"
        payload_ha = json.dumps(self.attributes) if is_json else str(self.attributes.get("value", 0.0))

        self.service.publish(self.state_topic(), payload_ha, retain=True)

        # Triggers active reactive adapters (Jinja engine hooks mapped in devices.yaml)
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handles numeric adjustments coming from Home Assistant input fields."""
        payload_str = ""

        try:
            payload_str = msg.payload.decode("utf-8").strip()
            logger.info(f"[HA IN] {self.domain}.{self.id} -> {payload_str}")
            
            val = float(payload_str)
            final_val = int(val) if val.is_integer() else val
            
            self.set_value(final_val)
            
        except ValueError:
            logger.warning(f"[NUMBER WARNING] Non-numeric payload received on '{self.id}': {payload_str}")
        except Exception as e:
            logger.error(f"[NUMBER ERROR] Failed processing input payload on '{self.id}': {e}")

    def set_value(self, value: Any) -> None:
        """Sets internal entity value safely applying historical context arrays."""
        try:
            val = float(value)
            final_val = int(val) if val.is_integer() else val
            
            self.add_attribute("value", final_val)
            self.print_state()
            self.update()
        except (ValueError, TypeError) as e:
            logger.error(f"[NUMBER ERROR] Type mismatch casting value '{value}' on '{self.id}': {e}")

########################################
# COVER
########################################
class Cover(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "cover"

        # Default state attributes
        if "state" not in self.attributes:
            self.add_attribute("state", "closed")
        if "position" not in self.attributes:
            self.add_attribute("position", 0)
        if "tilt_position" not in self.attributes:
            self.add_attribute("tilt_position", 0)

        # Thread concurrency control for physical simulation
        self._motion_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def setup(self) -> None:
        if "device_class" not in self.configurations:
            self.configurations["device_class"] = None

        # Inject additional position command topic required by HA Cover component
        set_pos_topic = f"homeassistant/{self.domain}/{self.id}/set_pos"
        self.service.subscribe(set_pos_topic, self.on_message)

        super().setup()

    def position_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/position"

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Publishes precise numerical position before delegating state broadcast to base."""
        current_position = str(self.attributes.get("position", 0))
        self.service.publish(self.position_topic(), current_position, retain=True)
        super().update()

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes text routing state commands or numeric positional targets."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            payload_upper = payload_str.upper()
            
            logger.info(f"[HA IN] {self.domain}.{self.id} -> {payload_str}")
            
            if payload_upper == "OPEN":
                self.open_cover()
            elif payload_upper == "CLOSE":
                self.close_cover()
            elif payload_upper == "STOP":
                self.stop_cover()
            else:
                try:
                    # Safe cascade casting handles potential '45.0' formatted strings
                    target_pos = int(float(payload_str))
                    self.set_cover_position(target_pos)
                except ValueError:
                    logger.warning(f"[COVER WARNING] Invalid payload payload on '{self.id}': {payload_str}")
                    
        except Exception as e:
            logger.error(f"[COVER ERROR] Failed routing MQTT message on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def open_cover(self) -> None:
        self._start_motion(target_position=100, moving_state="opening")

    def close_cover(self) -> None:
        self._start_motion(target_position=0, moving_state="closing")

    def stop_cover(self) -> None:
        """Gracefully halts active background animation threads."""
        if self._motion_thread and self._motion_thread.is_alive():
            logger.info(f"[MOTION] Halting thread runner on '{self.id}'")
            self._stop_event.set()
            self._motion_thread.join()
            
            current_pos = self.attributes.get("position", 0)
            final_state = "closed" if current_pos == 0 else "open"
            
            self._previous_attributes = self.attributes.copy()
            self.attributes["state"] = final_state
            self.update()

    def set_cover_position(self, target_position: Any) -> None:
        """Evaluates positional changes to fire corresponding engine step directions."""
        try:
            target_pos = max(0, min(100, int(target_position)))
            current_pos = self.attributes.get("position", 0)
            
            if target_pos > current_pos:
                self._start_motion(target_position=target_pos, moving_state="opening")
            elif target_pos < current_pos:
                self._start_motion(target_position=target_pos, moving_state="closing")
        except Exception as e:
            logger.error(f"[COVER ERROR] Parameter exception setting position on '{self.id}': {e}")

    # --- Background Simulation Engine ---
    def _start_motion(self, target_position: int, moving_state: str) -> None:
        """Handles fast-inversion safety checks over running threads before spawning."""
        if self._motion_thread and self._motion_thread.is_alive():
            self._stop_event.set()
            self._motion_thread.join()

        self._stop_event.clear()
        self._motion_thread = threading.Thread(
            target=self._animate_cover, 
            args=(target_position, moving_state),
            daemon=True
        )
        self._motion_thread.start()

    def _animate_cover(self, target_position: int, moving_state: str) -> None:
        current_pos = self.attributes.get("position", 0)
        if current_pos == target_position:
            return

        logger.info(f"[MOTION] '{self.id}' started moving to {target_position}%")

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = moving_state
        self.update()

        config_step = int(self.variables.get("step", 5))
        config_delay = float(self.variables.get("delay", 0.5))
        step = config_step if target_position > current_pos else -config_step

        while current_pos != target_position:
            if self._stop_event.is_set():
                return

            time.sleep(config_delay)
            current_pos += step
            
            # Boundary protections preventing step overshoots
            if (step > 0 and current_pos > target_position) or (step < 0 and current_pos < target_position):
                current_pos = target_position

            self._previous_attributes = self.attributes.copy()
            self.attributes["position"] = current_pos

            logger.info(f"[MOTION] {self.id} -> {current_pos}")
            self.update()

        final_state = "closed" if current_pos == 0 else "open"
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = final_state
        logger.info(f"[MOTION] '{self.id}' target reached. State consolidated: {final_state}")
        self.update()


######################################
# CLIMATE
######################################
class Climate(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "climate"
        
        # Ensure mandatory baseline telemetry state attributes exist in memory
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
        # Simplified discovery keys mapped against Home Assistant MQTT Climate expectations
        defaults = {
            "temperature_unit": "C",  # 🌟 ISSO REALIZA A MUDANÇA PARA CELSIUS
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

        # Fires base class discovery publishing flow
        super().setup()
        
        # Map specific multiplexed state listeners required by the climate architecture
        self.service.subscribe(self.mode_command_topic(), self.on_mode_message)
        self.service.subscribe(self.temperature_command_topic(), self.on_temp_message)

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts consolidated JSON multi-state payloads to HA."""
        payload_data = {
            "mode": self.attributes.get("mode", "off"),
            "temperature": float(self.attributes.get("temperature", 22.0)),
            "current_temperature": float(self.attributes.get("current_temperature", 25.0))
        }
        
        # Publish packed atomic telemetry string
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Trigger reactive adapter evaluation pipeline (Crucial for multi-entity automation)
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Fallback overridden loop preventing interface errors from base class."""
        pass

    def on_mode_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes incoming operational mode command streams from the MQTT broker."""
        try:
            payload = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN] {self.domain}.{self.id} (Mode) -> {payload}")
            self.set_hvac_mode(payload)
        except Exception as e:
            logger.error(f"[CLIMATE ERROR] Failed processing mode queue payload on '{self.id}': {e}")

    def on_temp_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes incoming target temperature setting command streams from the MQTT broker."""
        try:
            payload = msg.payload.decode("utf-8").strip()
            logger.info(f"[HA IN] {self.domain}.{self.id} (Target Temp) -> {payload}°C")
            self.set_temperature(payload)
        except Exception as e:
            logger.error(f"[CLIMATE ERROR] Failed processing target thermal payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def set_hvac_mode(self, mode: str) -> None:
        """Updates internal operational HVAC mode statefully."""
        clean_mode = str(mode).strip().lower()
        supported_modes = self.configurations.get("modes", ["off"])
        
        if clean_mode in supported_modes:
            self.add_attribute("mode", clean_mode)
            self.print_state()
            self.update()
        else:
            logger.warning(f"[CLIMATE WARNING] Attempted to set unsupported mode '{clean_mode}' on '{self.id}'")

    def set_temperature(self, temperature: Any) -> None:
        """Updates targeted heating/cooling setpoint limits statefully with precision rounding."""
        try:
            # 🌟 O PULO DO GATO: Arredonda para 1 casa decimal para matar o '15.5555555'
            target_temp = round(float(temperature), 1)
            
            # Se o valor for inteiro (ex: 22.0), mantém visualmente limpo como int (ex: 22)
            if target_temp.is_integer():
                target_temp = int(target_temp)
            
            self._previous_attributes = self.attributes.copy()
            self.attributes["temperature"] = target_temp
            self.print_state()
            self.update()
        except (ValueError, TypeError) as e:
            logger.error(f"[CLIMATE ERROR] Invalid target temperature format '{temperature}' on '{self.id}': {e}")


    def turn_off(self) -> None:
        """Standard shortcut to turn off the climate entity, mapping to hvac mode."""
        logger.info(f"[CLIMATE] Powering off interface via standard shortcut on '{self.id}'")
        self.set_hvac_mode("off")

    def turn_on(self) -> None:
        """Standard shortcut to turn on the climate entity, defaulting to cool mode."""
        logger.info(f"[CLIMATE] Powering on interface via standard shortcut on '{self.id}'")
        # Se já estiver em algum modo ligado, mantém. Se estiver off, força 'cool'
        current_mode = self.attributes.get("mode", "off")
        if current_mode == "off":
            self.set_hvac_mode("cool")
        else:
            self.set_hvac_mode(current_mode)

    def print_state(self) -> None:
        """Overridden log viewer to properly serialize the climate JSON state in the CLI."""
        payload_data = {
            "mode": self.attributes.get("mode", "off"),
            "temperature": self.attributes.get("temperature", 22.0),
            "current_temperature": self.attributes.get("current_temperature", 25.0)
        }
        logger.info(f"[STATE] {self.domain}.{self.id} -> {json.dumps(payload_data)}")


    def set_current_temperature(self, current_temperature: Any) -> None:
        """Simulates ambient sensor temperature variations."""
        try:
            ambient_temp = float(current_temperature)
            self.add_attribute("current_temperature", ambient_temp)
            self.update()
        except (ValueError, TypeError) as e:
            logger.error(f"[CLIMATE ERROR] Invalid current temperature sensor cast '{current_temperature}' on '{self.id}': {e}")

 
########################################
# FAN
########################################
class Fan(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "fan"
        
        # Ensure mandatory baseline dictionary telemetry keys exist in memory
        if "state" not in self.attributes: 
            self.attributes["state"] = "OFF"
        if "percentage" not in self.attributes: 
            self.attributes["percentage"] = 0

    def percentage_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/percentage/set"

    def setup(self) -> None:
        # Configuration setup targeted strictly at Home Assistant MQTT Fan specifications
        defaults = {
            "percentage_command_topic": self.percentage_command_topic(),
            "percentage_state_topic": self.state_topic(),
            "percentage_value_template": "{{ value_json.percentage }}",
            
            "state_topic": self.state_topic(),
            "state_value_template": "{{ value_json.state }}",
            "command_topic": self.command_topic()  # Reuses base state /set topic for basic ON/OFF
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        # Triggers core registration discovery publishing flow
        super().setup()
        
        # Map specific multiplexed state listeners required by the Fan architecture
        self.service.subscribe(self.percentage_command_topic(), self.on_percentage_message)

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts consolidated JSON multi-state payloads to HA."""
        payload_data = {
            "state": str(self.attributes.get("state", "OFF")).upper(),
            "percentage": int(self.attributes.get("percentage", 0))
        }
        
        # Transmit clean atomic JSON string to the state topic
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Trigger reactive adapter evaluation pipeline (Crucial for multi-entity automation)
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes core basic ON/OFF power command streams from the MQTT broker."""
        try:
            payload = msg.payload.decode("utf-8").strip().upper()
            if payload in ["ON", "OFF"]:
                logger.info(f"[HA IN] {self.domain}.{self.id} (Power) -> {payload}")
                if payload == "ON":
                    self.turn_on()
                else:
                    self.turn_off()
        except Exception as e:
            logger.error(f"[FAN ERROR] Failed processing power payload on '{self.id}': {e}")

    def on_percentage_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes slider-driven speed variation streams (0-100%) from the MQTT broker."""
        try:
            payload = msg.payload.decode("utf-8").strip()
            pct = int(payload)
            logger.info(f"[HA IN] {self.domain}.{self.id} (Speed) -> {pct}%")
            self.set_percentage(pct)
        except Exception as e:
            logger.error(f"[FAN ERROR] Failed processing speed scale payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def turn_on(self) -> None:
        """Statefully turns the fan entity ON, defaulting speed parameters if stalled."""
        self._previous_attributes = self.attributes.copy()
        
        self.attributes["state"] = "ON"
        # If fan was dead stopped (0%), force a baseline slow rotation speed (e.g., 33%)
        if int(self.attributes.get("percentage", 0)) == 0:
            self.attributes["percentage"] = 33
            
        self.print_state()
        self.update()

    def turn_off(self) -> None:
        """Statefully powers down the fan entity and clears rotational percentage."""
        self._previous_attributes = self.attributes.copy()
        
        self.attributes["state"] = "OFF"
        self.attributes["percentage"] = 0
        
        self.print_state()
        self.update()

    def set_percentage(self, percentage: Any) -> None:
        """Explicitly sets the speed percentage boundary mapping power states accordingly."""
        try:
            pct = int(percentage)
            # Boundary clamp safety guardrail (0 to 100)
            pct = max(0, min(100, pct))
            
            self._previous_attributes = self.attributes.copy()
            self.attributes["percentage"] = pct
            self.attributes["state"] = "OFF" if pct == 0 else "ON"
            
            self.print_state()
            self.update()
        except (ValueError, TypeError) as e:
            logger.error(f"[FAN ERROR] Invalid speed step conversion logic target '{percentage}' on '{self.id}': {e}")

    def print_state(self, include_attributes: bool = True) -> None:
        """Overridden log viewer to properly serialize the fan JSON state in the CLI."""
        payload_data = {
            "state": self.attributes.get("state", "OFF"),
            "percentage": self.attributes.get("percentage", 0)
        }
        logger.info(f"[STATE] {self.domain}.{self.id} -> {json.dumps(payload_data)}")


###########################
# SENSOR
##########################
class Sensor(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "sensor"

        if "state" not in self.attributes:
            self.attributes["state"] = "N/A"

    def simulate_topic(self) -> str:
        """Defines simulation gateway topic: homeassistant/sensor/id/simulate"""
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        # Standard configuration layout enforcing atomic JSON deserialization inside HA
        if "state_value_template" not in self.configurations:
            self.configurations["state_value_template"] = "{{ value_json.state }}"
            
        super().setup()
        
        # Subscribe to simulation pipeline injection topic
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts consolidated telemetry data via JSON packages."""
        payload_data = {
            "state": self.attributes.get("state", "N/A")
        }
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Telemetry entities disregard default Home Assistant inbound switch commands."""
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handles numeric or text simulation updates directly injected from the MQTT broker."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            logger.info(f"[SIMULATION] Sensor '{self.id}' raw input -> {payload_str}")
            
            # Smart casting conversion: attempts numerical float/int parsing before fallback to string
            try:
                if "." in payload_str:
                    val = float(payload_str)
                else:
                    val = int(payload_str)
            except ValueError:
                val = payload_str
                
            self.set_state(val)
        except Exception as e:
            logger.error(f"[SENSOR ERROR] Failed parsing simulation payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def set_state(self, value: Any) -> None:
        """Updates sensor state while properly archiving history logs."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = value
        self.update()
        self.print_state()

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> {self.attributes.get('state')}")


###########################
# BINARY SENSOR
##########################
class BinarySensor(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "binary_sensor"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

    def simulate_topic(self) -> str:
        """Defines simulation gateway topic: homeassistant/binary_sensor/id/simulate"""
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        # Binary sensors expect state templates to parse 'ON'/'OFF' flags natively inside HA
        if "value_template" not in self.configurations:
            self.configurations["value_template"] = "{{ value_json.state }}"
            
        super().setup()
        
        # Subscribe to simulation pipeline injection topic
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts binary state configuration via JSON packages."""
        payload_data = {
            "state": str(self.attributes.get("state", "OFF")).upper()
        }
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Telemetry entities disregard default Home Assistant inbound switch commands."""
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handles boolean ON/OFF simulation updates injected directly from the MQTT broker."""
        try:
            payload_str = msg.payload.decode("utf-8").strip().upper()
            
            if payload_str in ["ON", "OFF"]:
                logger.info(f"[SIMULATION] Binary Sensor '{self.id}' raw input -> {payload_str}")
                if payload_str == "ON":
                    self.turn_on()
                else:
                    self.turn_off()
            else:
                logger.warning(f"[SENSOR WARNING] Invalid payload '{payload_str}' for binary_sensor '{self.id}'. Use ON/OFF.")
        except Exception as e:
            logger.error(f"[SENSOR ERROR] Failed parsing binary simulation payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def turn_on(self) -> None:
        """Sets binary sensor value statefully to ON."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "ON"
        self.update()
        self.print_state()

    def turn_off(self) -> None:
        """Sets binary sensor value statefully to OFF."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "OFF"
        self.update()
        self.print_state()

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> {self.attributes.get('state')}")


################################
# ENERGY
###############################
class Energy(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        # In Home Assistant MQTT Discovery, energy monitoring components are subclasses of 'sensor'
        self.domain = "sensor"
        
        if "state" not in self.attributes: 
            self.attributes["state"] = 0.0  # Accumulated Energy (kWh)
        if "power" not in self.attributes: 
            self.attributes["power"] = 0.0  # Instantaneous Power Consumption (W)

    def simulate_topic(self) -> str:
        """Defines simulation gateway topic: homeassistant/sensor/id/simulate"""
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        """Publishes dedicated distinct MQTT Discovery topics for both metrics."""
        
        # Metadados de Hardware do Dispositivo Pai (Wrapper raiz)
        info = {
            "name": self.name,
            "model": "Energy Meter Wrapper",
            "manufacturer": "Python Engine",
            "identifiers": [f"{self.domain}.{self.id}"]
        }

        # Vínculo puro por ID para as outras entidades pegarem carona no mesmo dispositivo
        identifiers = { "identifiers": info["identifiers"] }

        if not self.configurations.get("device", False):
            self.configurations["device"] = info

        # 1. Configuração do Sensor de Energia Acumulada (kWh)
        energy_config = {
            "name": f"{self.name} Energy",
            "unique_id": f"{self.domain}.{self.id}_energy",
            "state_topic": self.state_topic(),
            "value_template": "{{ value_json.state }}",
            "device_class": "energy",
            "state_class": "total_increasing",
            "unit_of_measurement": "kWh",
            "device": info
        }
        
        # 2. Configuração do Sensor de Potência Instantânea (W)
        power_config = {
            "name": f"{self.name} Power",
            "unique_id": f"{self.domain}.{self.id}_power",
            "state_topic": self.state_topic(),
            "value_template": "{{ value_json.power }}",
            "device_class": "power",
            "state_class": "measurement",
            "unit_of_measurement": "W",
            "device": identifiers
        }

        # Publica o Discovery do sensor de kWh
        energy_discovery_topic = f"homeassistant/sensor/{self.id}_energy/config"
        self.service.publish(energy_discovery_topic, json.dumps(energy_config), retain=True)
        
        # Publica o Discovery do sensor de Watts
        power_discovery_topic = f"homeassistant/sensor/{self.id}_power/config"
        self.service.publish(power_discovery_topic, json.dumps(power_config), retain=True)

        # Se inscreve no tópico de simulação para escutar os comandos do terminal
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)
        #logger.info(f"[ENERGY SETUP] Multi-sensor discovery deployed for '{self.id}'")

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts consolidated power/energy JSON packages to HA."""
        payload_data = {
            "state": round(float(self.attributes.get("state", 0.0)), 2),
            "power": round(float(self.attributes.get("power", 0.0)), 1)
        }
        
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Telemetry entities disregard default Home Assistant inbound switch commands."""
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes complex comma-separated terminal simulation payloads (e.g., 'power,energy')."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            logger.info(f"[SIMULATION] Energy Monitor '{self.id}' raw input -> '{payload_str}'")
            
            # Expects comma separated injection values (e.g: "1500,432.15" -> 1500W, 432.15 kWh)
            if "," in payload_str:
                power_part, energy_part = payload_str.split(",")
                
                self._previous_attributes = self.attributes.copy()
                self.attributes["power"] = float(power_part.strip())
                self.attributes["state"] = float(energy_part.strip())
                self.print_state()
                self.update()
            else:
                # Fallback: if single numeric value is supplied, assume it maps to instant Power (W)
                self.set_power(payload_str)
                
        except Exception as e:
            logger.error(f"[ENERGY ERROR] Failed processing simulation payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def set_power(self, watts: Any) -> None:
        """Updates immediate real-time electrical power load statefully."""
        try:
            self._previous_attributes = self.attributes.copy()
            self.attributes["power"] = float(watts)
            self.print_state()
            self.update()
        except (ValueError, TypeError) as e:
            logger.error(f"[ENERGY ERROR] Invalid power consumption format '{watts}' on '{self.id}': {e}")

    def set_energy(self, kwh: Any) -> None:
        """Updates cumulative totalized energy metrics statefully."""
        try:
            self._previous_attributes = self.attributes.copy()
            self.attributes["state"] = float(kwh)
            self.print_state()
            self.update()
        except (ValueError, TypeError) as e:
            logger.error(f"[ENERGY ERROR] Invalid accumulated energy format '{kwh}' on '{self.id}': {e}")

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        p_load = self.attributes.get("power", 0.0)
        e_total = self.attributes.get("state", 0.0)
        logger.info(f"[STATE] {self.id} -> Power: {p_load}W | Total: {e_total}kWh")


##########################
#LOCK
##########################
class Lock(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "lock"

        if "state" not in self.attributes:
            self.attributes["state"] = "LOCKED"

    def setup(self) -> None:
        # Home Assistant MQTT Lock configuration mappings
        defaults = {
            "command_topic": self.command_topic(),
            "state_topic": self.state_topic(),
            "value_template": "{{ value_json.state }}",
            # Explicitly states which payload strings represent which lock state
            "payload_lock": "LOCK",
            "payload_unlock": "UNLOCK",
            "payload_open": "OPEN",
            "state_locked": "LOCKED",
            "state_unlocked": "UNLOCKED"
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts current lock state via JSON packages."""
        payload_data = {
            "state": str(self.attributes.get("state", "LOCKED")).upper()
        }
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes incoming state shift actions dispatched by Home Assistant."""
        try:
            payload_str = msg.payload.decode("utf-8").strip().upper()
            logger.info(f"[HA IN] {self.domain}.{self.id} -> {payload_str}")
            
            if payload_str == "LOCK":
                self.lock()
            elif payload_str == "UNLOCK":
                self.unlock()
            elif payload_str == "OPEN":
                self.open()

        except Exception as e:
            logger.error(f"[LOCK ERROR] Failed processing lock action queue on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def lock(self) -> None:
        """Statefully secures the lock mechanism."""
        if self.attributes.get("state") == "LOCKED":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "LOCKED"
        self.print_state()
        self.update()

    def unlock(self) -> None:
        """Statefully releases the lock mechanism deadbolt."""
        if self.attributes.get("state") == "UNLOCKED":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "UNLOCKED"
        self.print_state()
        self.update()

    def open(self) -> None:
        """Triggers latch/spring release mechanism if supported."""
        logger.info(f"[LOCK] Actuating latch pull on '{self.id}'")
        
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "UNLOCKED"
        self.print_state()
        self.update()

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> {self.attributes.get('state')}")


##########################
# BUTTON
##########################
class Button(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "button"
        
        # Stateless devices don't hold persistent telemetry, but we track 
        # a transient memory state to feed internal reactive adapters.
        self.attributes["state"] = ""

    def setup(self) -> None:
        # Home Assistant MQTT Button configuration discovery payloads
        defaults = {
            "command_topic": self.command_topic(),
            "payload_press": "PRESS"
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Buttons are stateless and do not broadcast telemetry updates back to HA."""
        pass

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes incoming activation pulses dispatched from Home Assistant UI."""
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            logger.info(f"[HA IN] {self.domain}.{self.id} -> {payload_str}")
            
            # Fire the press workflow execution sequence
            self.press()

        except Exception as e:
            logger.error(f"[BUTTON ERROR] Failed executing button action on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def press(self) -> None:
        """Triggers a transient state shift to fire internal cross-device adapters."""
        logger.info(f"[ACTION] Button '{self.id}' execution triggered")
        
        # 🌟 O PULO DO GATO PARA ACIONAR O ADAPTER:
        # Criamos uma mudança artificial de estado de "vazio" para "PRESSED"
        self._previous_attributes = {"state": ""}
        self.attributes["state"] = "PRESSED"
        
        # Imprime o log de sucesso no console
        self.print_state()
        
        # Varre os adapters do devices.yaml procurando regras para este botão
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)
                
        # Reseta o estado interno para o repouso sem disparar novos gatilhos
        self.attributes["state"] = ""

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> PRESSED")

########################
# VACUUM
########################
class Vacuum(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "vacuum"
        self.configurations["schema"] = "json"

        if "state" not in self.attributes: 
            self.attributes["state"] = "docked"
        if "battery_level" not in self.attributes: 
            self.attributes["battery_level"] = 100

    def setup(self) -> None:
        # Define device capabilities and mapping flags to activate UI actions in HA
        if "supported_features" not in self.configurations:
            self.configurations["supported_features"] = [
                "start", "pause", "stop", "return_home", "status"
            ]

            self.configurations["state_topic"] = self.state_topic()
            self.configurations["state_template"] = "{{ value_json.state }}"
            self.configurations["battery_level_topic"] = self.state_topic()
            self.configurations["battery_level_template"] = "{{ value_json.battery_level }}"

        super().setup()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts current vacuum state via JSON packages."""
        payload_data = {
            "state": str(self.attributes.get("state", "docked")).lower(),
            "battery_level": int(self.attributes.get("battery_level", 100))
        }
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Intercepts inbound hardware commands transmitted from Home Assistant buttons."""
        try:
            payload = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN] {self.domain}.{self.id} (Command) -> {payload}")
            
            if payload == "start":
                self.start()
            elif payload == "pause":
                self.pause()
            elif payload == "stop":
                self.stop()
            elif payload in ["return_to_base", "return_home"]:
                self.return_to_base()
            elif payload == "on":
                self.turn_on()
            elif payload == "off":
                self.turn_off()

        except Exception as e:
            logger.error(f"[VACUUM ERROR] Failed processing operation payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def start(self) -> None:
        """Statefully commands the vacuum runner to initiate a cleaning loop."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "cleaning"
        self.update()
        self.print_state()

    def pause(self) -> None:
        """Statefully halts active deployment keeping the current map track context."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "paused"
        self.update()
        self.print_state()

    def stop(self) -> None:
        """Aborts operational routines and shifts device into an idle standstill profile."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "idle"
        self.update()
        self.print_state()

    def return_to_base(self) -> None:
        """Intercepts automation patterns routing hardware blocks back to home docks."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "returning"
        self.update()
        self.print_state()

    def turn_on(self) -> None:
        """Fallback power compatibility mode translating 'ON' toggles straight to start."""
        self.start()

    def turn_off(self) -> None:
        """Fallback power compatibility mode routing hardware blocks back to home docks."""
        self.return_to_base()

    def toggle(self) -> None:
        """Toggles operational state context profiles."""
        if self.attributes.get("state") in ["cleaning", "returning"]:
            self.turn_off()
        else:
            self.turn_on()

    def start_pause(self) -> None:
        """Flips back and forth between active sweep routing or paused positions."""
        if self.attributes.get("state") == "cleaning":
            self.pause()
        else:
            self.start()

    def set_battery(self, level: Any) -> None:
        """Simulates internal energy capacity drainage logs directly inside the terminal."""
        try:
            val = int(level)
            val = max(0, min(100, val))
            
            self._previous_attributes = self.attributes.copy()
            self.attributes["battery_level"] = val
            
            # Automatically transitions state if battery is completely depleted
            if val == 0:
                self.attributes["state"] = "error"
                
            self.update()
            self.print_state()
        except (ValueError, TypeError) as e:
            logger.error(f"[VACUUM ERROR] Invalid battery entry format '{level}' on '{self.id}': {e}")

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        status = self.attributes.get("state", "docked")
        batt = self.attributes.get("battery_level", 100)
        logger.info(f"[STATE] {self.domain}.{self.id} -> State: {status} | Battery: {batt}%")


#####################
# SIREN
#####################
class Siren(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "siren"
        self.configurations["schema"] = "json"

        if "state" not in self.attributes:
            self.attributes["state"] = "OFF"

    def setup(self) -> None:
        # Home Assistant MQTT Siren JSON schema configurations
        defaults = {
            "command_topic": self.command_topic(),
            "state_topic": self.state_topic(),
            "state_value_template": "{{ value_json.state }}"
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts current siren state via JSON packages."""
        payload_data = {
            "state": str(self.attributes.get("state", "OFF")).upper()
        }
        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes incoming activation JSON payloads dispatched from Home Assistant."""
        try:
            decoded_payload = msg.payload.decode("utf-8").strip()
            payload = json.loads(decoded_payload)
            payload_str = str(payload.get("state", "")).upper()

            logger.info(f"[HA IN] {self.domain}.{self.id} -> {payload_str}")

            if payload_str == "ON":
                self.turn_on()
            elif payload_str == "OFF":
                self.turn_off()
                
        except Exception as e:
            logger.error(f"[SIREN ERROR] Failed processing inbound message on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def turn_on(self) -> None:
        """Statefully activates the siren output."""
        if self.attributes.get("state") == "ON":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "ON"
        self.update()
        self.print_state()

    def turn_off(self) -> None:
        """Statefully deactivates the siren output."""
        if self.attributes.get("state") == "OFF":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "OFF"
        self.update()
        self.print_state()

    def toggle(self) -> None:
        """Toggles the current acoustic alert state configuration."""
        self.turn_on() if self.attributes.get("state") == "OFF" else self.turn_off()

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> {self.attributes.get('state')}")


#######################
# ALARM
######################
class Alarm(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "alarm_control_panel"
        
        if "state" not in self.attributes:
            self.attributes["state"] = "disarmed"

    def setup(self) -> None:
        # Core mandatory parameters matching Home Assistant MQTT Alarm Control Panel specifications
        defaults = {
            "command_topic": self.command_topic(),
            "state_topic": self.state_topic(),
            #"state_template": "{{ value_json.state }}",
            
            # Removes code input requirements globally inside the Home Assistant UI card
            "code_arm_required": False,
            "code_disarm_required": False
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts current alarm panel state via JSON packages."""
        #payload_data = {
        #    "state": str(self.attributes.get("state", "disarmed")).lower()
        #}

        #self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        payload_data = str(self.attributes.get("state", "disarmed")).lower()
        self.service.publish(self.state_topic(), payload_data, retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Intercepts inbound arm/disarm actions dispatched by Home Assistant panel buttons."""
        try:
            payload_str = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN] {self.domain}.{self.id} -> Requested Action: '{payload_str}'")
            
            # Map native incoming MQTT commands directly to target core methods
            alarm_states = {
                "disarm": self.alarm_disarm,
                "arm_home": self.alarm_arm_home, 
                "arm_away": self.alarm_arm_away,
                "arm_night": self.alarm_arm_night,
                "arm_vacation": self.alarm_arm_vacation,
                "arm_custom_bypass": self.alarm_arm_custom_bypass
            }

            if payload_str in alarm_states:
                alarm_states[payload_str]()
            else:
                logger.warning(f"[ALARM WARNING] Unsupported action request payload '{payload_str}' received.")

        except Exception as e:
            logger.error(f"[ALARM ERROR] Failed processing action command stream on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def alarm_arm_away(self) -> None:
        """Statefully flags the alarm entity as completely armed (Away mode)."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "armed_away"
        self.print_state()
        self.update()

    def alarm_arm_custom_bypass(self) -> None:
        """Statefully flags the alarm entity as armed bypassing specific zones manually."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "armed_custom_bypass"
        self.print_state()
        self.update()

    def alarm_arm_home(self) -> None:
        """Statefully flags the alarm entity as armed with perimeter safety (Home mode)."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "armed_home"
        self.print_state()
        self.update()
        
    def alarm_arm_night(self) -> None:
        """Statefully flags the alarm entity as armed under sleeping parameters (Night mode)."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "armed_night"
        self.print_state()
        self.update()

    def alarm_arm_vacation(self) -> None:
        """Statefully flags the alarm entity as armed under long-term absence parameters (Vacation mode)."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "armed_vacation"
        self.print_state()
        self.update()

    def alarm_disarm(self) -> None:
        """Statefully resets the alarm entity back to an unmonitored safe clearance state."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "disarmed"
        self.print_state()
        self.update()
        
    def trigger(self) -> None:
        """Forces immediate 'triggered' siren-tripped state loop if intrusion vectors break."""
        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "triggered"
        self.print_state()
        self.update()

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> {self.attributes.get('state')}")


#####################
# DEVICE TRACKER
####################
class DeviceTracker(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "device_tracker"
        
        if "state" not in self.attributes:
            self.attributes["state"] = "not_home"

    def simulate_topic(self) -> str:
        """Defines simulation gateway topic: homeassistant/device_tracker/id/simulate"""
        return f"homeassistant/{self.domain}/{self.id}/simulate"

    def setup(self) -> None:
        # Core configuration layout for raw text state monitoring
        if "state_topic" not in self.configurations:
            self.configurations["state_topic"] = self.state_topic()
            
            # Explicitly maps expected text payloads inside Home Assistant engine
            self.configurations["payload_home"] = "home"
            self.configurations["payload_not_home"] = "not_home"
            
        super().setup()
        
        # Subscribe to simulation pipeline injection topic
        self.service.subscribe(self.simulate_topic(), self.on_simulate_message)
        
        # Force initial state broadcast on startup to prevent 'unknown' cards
        self.update()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Publishes the raw state string directly to HA (No JSON wrapping)."""
        state_str = str(self.attributes.get("state", "not_home")).lower()
        self.service.publish(self.state_topic(), state_str, retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Inbound commands from HA are disregarded since trackers are telemetry injectors."""
        pass

    def on_simulate_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handles presence state shifting directly from custom MQTT terminal injectors."""
        try:
            payload_str = msg.payload.decode("utf-8").strip().lower()
            
            if payload_str in ["home", "not_home"]:
                logger.info(f"[SIMULATION] Tracker '{self.id}' raw input -> '{payload_str}'")
                if payload_str == "home":
                    self.see_home()
                else:
                    self.see_not_home()
            else:
                logger.warning(f"[TRACKER WARNING] Invalid payload '{payload_str}' for device_tracker. Use 'home' or 'not_home'.")
        except Exception as e:
            logger.error(f"[TRACKER ERROR] Failed parsing simulation payload on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def see_home(self) -> None:
        """Statefully marks the tracked device profile as Home."""
        if self.attributes.get("state") == "home":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "home"
        self.update()
        self.print_state()

    def see_not_home(self) -> None:
        """Statefully marks the tracked device profile as Away (not_home)."""
        if self.attributes.get("state") == "not_home":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "not_home"
        self.update()
        self.print_state()

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        logger.info(f"[STATE] {self.domain}.{self.id} -> {self.attributes.get('state')}")


#################
# HUMIDIFIER
##################
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
        """Isolated topic dedicated strictly to transmitting current setpoint targets."""
        return f"homeassistant/{self.domain}/{self.id}/target_humidity/state"

    def setup(self) -> None:
        if "device_class" not in self.configurations:
            self.configurations["device_class"] = "humidifier"

        # Map distinct structural parameters aligned with HA MQTT Humidifier specs
        if "target_humidity_command_topic" not in self.configurations:
            self.configurations["target_humidity_command_topic"] = self.target_humidity_command_topic()
            self.configurations["target_humidity_state_topic"] = self.target_humidity_state_topic()
            self.configurations["target_humidity_state_template"] = "{{ value_json.target_humidity }}"
            
            # Base power management endpoints configuration mappings
            self.configurations["state_topic"] = self.state_topic()
            self.configurations["state_value_template"] = "{{ value_json.state }}"
            
        super().setup()
        
        # Explicit subscription bindings to capture targeted inbound MQTT commands
        self.service.subscribe(self.command_topic(), self.on_message)
        self.service.subscribe(self.target_humidity_command_topic(), self.on_humidity_message)
        
        # Broadcast current baseline statuses immediately on startup
        self.update()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializes and broadcasts power state and humidity targets to isolated topics."""
        payload_power = {
            "state": str(self.attributes.get("state", "OFF")).upper()
        }
        payload_humidity = {
            "target_humidity": int(self.attributes.get("target_humidity", 40))
        }
        
        # Publish structural telemetry blocks independently to avoid collisions
        self.service.publish(self.state_topic(), json.dumps(payload_power), retain=True)
        self.service.publish(self.target_humidity_state_topic(), json.dumps(payload_humidity), retain=True)

        # Evaluate reactive adapters for automation script integration
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes incoming primary power states transmitted by Home Assistant UI toggles."""
        try:
            payload = msg.payload.decode("utf-8").strip().upper()
            logger.info(f"[HA IN] {self.domain}.{self.id} (Power Request) -> '{payload}'")
            
            if payload == "ON":
                self.turn_on()
            elif payload == "OFF":
                self.turn_off()
                
        except Exception as e:
            logger.error(f"[HUMIDIFIER ERROR] Failed parsing power message on '{self.id}': {e}")

    def on_humidity_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Processes target slider adjustments transmitted directly from Home Assistant UI."""
        try:
            payload = msg.payload.decode("utf-8").strip()
            humidity_val = int(payload)
            logger.info(f"[HA IN] {self.domain}.{self.id} (Humidity Request) -> {humidity_val}%")
            
            self.set_humidity(humidity_val)
            
        except Exception as e:
            logger.error(f"[HUMIDIFIER ERROR] Failed parsing slider humidity message on '{self.id}': {e}")

    # --- Core Command Interfaces ---
    def turn_on(self) -> None:
        """Statefully powers on the device interface."""
        if self.attributes.get("state") == "ON":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "ON"
        self.update()
        self.print_state()

    def turn_off(self) -> None:
        """Statefully powers off the device interface."""
        if self.attributes.get("state") == "OFF":
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["state"] = "OFF"
        self.update()
        self.print_state()

    def toggle(self) -> None:
        """Alternates current hardware execution profile."""
        self.turn_on() if self.attributes.get("state") == "OFF" else self.turn_off()

    def set_humidity(self, target: Any) -> None:
        """Statefully clamps and commits targeted humidity percentage limits."""
        try:
            val = int(target)
            val = max(0, min(100, val)) # Clamps boundary states cleanly between 0-100%
            
            if self.attributes.get("target_humidity") == val:
                return

            self._previous_attributes = self.attributes.copy()
            self.attributes["target_humidity"] = val
            self.update()
            self.print_state()
            
        except (ValueError, TypeError) as e:
            logger.error(f"[HUMIDIFIER ERROR] Invalid humidity adjustment target '{target}' on '{self.id}': {e}")

    def print_state(self, include_attributes: bool = True) -> None:
        """Logs structured current state overview output inside the system console."""
        p_state = self.attributes.get("state", "OFF")
        h_target = self.attributes.get("target_humidity", 40)
        logger.info(f"[STATE] {self.domain}.{self.id} -> Power: {p_state} | Target: {h_target}%")


##########################
# WATER HEATER
########################
class WaterHeater(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "water_heater"
        
        # Atributos internos padrão esperados pelo HA
        if "operation_mode" not in self.attributes: 
            self.attributes["operation_mode"] = "eco"
        if "temperature" not in self.attributes: 
            self.attributes["temperature"] = 45.0
        if "current_temperature" not in self.attributes: 
            self.attributes["current_temperature"] = 39.0
            
        # Garante compatibilidade caso o motor de automação utilize a propriedade "state"
        self.attributes["state"] = self.attributes["operation_mode"]

    def mode_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/mode/set"

    def temperature_command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/temperature/set"

    def setup(self) -> None:
        defaults = {
            "mode_command_topic": self.mode_command_topic(),
            "mode_state_topic": self.state_topic(),
            "mode_state_template": "{{ value_json.state }}",
            
            "temperature_command_topic": self.temperature_command_topic(),
            "temperature_state_topic": self.state_topic(),
            "temperature_state_template": "{{ value_json.temperature }}",
            
            "current_temperature_topic": self.state_topic(),
            "current_temperature_template": "{{ value_json.current_temperature }}",
            
            "modes": ["off", "eco", "electric", "gas", "heat_pump", "high_demand", "performance"]
        }
        
        for key, val in defaults.items():
            if key not in self.configurations:
                self.configurations[key] = val

        super().setup()
        
        self.service.subscribe(self.mode_command_topic(), self.on_mode_message)
        self.service.subscribe(self.temperature_command_topic(), self.on_temp_message)
        
        # Sincroniza o estado inicial no boot
        self.update()

    def update(self, payload: Dict[str, Any] | None = None) -> None:
        """Serializa e publica o estado atual em JSON."""
        mode_value = str(self.attributes.get("operation_mode", "eco")).lower()
        self.attributes["state"] = mode_value  # Mantém o espelhamento para o trigger

        temperature = round(float(self.attributes.get("temperature", 45.0)), 1)
        current_temperature = self.attributes.get("current_temperature", round(float(temperature * (1 - 0.3)), 1))

        payload_data = {
            "state": mode_value,
            "temperature": str(temperature),
            "current_temperature": str(current_temperature)
        }

        self.service.publish(self.state_topic(), json.dumps(payload_data), retain=True)

        # Dispara os adapters do seu devices.yaml
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        pass

    def on_mode_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Trata comandos vindos da interface do HA para alteração de modo."""
        try:
            payload = msg.payload.decode("utf-8").strip().lower()
            logger.info(f"[HA IN] {self.domain}.{self.id} (Modo) -> '{payload}'")
            
            # Se o HA pedir para desligar ("off"), chama o método limpo turn_off()
            if payload == "off":
                self.turn_off()
            # Se for qualquer outro modo válido, repassa o argumento para o método parametrizado
            elif payload in self.configurations.get("modes", []):
                self.set_operation_mode(payload)
                
        except Exception as e:
            logger.error(f"[BOILER ERROR] Falha no on_mode_message em '{self.id}': {e}")

    def on_temp_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Trata comandos vindos do slider de temperatura do HA."""
        try:
            payload = msg.payload.decode("utf-8").strip()
            temp_val = float(payload)
            logger.info(f"[HA IN] {self.domain}.{self.id} (Temp) -> {temp_val}°C")
            
            # Altera a temperatura chamando o método parametrizado correto
            self.set_temperature(temp_val)
        except Exception as e:
            logger.error(f"[BOILER ERROR] Falha no on_temp_message em '{self.id}': {e}")

    # --- Métodos de Comando Puros (Conceitualmente SEM argumentos) ---
    def turn_on(self) -> None:
        """Liga o aquecedor no modo padrão ECO."""
        self.set_operation_mode("eco")

    def turn_off(self) -> None:
        """Desliga o aquecedor."""
        self.set_operation_mode("off")

    def toggle(self) -> None:
        """Alterna o estado de funcionamento."""
        self.turn_off() if self.attributes.get("operation_mode") != "off" else self.turn_on()

    def turn_away_mode_on(self) -> None:
        """Força o modo econômico de ausência."""
        self.set_operation_mode("eco")

    def turn_away_mode_off(self) -> None:
        """Retorna ao modo de performance."""
        self.set_operation_mode("performance")

    # --- Métodos Parametrizados (Que realmente esperam argumentos) ---
    def set_operation_mode(self, mode: str) -> None:
        """Aplica e salva o modo de operação."""
        mode_clean = str(mode).lower()
        if self.attributes.get("operation_mode") == mode_clean:
            return

        self._previous_attributes = self.attributes.copy()
        self.attributes["operation_mode"] = mode_clean
        self.update()
        self.print_state()

    def set_temperature(self, temp: Any) -> None:
        """Aplica e salva a temperatura alvo e atual de forma atômica."""
        try:
            val = round(float(temp), 1)
            if self.attributes.get("temperature") == val:
                return

            # 1. Tira o snapshot do estado anterior antes de qualquer mudança
            self._previous_attributes = self.attributes.copy()

            # 2. Calcula a temperatura dinâmica da água
            current_temp_calculated = round(float(val * (1 - 0.3)), 1)

            # 3. Atualiza AMBOS os atributos direto no dicionário primeiro.
            # Isso garante atomicidade: quando qualquer gatilho disparar, 
            # os dois valores já são floats numéricos puros dentro do objeto.
            self.attributes["temperature"] = val
            self.attributes["current_temperature"] = current_temp_calculated

            # 4. Agora sim, printa e propaga a atualização de estado com segurança
            self.print_state()
            self.update()

        except (ValueError, TypeError) as e:
            logger.error(f"[BOILER ERROR] Valor de temperatura inválido '{temp}': {e}")

  
    def print_state(self, include_attributes: bool = True) -> None:
        mode = self.attributes.get("operation_mode", "eco")
        target = self.attributes.get("temperature", 45.0)
        logger.info(f"[STATE] {self.domain}.{self.id} -> Mode: {mode.upper()} | Target: {target}°C")


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
