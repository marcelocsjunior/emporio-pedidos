# MVP-02B — Correções responsivas e observabilidade

## Escopo

- compactar o cabeçalho em telas pequenas;
- disponibilizar navegação móvel recolhível;
- eliminar cortes e rolagem horizontal nas listagens operacionais;
- converter tabelas em cartões no celular;
- preservar autenticação, permissões, regras de negócio e schema;
- tornar falhas internas rastreáveis sem expor dados sensíveis.

## Diagnóstico da mensagem genérica

A expressão `Algo deu errado. Tente novamente.` não existe nos templates, views, serviços, CSS ou demais arquivos do repositório. A aplicação também não possui JavaScript que gere snackbar ou toast com essa mensagem.

Na evidência visual, o painel foi carregado integralmente enquanto a mensagem apareceu em uma camada visual externa ao conteúdo da página. A conclusão técnica é que a notificação não foi emitida pelo Empório Pedidos; a origem mais provável é o navegador, o sistema Android ou outro recurso sobreposto ao navegador.

Para impedir diagnósticos futuros sem evidência, toda resposta passa a receber `X-Request-ID`. Exceções e respostas HTTP 5xx são registradas no stdout do container com método, caminho, status e código de correlação. A página 500 exibe somente esse código, sem stack trace ou dado sensível.

## Alterações visuais

- menu desktop preservado em telas largas;
- menu móvel baseado em `details/summary`, sem dependência de JavaScript;
- cartões de métricas em duas colunas no celular;
- cartões de status em duas colunas no celular;
- tabelas operacionais convertidas em cartões com rótulos semânticos;
- estados vazios renderizados sem corte;
- filtros passam para uma coluna em telas pequenas.

## Validação

```text
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
ruff check .
```

Validação visual requerida após implantação em homologação:

1. Chrome Android em largura aproximada de 360 a 430 px;
2. desktop em largura mínima de 1280 px;
3. abertura e fechamento do menu móvel;
4. painel sem rolagem horizontal;
5. empresas, produtos, pedidos, fechamentos e auditoria sem corte;
6. presença do cabeçalho `X-Request-ID` no healthcheck;
7. ausência de regressão em login, logout, troca de senha e permissões.

## Impacto em produção

- nenhuma migration;
- nenhuma alteração de banco;
- nenhuma integração externa;
- nenhuma ação automática;
- logs somente em stdout;
- nenhum dado real versionado.

## Rollback

Reverter o commit de merge do MVP-02B e reconstruir somente o serviço `web`. O banco e o volume PostgreSQL não precisam ser removidos.
