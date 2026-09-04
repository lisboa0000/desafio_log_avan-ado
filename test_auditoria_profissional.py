import json
import logging
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from auditoria_profissional import AuditoriaFinanceira


class TestAuditoriaFinanceira(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tempdir.name) / "auditoria.jsonl"
        AuditoriaFinanceira.configurar(self.log_path, max_bytes=500_000, backup_count=2)

    def tearDown(self):
        AuditoriaFinanceira.desligar()
        self.tempdir.cleanup()

    def eventos(self):
        for arquivo in sorted(self.log_path.parent.glob("auditoria.jsonl*")):
            if arquivo.is_file():
                yield from (json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines())

    def test_sucesso_usa_decimal_e_correlation_id(self):
        @AuditoriaFinanceira.log_operacao
        def pagar(valor: Decimal):
            return {"valor": valor, "status": "pago"}

        with AuditoriaFinanceira.correlacao("pedido-42"):
            resultado = pagar(Decimal("10.50"))

        self.assertEqual(resultado["valor"], Decimal("10.50"))
        evento = list(self.eventos())[0]
        self.assertEqual(evento["status"], "SUCESSO")
        self.assertEqual(evento["correlation_id"], "pedido-42")
        self.assertEqual(evento["retorno"]["valor"], "10.50")
        self.assertIsInstance(evento["duracao_ms"], (int, float))

    def test_falha_preserva_excecao_e_traceback(self):
        @AuditoriaFinanceira.log_operacao
        def falhar():
            raise ValueError("saldo insuficiente")

        with self.assertRaisesRegex(ValueError, "saldo insuficiente"):
            falhar()

        evento = list(self.eventos())[0]
        self.assertEqual(evento["status"], "FALHA")
        self.assertEqual(evento["erro"]["tipo"], "ValueError")
        self.assertIn("Traceback", evento["erro"]["traceback"])

    def test_campos_sensiveis_sao_mascarados(self):
        @AuditoriaFinanceira.log_operacao
        def autenticar(senha: str, dados: dict):
            return dados

        autenticar("segredo", {"token": "abc", "nome": "Ana"})
        evento = list(self.eventos())[0]
        self.assertEqual(evento["argumentos"]["senha"], "***REDACTED***")
        self.assertEqual(evento["argumentos"]["dados"]["token"], "***REDACTED***")
        self.assertEqual(evento["retorno"]["token"], "***REDACTED***")

    def test_rotacao_de_arquivo(self):
        AuditoriaFinanceira.configurar(self.log_path, max_bytes=300, backup_count=2)
        @AuditoriaFinanceira.log_operacao
        def grande(valor):
            return valor

        for i in range(20):
            grande("x" * 200 + str(i))
        arquivos = list(self.log_path.parent.glob("auditoria.jsonl*"))
        self.assertGreaterEqual(len(arquivos), 2)
        self.assertLessEqual(len(arquivos), 3)

    def test_concorrencia_nao_corrompe_json(self):
        @AuditoriaFinanceira.log_operacao
        def trabalho(numero):
            return numero * 2

        threads = [threading.Thread(target=trabalho, args=(i,)) for i in range(30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        eventos = list(self.eventos())
        self.assertEqual(len(eventos), 30)
        self.assertTrue(all(evento["status"] == "SUCESSO" for evento in eventos))

    def test_falha_de_logging_nao_interrompe_operacao(self):
        @AuditoriaFinanceira.log_operacao
        def operacao():
            return "ok"

        with patch.object(AuditoriaFinanceira._logger, "log", side_effect=OSError("disco cheio")):
            self.assertEqual(operacao(), "ok")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
