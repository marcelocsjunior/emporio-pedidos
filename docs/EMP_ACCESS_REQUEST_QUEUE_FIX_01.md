# EMP-ACCESS-REQUEST-QUEUE-FIX-01

## Problema

A solicitação pública de acesso podia exibir confirmação de recebimento sem persistir uma nova entrada. O limitador agrupava todos os usuários pelo mesmo endereço de rede, o que bloqueava clientes legítimos atrás de NAT ou proxy compartilhado. A fila também ocultava solicitações ainda não vinculadas quando o filtro por empresa estava ativo.

## Correção

- mantém idempotência somente para solicitações pendentes ou em análise;
- permite novo envio após decisão final;
- limita abuso por combinação protegida de rede e documento, sem expor dados sensíveis;
- diferencia registro criado, duplicidade recente, limite temporário e rejeição pelo honeypot;
- inclui solicitações não vinculadas no filtro de empresa quando o documento protegido corresponde;
- preserva visualmente o filtro selecionado e adiciona ação para limpar filtros;
- adiciona testes de regressão para NAT compartilhado, idempotência, decisão final e filtro da fila.

## Impacto e rollback

Não há migration nem alteração de schema. O rollback é feito retornando para o SHA anterior da aplicação. Dados existentes permanecem compatíveis; registros antigos continuam considerados pelo fallback de metadados de abuso.
