import functools
import datetime
import json
import os
import threading
import time
from typing import Any, Callable, Dict

class AuditoriaFinanceira:
    """
    Uma implementação única de um sistema de log para auditoria financeira.
    Diferenciais:
    1. Formatação JSON para facilitar análise posterior (Big Data/Analytics).
    2. Thread-safe (uso de Locks para evitar corrupção de arquivo).
    3. Tratamento de exceções (registra se a função falhou).
    4. Metadados extras (ID do processo, ID da thread).
    """
    
    _lock = threading.Lock()
    _arquivo_log = "log.txt"

    @classmethod
    def log_operacao(cls, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            inicio = time.perf_counter()
            data_hora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            try:
                # Executa a função original
                resultado = func(*args, **kwargs)
                status = "SUCESSO"
                erro = None
            except Exception as e:
                resultado = None
                status = "FALHA"
                erro = str(e)
                raise # Re-levanta a exceção para não quebrar o fluxo da app
            finally:
                fim = time.perf_counter()
                duracao = f"{fim - inicio:.4f}s"
                
                # Prepara o registro de log
                registro = {
                    "timestamp": data_hora,
                    "funcao": func.__name__,
                    "argumentos": {
                        "posicionais": [str(a) for a in args],
                        "nomeados": {k: str(v) for k, v in kwargs.items()}
                    },
                    "retorno": str(resultado) if status == "SUCESSO" else None,
                    "status": status,
                    "duracao": duracao,
                    "contexto": {
                        "pid": os.getpid(),
                        "thread": threading.current_thread().name
                    }
                }
                
                if erro:
                    registro["erro"] = erro

                # Escrita segura no arquivo
                with cls._lock:
                    with open(cls._arquivo_log, "a", encoding="utf-8") as f:
                        # Gravamos como uma string formatada em JSON
                        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            
            return resultado
        return wrapper

# --- Exemplo de Uso (Simulando uma Aplicação Financeira) ---

@AuditoriaFinanceira.log_operacao
def realizar_transferencia(origem: str, destino: str, valor: float):
    """Simula uma transferência bancária."""
    print(f"Processando transferência de R${valor} de {origem} para {destino}...")
    time.sleep(0.5) # Simula processamento real
    return {"id_transacao": "TX12345", "status": "confirmado"}

@AuditoriaFinanceira.log_operacao
def consultar_saldo(conta_id: str):
    """Simula consulta de saldo."""
    return 1500.50

@AuditoriaFinanceira.log_operacao
def operacao_com_erro():
    """Simula uma falha crítica."""
    raise ValueError("Saldo insuficiente para completar a operação.")

if __name__ == "__main__":
    print("Iniciando demonstração do Desafio de Auditoria...\n")
    
    try:
        # 1. Operação de Sucesso
        realizar_transferencia("Conta-A", "Conta-B", 500.0)
        
        # 2. Operação de Consulta
        consultar_saldo("Conta-A")
        
        # 3. Operação que gera erro
        print("\nTentando operação que gera erro...")
        operacao_com_erro()
        
    except Exception:
        print("Erro capturado e registrado no log.")

    print(f"\nVerificando o conteúdo de '{AuditoriaFinanceira._arquivo_log}':\n")
    if os.path.exists(AuditoriaFinanceira._arquivo_log):
        with open(AuditoriaFinanceira._arquivo_log, "r") as f:
            for linha in f:
                log_data = json.loads(linha)
                print(f"[{log_data['timestamp']}] Função: {log_data['funcao']} | Status: {log_data['status']} | Duração: {log_data['duracao']}")
    else:
        print("Arquivo de log não encontrado.")
