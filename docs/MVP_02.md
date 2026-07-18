# MVP-02 — Autenticação, permissões e primeira GUI operacional

## Objetivo

Disponibilizar a primeira interface web interna do Empório Pedidos com identidade operacional, autenticação individual, perfis previsíveis e atualização segura do fluxo de status.

## Perfis

- **Administrador:** administração completa, exceto alteração/exclusão da auditoria append-only.
- **Atendimento:** empresas, consulta de produtos, pedidos e recebimento/cancelamento inicial.
- **Produção:** leitura operacional e avanço de `Recebido` para `Em produção`.
- **Expedição:** avanço de `Em produção` para `Saiu para entrega` e depois `Entregue`.
- **Financeiro:** leitura dos pedidos, fechamentos e auditoria; sem transição operacional.

Os grupos são sincronizados de forma idempotente após as migrations e também pelo comando:

```bash
python manage.py bootstrap_roles
```

## GUI entregue

- login e logout;
- troca obrigatória de senha inicial;
- navegação condicionada por permissão;
- painel com indicadores do dia e pedidos recentes;
- consultas de empresas, produtos, pedidos, fechamentos e auditoria;
- detalhe do pedido com itens e histórico;
- atualização de status por perfil, usando o serviço transacional e a auditoria existentes;
- interface responsiva sem dependências externas de frontend.

## Segurança e governança

- autorização validada no backend, não apenas escondida na interface;
- transições passam por `change_order_status`;
- duplo envio protegido por chave de idempotência determinística;
- nenhuma integração externa ou disparo automático;
- nenhuma credencial ou dado real versionado.

## Rollback

Reverter o merge do PR do MVP-02. Não há migration nova nem alteração destrutiva de schema nesta entrega.
