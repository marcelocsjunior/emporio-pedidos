# MVP-05 Fase 1 — Portal B2B com aprovação manual

## Objetivo

Permitir que usuários previamente cadastrados por uma empresa cliente criem solicitações de pedido sem gravar diretamente no fluxo oficial de pedidos.

## Fluxo

```text
Cliente autenticado
  -> rascunho da solicitação
  -> envio para conferência
  -> análise do Atendimento
  -> correção, rejeição ou aprovação
  -> conversão transacional e idempotente em pedido oficial
```

## Fronteiras

- não existe cadastro público;
- todo usuário do portal possui um único vínculo ativo com uma empresa;
- o cliente visualiza somente as próprias solicitações;
- locais de entrega são previamente cadastrados para a empresa;
- produtos e preços são consultados e recalculados no backend;
- a solicitação não altera pedidos, status, fechamentos ou faturamento;
- somente Atendimento ou Administrador pode aprovar;
- nenhuma ação externa, WhatsApp, e-mail ou pagamento é executada.

## Estados

- `draft`: rascunho editável;
- `submitted`: enviada para conferência;
- `in_review`: análise iniciada pelo Atendimento;
- `correction_requested`: devolvida para ajuste;
- `approved`: estado transacional anterior à conversão;
- `converted`: pedido oficial criado;
- `rejected`: rejeitada com justificativa;
- `cancelled`: cancelada pelo cliente antes da aprovação;
- `expired`: reservada para expiração controlada futura.

## Idempotência

A criação da solicitação usa `creation_key` único. A conversão usa a chave `portal:<uuid-da-solicitação>` no campo `Order.creation_key`. Repetir a aprovação retorna o mesmo pedido e não duplica itens.

## Auditoria

São registrados eventos para criação, edição, envio, início de análise, solicitação de correção, rejeição, cancelamento, aprovação, conversão e criação do pedido oficial.

## Provisionamento

No primeiro ciclo, o Administrador cria pelo Django Admin:

1. o usuário;
2. o local de entrega da empresa;
3. o vínculo `CustomerPortalAccess` entre usuário e empresa.

Não existe convite por e-mail ou criação automática de senha.

## Implantação

1. criar backup validado do PostgreSQL;
2. aplicar `customer_portal.0001_initial`;
3. executar `python manage.py bootstrap_roles`;
4. validar o acesso do Atendimento à fila `/solicitacoes/`;
5. validar um usuário cliente em `/portal/` com dados demonstrativos;
6. confirmar que uma aprovação cria exatamente um pedido.

## Rollback

1. impedir novos acessos ao portal;
2. reverter o código;
3. preservar as tabelas do portal para auditoria;
4. não reverter migration sem backup e autorização específica;
5. pedidos já convertidos permanecem no domínio oficial e não devem ser removidos automaticamente.
