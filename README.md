# 📝 README.md

```markdown
# IoT Home Simulator Engine 🚀

Este projeto é um simulador de ecossistema IoT modular e local escrito em Python. Ele mapeia dinamicamente dispositivos de hardware fictícios através de um arquivo de configuração declarativo (`devices.yaml`), gera o mapeamento automático para o **Home Assistant MQTT Discovery**, e processa **regras de automação local (Triggers)** em tempo real sem depender de servidores externos.

---

## 🛠️ Estrutura do `devices.yaml`

O arquivo `devices.yaml` centraliza o comportamento do broker e a declaração de todas as entidades. Cada dispositivo possui escopos bem definidos para separar dados dinâmicos de hardware (`attributes`) de parâmetros de rede e protocolo (`configurations`).

### Exemplo Completo de Configuração

```yaml
broker: localhost

devices:
  # ----------------------------------------------------
  # 1. LIGHT (Luz Inteligente com suporte a Cores e Brilho)
  # ----------------------------------------------------
  - type: light
    id: living_room_light
    name: Luz da Sala de Estar
    configurations:
      schema: json
      brightness: true
      color_mode: true
      supported_color_modes: ["rgb", "color_temp"]
    attributes:
      state: "OFF"
      brightness: 255
      color_temp: 300
      rgb_color: [255, 255, 255]

  # ----------------------------------------------------
  # 2. SWITCH (Tomada / Interruptor Simples - Optimistic)
  # ----------------------------------------------------
  - type: switch
    id: coffee_maker
    name: Cafeteira da Cozinha
    configurations:
      optimistic: true
    attributes:
      state: "OFF"

  # ----------------------------------------------------
  # 3. CLIMATE (Termostato / Ar Condicionado)
  # ----------------------------------------------------
  - type: climate
    id: master_bedroom_ac
    name: Ar Condicionado Casal
    configurations:
      min_temp: 16
      max_temp: 30
      modes: ["off", "cool", "heat", "fan_only"]
    attributes:
      state: "OFF"
      temperature: 22.0
      current_temperature: 24.5
      fan_mode: "medium"

  # ----------------------------------------------------
  # 4. BINARY SENSOR & TRIGGERS (Sensor com Automação Local Complexa)
  # ----------------------------------------------------
  - type: binary_sensor
    id: corridor_motion
    name: Sensor de Movimento do Corredor
    attributes:
      state: "OFF"
      lux: 120
    # ⚡ Motor de Automação Local (Lógica AND para as condições)
    triggers:
      - target_id: "light.living_room_light"
        action: "turn_on"
        conditions:
          - attribute: "state"
            value: "ON"
          - attribute: "lux"
            below: 50  # Só liga a luz se o movimento for ON e estiver escuro (< 50 lx)
      
      - target_id: "light.living_room_light"
        action: "turn_off"
        conditions:
          - attribute: "state"
            value: "OFF"

  - type: binary_sensor
    id: motion_kitchen
    name: Sensor de Movimento Cozinha
    triggers:
      - target_id: "light.kitchen"
        action: "turn_on"
        data:
          brightness: 128
          rgb_color: [255, 180, 50] # Acende uma luz mais quente
        conditions:
          - attribute: "state"
            value: "ON"
          - attribute: "lux"
            below: 40

  - type: sensor
    id: balcony_humidity
    name: Umidade da Varanda
    triggers:
      - target_id: "cover.living_room_window"
        action: "close_cover"
        data:
          tilt: 100 # Fecha totalmente a persiana se começar a chover forte
        conditions:
          - attribute: "state"
            above: 85.0

  # ----------------------------------------------------
  # 5. SENSOR (Sensor Numérico de Telemetria com Gatilho)
  # ----------------------------------------------------
  - type: sensor
    id: server_room_temp
    name: Temperatura do Servidor
    attributes:
      state: 25.0  # Estado principal de um sensor numérico é o seu valor atual
    triggers:
      - target_id: "switch.coffee_maker" # Exemplo de gatilho de segurança
        action: "turn_off"
        conditions:
          - attribute: "state"
            above: 45.0 # Desliga a tomada se a temperatura subir de 45°C


