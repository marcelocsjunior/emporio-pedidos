# Empório Pedidos

Sistema web interno para gestão de empresas clientes, produtos, pedidos, produção, entrega, fechamento mensal e mensagens assistidas do Empório Restaurante.

## Escopo do MVP

- uso exclusivamente interno;
- autenticação individual e permissões por grupos;
- empresas e produtos;
- pedidos com múltiplos itens;
- cálculo financeiro no backend;
- fluxo controlado de status e histórico;
- fechamento mensal por empresa;
- geração de texto para WhatsApp, sem envio automático;
- auditoria, testes e proteção contra versionamento de dados operacionais.

## Stack

- Python 3.12+
- Django 5.2 LTS
- PostgreSQL em produção
- SQLite apenas para desenvolvimento e testes locais

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

## Validação

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
ruff check .
```

## Segurança operacional

Nunca versionar bancos, planilhas de clientes, exports, uploads, backups, logs, tokens, secrets, credenciais ou dados reais.
