# MVP-IA-01 — Central Inteligente

## Objetivo

Adicionar supervisão operacional assistida por IA sem alterar automaticamente pedidos, status,
preços, fechamentos, faturamento ou qualquer ação externa.

## Capacidades

- risco de atraso;
- possível pedido duplicado;
- resumo diário de produção para hoje e amanhã;
- auditoria assistida de fechamento;
- alertas internos idempotentes;
- feedback do operador: útil, incorreta ou não aplicável.

## Arquitetura

```text
Django
  -> AIEvent no PostgreSQL
  -> worker run_ai_worker
  -> sanitização e minimização
  -> Gemini opcional
  -> JSON estruturado validado
  -> AIRecommendation
  -> feedback e auditoria
```

Não há Redis nem Celery. O PostgreSQL funciona como outbox/fila com um único worker.

## Segurança e privacidade

- empresas são enviadas ao provedor somente por identificador pseudonimizado;
- telefone, e-mail, endereço, CPF/CNPJ e termos conhecidos são removidos;
- dados reais e demonstrativos são processados separadamente;
- a chave Gemini fica somente no ambiente da VPS;
- a chave nunca é incluída em URL, log, banco, Git ou interface;
- qualquer entrada que falhe na validação de privacidade é bloqueada;
- o sistema continua operacional quando o Gemini estiver indisponível.

## Autonomia

Permitido automaticamente:

- analisar dados estruturados;
- enfileirar eventos;
- criar alertas e recomendações internas;
- expirar recomendações obsoletas;
- repetir chamadas temporariamente falhas, sem duplicidade.

Proibido para IA:

- alterar pedido, quantidade, preço ou status;
- validar ou faturar fechamento;
- enviar WhatsApp, e-mail ou outra ação externa;
- criar ou modificar dados comerciais fora das tabelas do módulo de IA.

## Gemini

Configuração segura por padrão:

```text
AI_ENABLED=0
AI_MODE=shadow
AI_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash-lite
AI_POLL_SECONDS=900
AI_MAX_ATTEMPTS=5
AI_RETENTION_DAYS=365
```

O nome do modelo é configurável. A integração usa resposta JSON estruturada e temperatura baixa.
Com `AI_ENABLED=0`, as regras determinísticas continuam gerando recomendações sem chamada externa.

## Operação

Executar um ciclo manual:

```bash
python manage.py run_ai_worker --once
```

Executar continuamente a cada 15 minutos:

```bash
python manage.py run_ai_worker
```

Expurgo controlado após 12 meses:

```bash
python manage.py purge_ai_history           # dry-run
python manage.py purge_ai_history --apply   # efetiva
```

## Modo sombra

No modo `shadow`, apenas Administradores visualizam recomendações. Depois da calibração e da
validação da sanitização, alterar explicitamente para:

```text
AI_MODE=pilot
```

## Idempotência

A chave combina tipo da análise, origem, versão dos dados, versão do prompt e modelo. Reexecutar
o mesmo contexto reutiliza o evento/recomendação existente e não repete consumo de API.

## Retentativas

Falhas temporárias são repetidas até cinco vezes:

1. primeira tentativa imediata;
2. após 15 minutos;
3. após 30 minutos;
4. após 60 minutos;
5. após 120 minutos.

Após o limite, o evento falha e gera alerta interno para o Administrador.

## Implantação

1. aplicar migrations;
2. executar `bootstrap_roles`;
3. configurar a chave somente na VPS;
4. iniciar em `AI_MODE=shadow`;
5. executar worker separado;
6. validar sete dias de modo sombra;
7. promover para `AI_MODE=pilot` somente após chancela.

## Rollback

1. interromper o worker;
2. definir `AI_ENABLED=0`;
3. reverter o merge;
4. manter as tabelas do módulo para preservar evidências;
5. remover migrations somente mediante autorização específica e backup validado.

O domínio de pedidos e fechamentos permanece independente do módulo de IA.
