# Documentação do Motor de Automação Residencial (Simulador MQTT)

O sistema foi projetado para abstrair hardware físico em entidades lógicas altamente flexíveis. Através de um arquivo centralizado de configuração (`devices.yaml`), o motor gerencia o ciclo de vida dos dispositivos, realiza a autodescoberta (*MQTT Discovery*) no Home Assistant e orquestra automações na borda através de **Adapters**.

---

## 1. Arquitetura do Sistema e Ciclo de Dados

O motor opera em um modelo de **Inversão de Controle**. Os dispositivos físicos (como interruptores e potenciômetros na parede) perdem o poder de decisão direta sobre a carga elétrica e passam a agir como *sensores de intenção do usuário*, delegando o estado final para uma **Entidade Virtual Unificada**.

```
   [ Botão Físico ] ───(MQTT)───> [ Entidade Unificada ] <───(MQTT)─── [ Home Assistant ]
   (Sensor de Intenção)               (Cérebro / Light)                    (Painel de Controle)
                                              │
                                       (Adapters Engine)
                                              │
                                              ▼
                                    [ Relé de Carga / Script / Outro MQTT ]

```

### Ciclo de Mensagens (Inbound vs Outbound):

1. **Inbound (`on_message`):** O Home Assistant ou um dispositivo físico publica um comando no tópico `/set`. O simulador intercepta, atualiza o dicionário `attributes`, move o estado antigo para `_previous_attributes` (usando `.copy()`) e chama o método `update()`.
2. **Outbound (`update`):** O estado atualizado é publicado de volta para o Home Assistant no tópico `/state`. Logo em seguida, o loop de `adapters` analisa se houve mudança de propriedades para disparar as regras de automação.

---

## 2. Tipos de Dispositivos (Domains)

Os dispositivos disponíveis no ecossistema estendem a classe base `Device`. Cada domínio possui uma semântica rígida sobre como gerencia dados:

### 💡 `light` (Lâmpada)

* **Propósito:** Controlar iluminação discreta (ON/OFF) e contínua (brilho).
* **Escala de Brilho:** Opera nativamente no padrão de byte internacional, aceitando valores de **0 a 255**.
* **Atributos principais:** `state` ("ON"/"OFF"), `brightness` (int).

### 🎛️ `number` (Controle Numérico / Dimmer)

* **Propósito:** Representar controles deslizantes, potenciômetros físicos ou seletores.
* **Escala Padrão:** Customizável via YAML (geralmente **0 a 100** para representar porcentagem).
* **Atributos principais:** `value` (float/int). *Nota: Sobrescreve o método `update()` padrão para enviar números puros ao invés de strings binárias.*

### 🔌 `switch` (Interruptor / Relé)

* **Propósito:** Controlar o corte ou passagem de energia física (relés) ou representar botões binários.
* **Atributos principais:** `state` ("ON"/"OFF").

---

## 3. O Motor de Adapters (Orquestrador de Ações)

Os `adapters` interceptam mudanças de estado dentro de um dispositivo e disparam reações automáticas. Eles possuem um despachante de ações integrado que analisa a chave `action_type`.

### Tipos de Ações Suportadas:

1. **`device` (Padrão/Omitido):** Executa um método interno de outro dispositivo instanciado no simulador.
2. **`mqtt`:** Publica uma string/payload customizado em um tópico MQTT arbitrário da rede.
3. **`script`:** Dispara um comando shell no sistema operacional hospedeiro em segundo plano (não-bloqueante).

### O Ecossistema Jinja2:

Sempre que uma automação é disparada, a variável `value` (representando o valor atualizado da propriedade que acionou o gatilho) é injetada no ambiente do Jinja2. Isso permite realizar conversões matemáticas de escala e decisões lógicas dinâmicas no próprio YAML.

---

## 4. Guia Completo de Exemplos (`devices.yaml`)

O exemplo abaixo demonstra um cenário real e completo de uma sala de estar, aplicando **abstração unificada**, **sincronização reativa de brilho**, **emissão de logs no sistema** e **notificações via MQTT**.

