# Sistema Profissional de Auditoria Financeira em Python

**Autor:** lisboa_0000  
**Arquivos principais:** `auditoria_profissional.py` e `test_auditoria_profissional.py`

## 1. Visão geral

Esta atividade implementa um sistema de auditoria para operações financeiras em Python. O sistema registra cada execução de uma função decorada em um arquivo JSONL, com informações suficientes para identificar a operação, medir sua duração, investigar falhas e rastrear chamadas relacionadas.

A implementação usa o módulo `logging` da biblioteca padrão do Python. O arquivo de log possui rotação automática para evitar crescimento ilimitado. Os valores financeiros devem ser representados com `Decimal`, evitando os problemas de precisão associados ao tipo `float`.

> **Objetivo:** produzir registros estruturados, seguros e úteis para investigação operacional sem permitir que uma falha de observabilidade interrompa a operação principal.

## 2. Estrutura dos arquivos

| Arquivo | Responsabilidade |
|---|---|
| `auditoria_profissional.py` | Implementa o formatador JSON, a configuração do logging, a correlação de operações, a sanitização e o decorador de auditoria. |
| `test_auditoria_profissional.py` | Contém os testes automatizados de comportamento, segurança, rotação e concorrência. |
| `logs/auditoria.jsonl` | Arquivo gerado durante a execução. Ele não precisa ser criado manualmente. |

## 3. Fluxo de uma operação auditada

O fluxo completo ocorre quando uma função recebe o decorador `@AuditoriaFinanceira.log_operacao`.

1. O decorador inicia um cronômetro de alta resolução.
2. O sistema obtém o `correlation_id` atual ou gera um novo identificador.
3. Os argumentos são convertidos para uma representação segura.
4. Um `event_id` exclusivo é criado para aquele evento.
5. A função original é executada normalmente.
6. Em caso de sucesso, o retorno e o status `SUCESSO` são registrados.
7. Em caso de exceção, o status `FALHA`, o tipo do erro, a mensagem e o traceback são registrados.
8. A duração é calculada em milissegundos.
9. O evento é enviado ao módulo `logging`.
10. O `RotatingFileHandler` grava o evento no arquivo JSONL.
11. Se o logging falhar por qualquer motivo, a exceção de logging é capturada e apenas reportada no `stdout`, sem substituir o resultado ou a exceção da operação original.

O registro é feito no bloco `finally`, garantindo que a duração e o resultado da tentativa sejam registrados tanto em sucessos quanto em falhas.

## 4. Uso do decorador

Uma função pode ser auditada com poucas alterações:

```python
from decimal import Decimal

from auditoria_profissional import AuditoriaFinanceira


@AuditoriaFinanceira.log_operacao
def realizar_pagamento(conta: str, valor: Decimal) -> dict[str, str]:
    if valor <= Decimal("0"):
        raise ValueError("O valor deve ser positivo")
    return {"status": "processado", "conta": conta}
```

Antes de executar a função em uma aplicação, configure o destino do log:

```python
AuditoriaFinanceira.configurar(
    "logs/auditoria.jsonl",
    max_bytes=10_000_000,
    backup_count=5,
)
```

O parâmetro `max_bytes` define o tamanho máximo do arquivo atual. Quando esse limite é atingido, o arquivo é renomeado e um novo arquivo é iniciado. O parâmetro `backup_count` define quantos arquivos antigos serão preservados.

## 5. Uso de `Decimal` em valores financeiros

Valores monetários não devem ser calculados com `float` quando precisão exata for necessária. O tipo `float` representa números em ponto flutuante binário e pode produzir resultados inesperados em operações decimais.

O código utiliza `Decimal` com strings:

```python
valor = Decimal("500.00")
```

A construção com string é preferível à construção direta a partir de um `float`:

```python
# Preferível
Decimal("0.10")

# Evitar
Decimal(0.10)
```

A conversão para JSON é feita pelo auditor como texto. Assim, um valor `Decimal("10.50")` aparece no log como `"10.50"`, preservando a informação decimal sem depender de uma conversão implícita para `float`.

