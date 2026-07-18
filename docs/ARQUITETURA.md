# Arquitetura inicial

## Decisão

Monólito modular em Django 5.2 LTS, com PostgreSQL em produção e renderização web server-side nas próximas entregas.

## Motivos

- autenticação, permissões, ORM, migrations e proteção CSRF nativas;
- menor complexidade operacional que separar frontend e API no MVP;
- manutenção simples em VM Linux;
- possibilidade de expor API posteriormente sem reconstruir o domínio;
- bom suporte a transações, auditoria e integridade relacional.

## Domínio inicial

- `accounts`: usuários internos;
- `orders`: empresas, produtos, pedidos, itens, histórico, fechamento e auditoria;
- `config`: configuração do projeto.

## Banco

- SQLite somente para desenvolvimento e testes rápidos;
- PostgreSQL obrigatório em produção;
- arquivos de banco nunca entram no Git.

## Evolução prevista

1. Fundação de domínio e testes.
2. Autenticação, grupos e permissões.
3. GUI operacional: pedidos do dia e novo pedido.
4. Produção/expedição e histórico.
5. Fechamento e mensagens.
6. Dashboard, exportação e rotina de backup.