```yaml
devices:
  # =========================================================================
  # 1. A ENTIDADE CENTRAL (CÉREBRO DA ILUMINAÇÃO)
  # =========================================================================
  - type: "light"
    id: "lampada_sala_completa"
    name: "Lâmpada da Sala"
    configurations:
      brightness: true
      schema: json
    attributes:
      state: "OFF"
      brightness: 120 # Inicializa em ~47% de brilho
    adapters:
      # Ação Tipo 1 (Omitida): Quando a lâmpada mudar de estado, gerencia o relé físico
      - trigger: "change"
        property: "state"
        target_id: "switch.rele_parede"
        target_action: "execute_action"
        data: "{{ 'turn_on' if value == 'ON' else 'turn_off' }}"

      # Ação Tipo 1 (Omitida): Quando o brilho mudar via app, alinha o dimmer físico da parede
      - trigger: "change"
        property: "brightness"
        target_id: "number.dimmer_parede"
        target_action: "set_value"
        data: "{{ (value / 2.55) | round | int }}" # Converte de byte (0-255) para % (0-100)

  # =========================================================================
  # 2. INTERRUPTOR FÍSICO DA PAREDE (BOTÃO BINÁRIO)
  # =========================================================================
  - type: "switch"
    id: "rele_parede"
    name: "Interruptor Físico da Sala"
    attributes:
      state: "OFF"
    adapters:
      # Delegação: O interruptor não desliga a energia, ele avisa a lâmpada virtual
      - trigger: "change"
        property: "state"
        target_id: "light.lampada_sala_completa"
        target_action: "execute_action"
        data: "{{ 'turn_on' if value == 'ON' else 'turn_off' }}"

  # =========================================================================
  # 3. DIMMER ROTATIVO DA PAREDE (CONTROLE NUMÉRICO)
  # =========================================================================
  - type: "number"
    id: "dimmer_parede"
    name: "Dimmer Rotativo"
    configurations:
      min: 0
      max: 100
      step: 1
    attributes:
      value: 0
    adapters:
      # Delegação com Matemática: Controla o brilho da lâmpada convertendo a escala para byte
      - trigger: "change"
        property: "value"
        target_id: "light.lampada_sala_completa"
        target_action: "set_brightness"
        data: "{{ (value * 2.55) | round | int }}" # Converte de % (0-100) para byte (0-255)

      # Ação Tipo 2 (MQTT Extrapolado): Notifica sistemas externos sobre a mudança do dimmer
      - trigger: "change"
        property: "value"
        action_type: "mqtt"
        topic: "casa/sala/dimmer/status"
        data: "O usuário alterou o potenciômetro físico para {{ value }}%"

      # Ação Tipo 3 (Script de Sistema): Escreve um log direto no servidor Linux local
      - trigger: "change"
        property: "value"
        action_type: "script"
        command: "echo '[$(date)] Dimmer Sala alterado para {{ value }}' >> /var/log/automacoes.log"

```

---

## 5. Arquivo Técnico de Implementação (Python)

Abaixo está o núcleo das classes estruturadas que interpretam o YAML acima, garantindo isolamento de histórico de atributos com `.copy()` e o despachante de ações flexível:

```python
import json
import logging
import subprocess
from typing import Any, Dict

logger = logging.getLogger("AutomationEngine")

class Device:
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.service = service
        self.domain = "generic"
        
        self.configurations = options.get("configurations", {})
        self.attributes = options.get("attributes", {})
        self.variables = options.get("variables", {})
        self.adapters_config = options.get("adapters", [])
        
        # Históricos isolados para o motor do is_changed
        self._previous_attributes: Dict[str, Any] = {}
        self._previous_variables: Dict[str, Any] = {}

    def get_property(self, key: str) -> Any:
        if key in self.attributes:
            return self.attributes[key]
        return self.variables.get(key)

    def get_previous_property(self, key: str) -> Any:
        if key in self._previous_attributes:
            return self._previous_attributes[key]
        if key in self._previous_variables:
            return self._previous_variables[key]
        return None

    def state_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/state"

    def command_topic(self) -> str:
        return f"homeassistant/{self.domain}/{self.id}/set"

    def update(self) -> None:
        """Comportamento padrão de publicação de estado (Binário/JSON)."""
        is_json_schema = self.configurations.get("schema") == "json"
        if is_json_schema:
            payload_ha = json.dumps(self.attributes)
        else:
            payload_ha = str(self.attributes.get("state", "OFF"))

        self.service.publish(self.state_topic(), payload_ha, retain=True)
        self._process_adapters()

    def _process_adapters(self) -> None:
        for adapter in self.adapters_config:
            if adapter.get("trigger") == "change":
                self._change_adapter(adapter)

    def _parse_adapter_data(self, template_str: str, current_value: Any) -> Any:
        """Sua engine interna que renderiza o Jinja2 injetando a var 'value'."""
        # Exemplo simplificado de resolução conceitual:
        # return jinja_env.from_string(template_str).render(value=current_value)
        pass

    def _change_adapter(self, adapter: Dict[str, Any]) -> None:
        prop = adapter.get("property")
        current_value = self.get_property(prop)
        previous_value = self.get_previous_property(prop)

        # Se for o boot inicial (previous é None), tratamos de forma reativa para dimmers
        if previous_value is None:
            if adapter.get("to") is not None:
                return # Bloqueia falsos gatilhos de ON/OFF no boot
            previous_value = current_value

        # Avalia o disparo baseado em mudança real de estado
        if current_value != previous_value:
            action_type = adapter.get("action_type", "device") # Fallback padrão omisso
            raw_data = adapter.get("data")
            action_payload = self._parse_adapter_data(raw_data, current_value)

            # --- CASO 1: EXECUÇÃO DE DISPOSITIVO INTERNO (OMITIDO NO YAML) ---
            if action_type == "device":
                target_object = adapter.get("target_object") # Resolvido pelo Runtime
                target_action = adapter.get("target_action")
                if target_object and target_action:
                    target_object.execute_action(target_action, payload=action_payload)

            # --- CASO 2: PUBLICAÇÃO MQTT EXTERNA ---
            elif action_type == "mqtt":
                topic = adapter.get("topic")
                if topic:
                    self.service.publish(topic, str(action_payload), retain=False)

            # --- CASO 3: SCRIPT DO SISTEMA OPERACIONAL (BASH/SHELL) ---
            elif action_type == "script":
                raw_command = adapter.get("command")
                if raw_command:
                    exec_command = self._parse_adapter_data(raw_command, current_value)
                    subprocess.Popen(exec_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Number(Device):
    def __init__(self, id: str, name: str, service: Any, options: Dict[str, Any]) -> None:
        super().__init__(id, name, service, options)
        self.domain = "number"
        if "value" not in self.attributes:
            self.attributes["value"] = 0.0

    def update(self) -> None:
        """Sobrescreve para garantir envio numérico puro, ignorando strings binárias."""
        is_json_schema = self.configurations.get("schema") == "json"
        if is_json_schema:
            payload_ha = json.dumps(self.attributes)
        else:
            payload_ha = str(self.attributes.get("value", 0.0))

        self.service.publish(self.state_topic(), payload_ha, retain=True)
        self._process_adapters()

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload_str = msg.payload.decode("utf-8").strip()
            val = float(payload_str)
            final_val = int(val) if val.is_integer() else val
            
            # Isolamento crucial de memória antes da mutação de estado
            self._previous_attributes = self.attributes.copy()
            self.attributes["value"] = final_val
            
            self.update()
        except Exception as e:
            logger.error(f"Erro de processamento no número '{self.id}': {e}")

```

---

## 6. Diagnóstico de Problemas Comuns

### O Slider do Dimmer voltou sozinho para o zero ou ficou cinza?

* **Causa:** O Home Assistant aplicou o comando via `/set`, mas a classe `Number` enviou uma string não-numérica no formato padrão (ex: `"OFF"`) de volta para o `/state`. O HA rejeita strings literais no domínio de números e desativa a entidade jogando-a em `unknown`.
* **Solução:** Garanta que o método `update()` da classe `Number` foi sobrescrito para extrair a propriedade `.get("value")` em formato string pura contendo apenas numerais (ex: `"45"`).

### Automações disparando em loops cíclicos infinitos?

* **Causa:** O Dimmer atualiza a Lâmpada e a Lâmpada devolve a atualização para o Dimmer sem validar se o valor de fato mudou.
* **Solução:** Garanta que nos métodos de entrada de comandos (`set_brightness` ou `set_value`), a alteração do dicionário `attributes` e a chamada subsequente do `update()` só ocorram se `self.attributes["propriedade"] != novo_valor`.