## 6. Identificadores de rastreamento

O sistema utiliza dois identificadores diferentes.

| Identificador | Finalidade |
|---|---|
| `event_id` | Identifica uma chamada específica da função. Cada execução recebe um valor novo. |
| `correlation_id` | Agrupa várias operações relacionadas à mesma solicitação, atendimento ou transação. |

Para definir manualmente um identificador de correlação, use o context manager:

```python
with AuditoriaFinanceira.correlacao("pedido-42"):
    validar_pagamento()
    realizar_pagamento("conta-001", Decimal("25.00"))
```

As operações executadas dentro desse contexto compartilham o valor `pedido-42`. Se nenhum identificador for informado, o sistema gera um UUID automaticamente.

O recurso utiliza `contextvars`, que permite manter o contexto de forma adequada durante chamadas encadeadas e em contextos assíncronos compatíveis.

## 7. Formato do evento

Cada linha do arquivo representa um objeto JSON independente. Um evento de sucesso possui estrutura semelhante a esta:

```json
{
  "event_id": "8f5f5d3d-7c68-4c1c-9a6b-5d0f3ac2d252",
  "correlation_id": "pedido-42",
  "timestamp": "2026-09-04T00:00:00.123+00:00",
  "funcao": "app.pagamentos.realizar_pagamento",
  "argumentos": {
    "conta": "conta-001",
    "valor": "25.00"
  },
  "contexto": {
    "pid": 1234,
    "thread_id": 14001,
    "thread_nome": "MainThread"
  },
  "status": "SUCESSO",
  "retorno": {
    "status": "processado",
    "conta": "conta-001"
  },
  "duracao_ms": 1.238
}
```

Um evento de falha acrescenta informações diagnósticas:

```json
{
  "status": "FALHA",
  "erro": {
    "tipo": "ValueError",
    "mensagem": "O valor deve ser positivo",
    "traceback": "Traceback ..."
  }
}
```

O timestamp é registrado em UTC no padrão ISO-8601. A duração é numérica e está expressa em milissegundos, facilitando cálculos de média, percentis e identificação de operações lentas.

## 8. Proteção de dados sensíveis

O método interno `_seguro` percorre mapas, listas, tuplas e outros valores compostos. Quando encontra nomes de campos sensíveis, substitui o conteúdo por `***REDACTED***`.

Entre os nomes protegidos estão:

| Campo | Representação no log |
|---|---|
| `senha` ou `password` | `***REDACTED***` |
| `token` | `***REDACTED***` |
| `authorization` | `***REDACTED***` |
| `cpf` | `***REDACTED***` |
| `cartao` / `cartão` / `numero_cartao` / `numero_cartão` | `***REDACTED***` |
| `cvv` | `***REDACTED***` |

A proteção também é aplicada a estruturas aninhadas. Por exemplo, um `token` dentro de um dicionário de argumentos também é mascarado.

Essa lista deve ser ampliada conforme os dados existentes no domínio da aplicação. A sanitização reduz o risco de exposição acidental, mas não substitui uma política completa de classificação, retenção e controle de acesso aos logs.

## 9. Rotação dos arquivos

O `RotatingFileHandler` mantém o arquivo atual e cria cópias numeradas quando o limite de tamanho é alcançado. Com a configuração padrão, podem existir arquivos como:

```text
logs/auditoria.jsonl
logs/auditoria.jsonl.1
logs/auditoria.jsonl.2
```

A rotação evita que um único arquivo cresça indefinidamente. Em produção, os valores de `max_bytes` e `backup_count` devem considerar o volume de operações, o espaço disponível e a política de retenção da organização.

A rotação por tamanho não é uma política completa de retenção. Logs financeiros podem exigir armazenamento centralizado, cópia de segurança, controle de acesso e retenção definida por requisitos legais ou internos.

## 10. Concorrência e limites da implementação

