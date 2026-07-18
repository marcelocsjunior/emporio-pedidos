# MVP-04 — Fechamento mensal e mensagens operacionais

## Objetivo

Permitir que o Financeiro gere, confira, valide e marque como faturado o fechamento mensal de cada empresa, usando exclusivamente pedidos entregues.

## Fluxo

1. Selecionar empresa e mês.
2. Gerar ou recalcular o fechamento.
3. Conferir pedidos, quantidades e valor total.
4. Registrar observações internas.
5. Marcar como `Pendente`, `A conferir`, `Validado` ou `Faturado` conforme as transições permitidas.
6. Copiar a mensagem ou abrir manualmente o WhatsApp.
7. Exportar o detalhamento em CSV.

## Regras

- somente pedidos com status `Entregue` entram no fechamento;
- existe no máximo um fechamento por empresa e mês;
- gerar novamente atualiza o mesmo registro;
- fechamento validado ou faturado não pode ser recalculado;
- validação exige ao menos um pedido entregue e valor total positivo;
- faturamento somente ocorre após validação;
- ações financeiras e alterações de status são auditadas;
- a exportação CSV neutraliza conteúdo potencialmente interpretado como fórmula;
- mensagens não são enviadas automaticamente.

## Permissões

- **Administrador:** operação completa;
- **Financeiro:** gerar, recalcular, alterar status, registrar observações, exportar;
- **Atendimento:** consultar fechamentos e exportar, sem alterações;
- **Produção e Expedição:** não recebem permissão financeira adicional.

## Implantação

Não há migration ou alteração de schema nesta entrega. A implantação requer reconstrução do serviço web e execução do `bootstrap_roles` para garantir a matriz vigente.

## Validação

```text
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
ruff check .
```

## Rollback

1. Reverter o merge do MVP-04.
2. Reconstruir somente o serviço web.
3. Validar `/health/`, login, pedidos e fechamentos existentes.

Os dados já existentes de pedidos e fechamentos não são removidos pelo rollback do código.
