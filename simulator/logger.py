import logging
import sys

def setup_logger(verbose: bool = False) -> logging.Logger:
    """Configura o sistema de logs para arquivo e terminal de forma independente."""
    logger = logging.getLogger("simulator")
    logger.setLevel(logging.DEBUG)  # Captura tudo internamente
    
    # Evita duplicar logs caso o setup seja chamado mais de uma vez
    if logger.handlers:
        return logger

    # --- FORMATADORES ---
    # Terminal fica mais limpo, arquivo ganha timestamp completo e arquivo/linha
    stdout_formatter = logging.Formatter('%(message)s')
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] (%(filename)s:%(lineno)d): %(message)s')

    # --- HANDLER 1: TERMINAL (STDOUT) ---
    stdout_handler = logging.StreamHandler(sys.stdout)
    # Se verbose=True mostra DEBUG no terminal, senão mostra apenas INFO para cima
    stdout_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stdout_handler.setFormatter(stdout_formatter)
    logger.addHandler(stdout_handler)

    # --- HANDLER 2: ARQUIVO (simulator.log) ---
    file_handler = logging.FileHandler("simulator.log", mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # Arquivo SEMPRE grava tudo (modo verbose eterno)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

# Instância global padrão inicializada como não-verbose
logger = setup_logger(verbose=False)
