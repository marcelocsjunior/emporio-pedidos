# MVP-CLIENTES-IMPORT-01 — Adequação cadastral

## Objetivo

Preparar o cadastro canônico `Company` para receber futuramente clientes por importação controlada, sem criar uma base paralela e sem alterar pedidos, fechamentos ou o Portal B2B.

## Alterações

- natureza do cliente: pessoa física ou pessoa jurídica;
- CPF/CNPJ opcional, normalizado e validado;
- e-mail, CEP e UF;
- sistema de origem e identificador externo;
- unicidade de CPF/CNPJ preenchido;
- unicidade de `source_system + external_id` preenchidos;
- cadastro manual atualizado para os novos campos;
- listagem com documento mascarado e contato consolidado.

## Compatibilidade

- registros existentes recebem `entity_type=company`;
- todos os demais campos novos são opcionais;
- `Company`, `Order` e `MonthlyClosing` permanecem com os mesmos vínculos;
- nenhuma autorização, rota de pedido, status, preço ou fechamento é modificada;
- nenhum arquivo CSV, XML ou XLSX é processado nesta entrega.

## Segurança e privacidade

- CPF/CNPJ é armazenado somente com números;
- CEP é armazenado somente com números;
- e-mail e sistema de origem são normalizados em minúsculas;
- a listagem exibe apenas documento mascarado;
- dados reais, arquivos de importação e credenciais não entram no Git.

## Validação

```text
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
ruff check .
```

## Rollback

A migration é reversível. A reversão remove apenas os campos e constraints desta entrega. Antes de qualquer rollback em ambiente com dados preenchidos, deve ser produzido backup do PostgreSQL e exportação das novas colunas, pois a reversão elimina esses valores.
