# EMP-PUBLIC-ACCESS-DISABLE-01

## Decisão operacional

A criação de usuários e o vínculo de acessos do portal passam a ser responsabilidade exclusiva da Biotech ou de uma pessoa autorizada pelo Empório com a capacidade `manage_companies`.

## Comportamento

- a configuração `PUBLIC_ACCESS_REQUEST_ENABLED=0` desativa a solicitação pública;
- o link **Solicitar acesso** deixa de ser exibido no login;
- a rota pública continua orientando usuários que possuam links antigos, mas não mostra formulário;
- qualquer POST direto recebe HTTP 403 e não cria registro;
- usuários, acessos e solicitações históricas são preservados;
- a fila e todas as operações internas de criação, vínculo, ativação, revogação e redefinição de senha continuam disponíveis a operadores autorizados;
- não há migration nem alteração de schema.

## Reativação controlada

Para reativar temporariamente a solicitação pública, defina:

```env
PUBLIC_ACCESS_REQUEST_ENABLED=1
```

Depois, recrie os serviços web e worker. A reativação não altera dados existentes.

## Rollback

O rollback da mudança pode ser feito retornando ao SHA anterior da aplicação ou definindo `PUBLIC_ACCESS_REQUEST_ENABLED=1`. Nenhuma restauração de banco é necessária.