```


---

## 🔌 API de Comunicação & Interface MQTT

Cada dispositivo interage com o Broker baseado em tópicos padronizados derivados de seu `domain` e de seu `id` (formato: `homeassistant/{domain}/{id}/{action}`).

### 1. Descoberta Automática (Home Assistant Discovery)

No momento em que o sistema inicializa, cada entidade despacha uma mensagem de configuração com a flag `retain: True`. O Home Assistant intercepta esse payload e cria o dispositivo instantaneamente na interface sem necessidade de reiniciar o servidor.

* **Tópico:** `homeassistant/light/living_room_light/config`
* **Payload:** Configurações de tópicos de estado, comando, propriedades de cor, brilho e metadados de hardware.

### 2. Controle do Home Assistant para o Simulador (`/set`)

Dispositivos atuadores assinam tópicos de comando para reagir a cliques e interações feitas pelo usuário na interface do Home Assistant.

* **Comando de Luz Simples:**
```bash
mosquitto_pub -h localhost -t "homeassistant/switch/coffee_maker/set" -m "ON"

```


* **Comando JSON Avançado (Luz com Brilho/Cor):**
```bash
mosquitto_pub -h localhost -t "homeassistant/light/living_room_light/set" -m '{"state": "ON", "brightness": 180, "color": {"r": 255, "g": 0, "b": 100}}'

```



### 3. Injeção de Telemetria e Simulação Externa (`/simulate`)

Sensores biestáveis e numéricos são entidades *Read-Only* para o Home Assistant. Para simular eventos físicos do ambiente (como a leitura de uma porta GPIO, dados do clima ou a passagem de uma pessoa), envie payloads para o canal reservado de bypass do simulador.

* **Simulando Detecção de Movimento:**
```bash
mosquitto_pub -h localhost -t "homeassistant/binary_sensor/corridor_motion/simulate" -m "ON"

```


* **Injetando Valor de Temperatura em um Sensor:**
```bash
mosquitto_pub -h localhost -t "homeassistant/sensor/server_room_temp/simulate" -m "48.5"

```



---

## 🧠 Arquitetura do Motor de Triggers Locais

O `AppOrchestrator` atua como um barramento interno de eventos. O diagrama abaixo exemplifica o ciclo de vida completo de uma mensagem injetada pelo barramento de simulação até a execução final do gatilho local:

```text
 [Terminal / Hardware]
          │  (mosquitto_pub .../simulate "ON")
          ▼
   ┌──────────────┐
   │  MQTT Broker │
   └──────┬───────┘
          │ (Inbound Event)
          ▼
┌──────────────────────────────────────────────────────────────┐
│ Simulator Core Runtime                                       │
│                                                              │
│  ┌─────────────────────┐                                     │
│  │ BinarySensorDevice │                                     │
│  └──────────┬──────────┘                                     │
│             │ .turn_on() -> .addAttribute("state", "ON")     │
│             ▼                                                │
│  ┌─────────────────────┐                                     │
│  │   AppOrchestrator   │ ◄─── [Valida as condições do YAML]  │
│  └──────────┬──────────┘       Se 'state' == 'ON' e 'lux' < 50│
│             │                                                │
│             │ (Match! Executa reflexão do método target)     │
│             ▼                                                │
│  ┌─────────────────────┐                                     │
│  │     LightDevice     │ ──► .turn_on()                      │
│  └─────────────────────┘                                     │
└──────────────────────────────────────────────────────────────┘

```

---

## 🛠️ Como Executar o Ecossistema

1. Certifique-se de que o broker MQTT está rodando localmente:
```bash
docker run -d -p 1883:1883 --name mosquitto eclipse-mosquitto

```


2. Inicie o simulador em modo escuta:
```bash
python -m simulator.main

```


3. Abra um terminal complementar para assistir as atualizações em tempo real:
```bash
mosquitto_sub -h localhost -t "homeassistant/#" -v

```

