"""Auditoria financeira profissional baseada no módulo logging da biblioteca padrão."""

from __future__ import annotations

import contextvars
import functools
import inspect
import json
import logging
import logging.handlers
import os
import time
import threading
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "auditoria_correlation_id", default=None
)


class JSONFormatter(logging.Formatter):
    """Serializa cada registro de logging como um objeto JSON em uma única linha."""

    def format(self, record: logging.LogRecord) -> str:
        evento = getattr(record, "evento", None)
        if evento is None:
            evento = {"mensagem": record.getMessage(), "nivel": record.levelname}
        return json.dumps(evento, ensure_ascii=False, separators=(",", ":"), default=str)


class AuditoriaFinanceira:
    """Decorador de auditoria com correlação, sanitização e rotação de arquivos."""

    LOGGER_NAME = "auditoria.financeira"
    _logger = logging.getLogger(LOGGER_NAME)
    _configurado = False
    _lock_configuracao = threading.Lock()
    _campos_sensiveis = frozenset(
        {
            "senha", "password", "token", "authorization", "cpf",
            "cartao", "cartão", "numero_cartao", "numero_cartão", "cvv",
        }
    )
    _limite_valor = 2_000

    @classmethod
    def configurar(
        cls,
        arquivo: str | os.PathLike[str] = "logs/auditoria.jsonl",
        *,
        max_bytes: int = 10_000_000,
        backup_count: int = 5,
        nivel: int = logging.INFO,
    ) -> None:
        """Configura um arquivo JSONL com rotação por tamanho.

        A configuração é idempotente: chamadas posteriores substituem os
        handlers anteriores, evitando linhas duplicadas em testes ou reloads.
        """
        if max_bytes <= 0 or backup_count < 0:
            raise ValueError("max_bytes deve ser positivo e backup_count não pode ser negativo")

        caminho = Path(arquivo)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            caminho, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setFormatter(JSONFormatter())

        with cls._lock_configuracao:
            for antigo in cls._logger.handlers[:]:
                cls._logger.removeHandler(antigo)
                antigo.close()
            cls._logger.addHandler(handler)
            cls._logger.setLevel(nivel)
            cls._logger.propagate = False
            cls._configurado = True

    @classmethod
    def desligar(cls) -> None:
        """Remove handlers, útil para testes e encerramento controlado."""
        with cls._lock_configuracao:
            for handler in cls._logger.handlers[:]:
                cls._logger.removeHandler(handler)
                handler.close()
            cls._configurado = False

    @classmethod
    @contextmanager
    def correlacao(cls, correlation_id: str | None = None) -> Iterator[str]:
        """Define um identificador para todas as operações no contexto atual."""
        atual = correlation_id or str(uuid.uuid4())
        token = _correlation_id.set(atual)
        try:
            yield atual
        finally:
            _correlation_id.reset(token)

    @classmethod
    def _seguro(cls, valor: Any, nome: str = "") -> Any:
        if nome.casefold() in cls._campos_sensiveis:
            return "***REDACTED***"
        if valor is None or isinstance(valor, (bool, int, float, str, Decimal)):
            convertido: Any = str(valor) if isinstance(valor, Decimal) else valor
        elif isinstance(valor, Mapping):
            convertido = {str(k): cls._seguro(v, str(k)) for k, v in valor.items()}
        elif isinstance(valor, (list, tuple, set, frozenset)):
            convertido = [cls._seguro(item) for item in valor]
        else:
            convertido = repr(valor)
        if isinstance(convertido, str) and len(convertido) > cls._limite_valor:
            return convertido[: cls._limite_valor] + "...<truncado>"
        return convertido

    @classmethod
    def _argumentos(cls, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            vinculados = inspect.signature(func).bind(*args, **kwargs)
            vinculados.apply_defaults()
            return {
                nome: cls._seguro(valor, nome)
                for nome, valor in vinculados.arguments.items()
            }
        except (TypeError, ValueError):
            # Fallback para callables sem assinatura introspectável.
            nomes = ["arg_" + str(i) for i in range(len(args))]
            resultado = {nome: cls._seguro(valor, nome) for nome, valor in zip(nomes, args)}
            resultado.update({nome: cls._seguro(valor, nome) for nome, valor in kwargs.items()})
            return resultado

    @classmethod
    def registrar_evento(cls, evento: dict[str, Any], nivel: int = logging.INFO) -> None:
        """Envia o evento para logging; falha de observabilidade não interrompe negócio."""
        if not cls._configurado:
            cls.configurar()
        try:
            cls._logger.log(nivel, "evento_de_auditoria", extra={"evento": evento})
        except Exception as erro:  # noqa: BLE001 - observabilidade nunca derruba o negócio
            # A operação financeira não deve falhar apenas porque o log falhou.
            print(f"[auditoria] falha ao escrever evento: {erro}", flush=True)

    @classmethod
    def log_operacao(cls, func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            inicio = time.perf_counter()
            id_atual = _correlation_id.get()
            gerou_id = id_atual is None
            if gerou_id:
                id_atual = str(uuid.uuid4())
                token = _correlation_id.set(id_atual)

            evento: dict[str, Any] = {
                "event_id": str(uuid.uuid4()),
                "correlation_id": id_atual,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "funcao": f"{func.__module__}.{func.__qualname__}",
                "argumentos": cls._argumentos(func, args, dict(kwargs)),
                "contexto": {
                    "pid": os.getpid(),
                    "thread_id": threading.get_ident(),
                    "thread_nome": threading.current_thread().name,
                },
            }
            try:
                resultado = func(*args, **kwargs)
            except Exception as erro:
                evento.update(
                    status="FALHA",
                    erro={
                        "tipo": type(erro).__name__,
                        "mensagem": str(erro),
                        "traceback": traceback.format_exc(),
                    },
                )
                raise
            else:
                evento.update(status="SUCESSO", retorno=cls._seguro(resultado))
                return resultado
            finally:
                evento["duracao_ms"] = round((time.perf_counter() - inicio) * 1000, 3)
                cls.registrar_evento(evento, logging.ERROR if evento.get("status") == "FALHA" else logging.INFO)
                if gerou_id:
                    _correlation_id.reset(token)

        return wrapper


@AuditoriaFinanceira.log_operacao
def realizar_transferencia(origem: str, destino: str, valor: Decimal) -> dict[str, str]:
    """Exemplo de operação monetária sem aritmética binária de float."""
    if valor <= Decimal("0"):
        raise ValueError("O valor deve ser positivo")
    return {"status": "confirmado", "origem": origem, "destino": destino}


if __name__ == "__main__":
    AuditoriaFinanceira.configurar()
    with AuditoriaFinanceira.correlacao("atendimento-001") as cid:
        print(realizar_transferencia("Conta-A", "Conta-B", Decimal("500.00")))
        print(f"correlation_id={cid}")

__all__ = ["AuditoriaFinanceira", "JSONFormatter", "realizar_transferencia"]
