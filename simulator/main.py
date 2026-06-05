import time

if __name__ == "__main__":
    from .runtime import Runtime

    runtime = Runtime()
    runtime.load_config("simulator/devices.yaml")
    runtime.start()
    
    try:
        # Mantém a aplicação viva escutando o Home Assistant
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        # Captura o Ctrl+C e limpa tudo automaticamente
        runtime.stop()

