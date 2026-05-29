import time
import paho.mqtt.client as mqtt

from .runtime import Runtime

def iniciar_sistema():
    # 1. Instancia o Runtime principal
    runtime = Runtime()

    # 2. Carrega as configurações do arquivo 'config.yaml'
    print("--- Carregando Configurações ---")
    runtime.load_config("simulator/config/devices.yaml")

    # 3. Define os callbacks do cliente MQTT para monitorarmos a conexão no terminal
    def on_connect(client, userdata, flags, rc, properties=None):
        """Disparado quando conecta com sucesso ao Broker."""
        if rc == 0:
            print(
                f"\n[Sucesso] Conectado ao Broker MQTT ({runtime.broker_host})!"
            )
            print("Inicializando dispositivos e enviando Home Assistant Discovery...")

            # Executa o setup de cada dispositivo (Envia Discovery e assina tópicos de comando)
            for device in runtime.devices:
                device.setup()
        else:
            print(f"[Erro] Falha na conexão com o broker. Código de retorno: {rc}")

    def on_disconnect(client, userdata, rc, properties=None):
        print("[Aviso] Desconectado do Broker MQTT. Tentando reconectar...")

    # Vincula os callbacks ao cliente interno do runtime
    runtime.client.on_connect = on_connect
    runtime.client.on_disconnect = on_disconnect

    # 4. Inicia a conexão com o Broker
    print(f"\nTentando conectar ao broker em '{runtime.broker_host}'...")
    try:
        # Método start() inicia a conexão e o loop_start() em segundo plano
        runtime.start(port=1883)
    except Exception as e:
        print(f"[Erro fatal] Não foi possível conectar ao broker: {e}")
        return

    # 5. Mantém o script vivo para escutar os comandos do Home Assistant
    print("\n[Sistema Ativo] Pressione Ctrl+C para encerrar.")
    try:
        contador_teste = 0
        while True:
            time.sleep(1)
            contador_teste += 1

            # --- SIMULAÇÃO DE LEITURA DE SENSOR (Opcional) ---
            # A cada 10 segundos, vamos simular que o sensor de energia mediu algo novo
            if contador_teste % 10 == 0:
                house_power = next(
                    (d for d in runtime.devices if d.id == "house_power"), None
                )
                if house_power:
                    import random

                    # Gera um consumo simulado em Watts baseado no base_power do yaml
                    base = house_power.getAttribute("base_power", 350)
                    novo_consumo = base + random.randint(-50, 150)

                    print(
                        f"\n[Sensor Telemetria] Atualizando {house_power.name} para {novo_consumo}W"
                    )
                    # O método updateState atualiza internamente e já publica via MQTT
                    house_power.updateState(new_state=novo_consumo)

    except KeyboardInterrupt:
        print("\nEncerrando o Runtime de forma segura...")
        runtime.client.loop_stop()
        runtime.client.disconnect()
        print("Runtime encerrado.")


if __name__ == "__main__":
    iniciar_sistema()

#if __name__ == "__main__":
#    runtime = Runtime()
#    runtime.load_config("config.yaml")
#
#    # Callbacks de monitoramento MQTT
#    runtime.client.on_connect = lambda c, u, f, rc: [
#        print("\n⚡ Conectado ao Broker! Inicializando dispositivos..."),
#        [d.setup() for d in runtime.devices],
#    ]
#
#    runtime.start()
#
#    print("\n🚀 Sistema rodando. Simulando telemetria de sensores a cada 5s...")
#    try:
#        contador = 0
#        import random
#
#        while True:
#            time.sleep(5)
#            contador += 1
#
#            # 1. Testando Sensor de Energia (Acumulando kWh)
#            energy_dev = next(
#                (d for d in runtime.devices if d.id == "house_power"), None
#            )
#            if energy_dev:
#                # Incrementa o valor atual do estado simulando consumo acumulado
#                consumo_atual = energy_dev.state()
#                novo_consumo = consumo_atual + round(random.uniform(0.1, 0.5), 2)
#                print(f"\n[Simulação] {energy_dev.name} mediu: {novo_consumo} kWh")
#                energy_dev.updateState(new_state=novo_consumo)
#
#            # 2. Testando Sensor de Temperatura Comum
#            temp_dev = next(
#                (d for d in runtime.devices if d.id == "temperature_sensor"), None
#            )
#            if temp_dev:
#                nova_temp = round(random.uniform(21.0, 26.5), 1)
#                print(f"[Simulação] {temp_dev.name} atualizou para: {nova_temp}°C")
#                temp_dev.updateState(new_state=nova_temp)
#
#            # 3. Testando Sensor Binário (Porta Aberta / Fechada)
#            door_dev = next(
#                (d for d in runtime.devices if d.id == "front_door_sensor"), None
#            )
#            if door_dev:
#                # Fica alternando o estado a cada ciclo
#                novo_estado = "ON" if contador % 2 == 0 else "OFF"
#                print(f"[Simulação] {door_dev.name} mudou para: {novo_estado}")
#                door_dev.updateState(new_state=novo_estado)
#
# # ... dentro do seu loop while True principal ...

# Busca os objetos criados pela Factory na lista do runtime
#alarme = next((d for d in runtime.devices if d.id == "house_alarm"), None)
#sirene = next((d for d in runtime.devices if d.id == "backyard_siren"), None)
#
#if alarme and sirene:
#    estado_alarme = alarme.state()
#
#    # Exemplo: Se você for no Home Assistant e clicar em "Disparar" (ou simular via MQTT)
#    # O estado do alarme mudará para "triggering". Vamos fazer a sirene tocar junto!
#    if estado_alarme == "triggering" and sirene.state() == "OFF":
#        print("\n🔥 [AUTOMAÇÃO INTERNA] Alarme disparado! Ligando a sirene...")
#        sirene.updateState(new_state="ON")
#
#    # Se você for no HA e desarmar o alarme, desliga a sirene automaticamente
#    elif estado_alarme == "disarmed" and sirene.state() == "ON":
#        print(
#            "\n🟢 [AUTOMAÇÃO INTERNA] Alarme desarmado. Desligando a sirene..."
#        )
#        sirene.updateState(new_state="OFF")
#    except KeyboardInterrupt:
#        print("\nParando loops...")
#        runtime.client.loop_stop()

