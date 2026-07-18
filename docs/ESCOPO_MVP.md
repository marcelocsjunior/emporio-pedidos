# Escopo funcional — MVP Empório Pedidos

## Objetivo

Substituir o protótipo AppSheet por um software web próprio, exclusivo para uso interno do Empório Restaurante.

## Módulos aprovados

1. Autenticação e permissões por grupos.
2. Empresas clientes.
3. Produtos e preços.
4. Pedidos e itens.
5. Painel operacional do dia.
6. Fluxo de produção e entrega.
7. Fechamento mensal por empresa.
8. Mensagens prontas para WhatsApp.
9. Dashboard operacional.
10. Auditoria, logs, backup e exportação.

## Regras centrais

- valores são calculados e validados no backend;
- o preço do item é congelado no momento do pedido;
- o total do pedido é a soma dos itens persistidos;
- mudanças de status obedecem ao fluxo aprovado e geram histórico;
- fechamento mensal considera inicialmente apenas pedidos entregues;
- fechamento validado ou faturado não pode ser recalculado silenciosamente;
- mensagens são somente preparadas para revisão e envio humano;
- nenhuma ação externa automática entra no MVP;
- dados reais, bancos e credenciais ficam fora do Git.

## Fora do MVP

- portal do cliente;
- cliente lançando pedidos;
- WhatsApp API ou disparo automático;
- emissão fiscal;
- gateway bancário;
- rastreamento de entregador;
- integração direta com LeadOps;
- aplicativo nativo de loja.

## Critério de aceite da fundação

- migrations reproduzíveis;
- testes de cálculo, status, idempotência e fechamento aprovados;
- `manage.py check` sem erro;
- nenhuma credencial ou dado real versionado;
- branch isolada e PR revisável.