O `logging` oferece coordenação entre handlers no processo, e os testes verificam que múltiplas threads conseguem gerar eventos JSON válidos sem corromper as linhas. Além disso, `registrar_evento` captura qualquer exceção levantada pelo `logging` para que uma falha de escrita nunca interrompa a operação de negócio.

A implementação foi projetada para múltiplas threads dentro do mesmo processo. Em uma arquitetura com vários processos, containers ou máquinas, é recomendável utilizar uma solução centralizada, como:

- `QueueHandler` e `QueueListener`;
- syslog;
- um agente de coleta;
- Loki, Elasticsearch ou OpenSearch;
- um serviço de auditoria dedicado.

O arquivo local pode continuar sendo útil para desenvolvimento, testes e ambientes pequenos. Ele não deve ser considerado, sozinho, um armazenamento inviolável de auditoria.

## 11. Testes automatizados

Os testes usam `unittest`, que faz parte da biblioteca padrão do Python. A suíte cobre os comportamentos mais relevantes:

| Teste | O que verifica |
|---|---|
| Sucesso com `Decimal` | Preserva o resultado e registra o valor decimal como texto. |
| Falha com traceback | Relança a exceção e registra tipo, mensagem e traceback. |
| Campos sensíveis | Mascara dados secretos em argumentos e retornos. |
| Rotação | Cria arquivos de backup quando o limite é atingido. |
| Concorrência | Registra chamadas simultâneas sem corromper o JSON. |
| Falha do logging | Mantém a operação funcionando quando a escrita falha. |

Execute os testes com:

```bash
python3 -m unittest -v test_auditoria_profissional
```

Antes da execução, a verificação sintática pode ser feita com:

```bash
python3 -m py_compile auditoria_profissional.py test_auditoria_profissional.py
```

A saída esperada da suíte é semelhante a:

```text
Ran 6 tests
OK
```

## 12. Execução do exemplo

Para executar o exemplo incluído no módulo:

```bash
python3 auditoria_profissional.py
```

O comando configura o arquivo padrão, cria uma correlação chamada `atendimento-001` e executa uma transferência com `Decimal("500.00")`.

O arquivo será criado em:

```text
logs/auditoria.jsonl
```

Para analisar manualmente os eventos, cada linha pode ser lida como JSON. Em uma aplicação real, recomenda-se utilizar uma ferramenta de consulta ou enviar os eventos para uma plataforma de observabilidade.

## 13. Boas práticas para evolução

A implementação pode ser expandida com validação de schema dos eventos, hash de campos que precisem ser correlacionados sem serem expostos, controle de acesso aos arquivos e envio para armazenamento centralizado.

Também é recomendável separar eventos de auditoria de logs técnicos comuns. Auditoria deve possuir regras próprias de retenção, revisão e proteção contra alteração indevida.

Outra evolução possível é adicionar campos de negócio, como identificador da transação, conta de origem, conta de destino, valor autorizado e motivo da falha. Esses campos devem ser definidos com cuidado para evitar registrar mais dados pessoais do que o necessário.

## 14. Resumo

A atividade transforma um decorador simples em uma base de auditoria mais próxima de um sistema real. O `logging` centraliza a escrita, a rotação controla o crescimento dos arquivos, `Decimal` protege a precisão monetária, os identificadores permitem rastreamento, a sanitização reduz exposição de dados e os testes automatizados protegem o comportamento esperado.

A principal limitação restante é o armazenamento local. Para uso financeiro em produção, a próxima etapa deve ser integrar os eventos a uma infraestrutura centralizada, com retenção, controle de acesso, monitoramento e mecanismos de integridade.

## Referências

[1]: https://docs.python.org/3/library/logging.html "Python Logging — documentação oficial"

[2]: https://docs.python.org/3/library/logging.handlers.html "Python Logging Handlers — documentação oficial"

[3]: https://docs.python.org/3/library/decimal.html "Python Decimal — documentação oficial"

[4]: https://docs.python.org/3/library/contextvars.html "Python Context Variables — documentação oficial"

[5]: https://docs.python.org/3/library/unittest.html "Python unittest — documentação oficial"
