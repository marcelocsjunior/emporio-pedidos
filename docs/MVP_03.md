# MVP-03 — Cadastros e lançamento operacional de pedidos

## Escopo entregue

- cadastro, edição, ativação e inativação de empresas pela GUI;
- cadastro, edição, ativação e inativação de produtos pela GUI;
- lançamento de pedidos com múltiplos itens;
- cálculo de subtotais e total exclusivamente no backend;
- congelamento do nome e do preço do produto no item do pedido;
- edição de pedidos pendentes e dos dados de entrega de pedidos recebidos;
- bloqueio de produtos e empresas inativos em novos pedidos;
- bloqueio de produto duplicado, quantidade inválida e pedido sem item;
- bloqueio de avanço de status para pedido sem item ou valor válido;
- chave única para impedir duplicidade no reenvio do formulário;
- auditoria de criação, edição, ativação e inativação;
- permissões operacionais para Atendimento e Administrador.

## Regra de congelamento financeiro

O preço do produto é copiado para `OrderItem.unit_price` no momento da inclusão. Alterações posteriores no catálogo não modificam pedidos já lançados. Enquanto o pedido está `Pendente`, a quantidade pode ser alterada preservando o preço congelado. A troca do produto aplica o preço atual do novo produto.

## Regra de edição

- `Pendente`: dados do pedido e itens editáveis;
- `Recebido`: apenas dados gerais e de entrega editáveis;
- `Em produção`, `Saiu para entrega`, `Entregue` e `Cancelado`: edição bloqueada;
- inativação é lógica e não remove histórico.

## Migração

A migration `orders.0002_order_creation_key` adiciona um campo anulável e único. Não remove nem transforma dados existentes. Pedidos anteriores permanecem com valor nulo.

## Validação

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
pytest -q
ruff check .
```

## Implantação no NBBIO

1. atualizar a branch `main` após merge;
2. fazer backup lógico do PostgreSQL antes da migration;
3. reconstruir somente o serviço `web`;
4. o comando de inicialização aplicará a migration;
5. executar `python manage.py bootstrap_roles`;
6. validar `/health/`, login, cadastros e pedido de homologação;
7. conferir evento `order.created` na auditoria.

## Rollback

Rollback de código: reverter o merge e reconstruir o serviço `web`.

O campo `creation_key` pode permanecer no banco durante rollback por ser anulável e não interferir no MVP-02B. A reversão da migration só deve ocorrer após confirmar que nenhum pedido do MVP-03 depende da chave e após backup validado.

## Fora do escopo

- envio automático de WhatsApp;
- integrações fiscais ou financeiras;
- acesso de clientes;
- exclusão física de empresas, produtos ou pedidos;
- implantação em produção definitiva.
