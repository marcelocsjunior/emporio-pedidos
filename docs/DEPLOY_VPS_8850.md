# Implantação VPS isolada — porta 8850

Este pacote prepara uma implantação PostgreSQL autônoma do Empório Pedidos, sem executar qualquer deploy. Web e worker usam a mesma imagem identificada pelo SHA Git; migrations e `bootstrap_roles` são etapas controladas. O worker reproduz o comando observado no piloto: `python manage.py run_ai_worker --interval 900`.

## Acesso HTTP público temporário

A URL autorizada nesta fase é `http://${APP_PUBLIC_HOST}:8850`, exposta diretamente pelo host público da VPS ou VM e sem TLS. Credenciais e sessão trafegam sem criptografia: use uma credencial exclusiva e nunca reaproveite senha. `DEBUG` e IA permanecem desligados, e CSRF permanece integralmente ativo.

O arquivo de ambiente explicita temporariamente `DJANGO_SESSION_COOKIE_SECURE=0` e `DJANGO_CSRF_COOKIE_SECURE=0`; isso permite login em HTTP, mas reduz a proteção de transporte dos cookies. Não use `DEBUG=1` como solução.

## Arquitetura e isolamento

- aplicação: `/opt/emporio-pedidos-producao/app`
- runtime e `.env`: `/opt/emporio-pedidos-producao/runtime`
- backups: `/opt/emporio-pedidos-producao/backups`
- logs: `/opt/emporio-pedidos-producao/logs`
- projeto Compose: `emporio_pedidos_producao`
- porta pública: `8850`; web interna: `8000`; PostgreSQL não publica porta
- volume exclusivo: `emporio_pedidos_producao_pgdata`

Os scripts falham fechados se encontrarem porta, path, projeto, volume ou Compose do piloto. Não há opção para ignorar a proteção. É proibido copiar banco, arquivos, usuários ou dados do piloto sem um novo GO explícito.

## Pré-requisitos e ambiente

São necessários Linux, Bash, Git, Docker Engine, Docker Compose v2, `flock`, `curl`, espaço em disco e acesso ao repositório. Faça checkout do SHA autorizado exatamente no path da aplicação. Prepare o ambiente sem versioná-lo:

```bash
sudo install -d -m 700 /opt/emporio-pedidos-producao/runtime
sudo install -m 600 deploy/env.vps.example /opt/emporio-pedidos-producao/runtime/.env
sudoedit /opt/emporio-pedidos-producao/runtime/.env
```

Substitua todos os exemplos por segredos novos e exclusivos. Defina `APP_PUBLIC_HOST` somente com o IP ou hostname público, sem protocolo, porta, barra, espaços ou wildcards. Inclua exatamente esse valor em `DJANGO_ALLOWED_HOSTS` e configure `DJANGO_CSRF_TRUSTED_ORIGINS=http://${APP_PUBLIC_HOST}:8850`. Preserve `APP_PORT=8850`, o projeto e o volume definidos. IA e ações externas permanecem desligadas por padrão.

Valide o login manualmente em `http://${APP_PUBLIC_HOST}:8850/conta/entrar/`, confirme que CSRF continua rejeitando requisições inválidas e encerre a sessão após o teste.

## Preflight, primeira instalação e atualização

Use sempre um SHA completo de 40 caracteres, pertencente a `origin/main`, com o checkout no mesmo SHA:

```bash
sudo /opt/emporio-pedidos-producao/app/ops/vps-deploy.sh --sha 0123456789abcdef0123456789abcdef01234567 --preflight-only
sudo /opt/emporio-pedidos-producao/app/ops/vps-deploy.sh --sha 0123456789abcdef0123456789abcdef01234567 --dry-run
sudo /opt/emporio-pedidos-producao/app/ops/vps-deploy.sh --sha 0123456789abcdef0123456789abcdef01234567
```

Na primeira instalação, o fluxo constrói a imagem, inicia o banco vazio, migra, aplica perfis idempotentes, inicia web/worker, valida e cria backup-base. Em atualização, cria backup antes da mudança. Repetir o SHA saudável resulta em `DEPLOY_MODE=NO_OP`; o mesmo SHA degradado resulta em `DEPLOY_MODE=RECONCILE`, preservando banco e volume.

O administrador nunca é criado pelo deploy. Quando `ADMIN_REQUIRED=SIM`, use um terminal humano:

```bash
sudo /opt/emporio-pedidos-producao/app/ops/vps-create-admin.sh
```

A senha é solicitada pelo Django, nunca por argumento, ambiente ou log.

## Backup, status e rollback

```bash
sudo /opt/emporio-pedidos-producao/app/ops/vps-backup.sh --reason manual
sudo /opt/emporio-pedidos-producao/app/ops/vps-status.sh
sudo /opt/emporio-pedidos-producao/app/ops/vps-rollback.sh --previous --dry-run
sudo /opt/emporio-pedidos-producao/app/ops/vps-rollback.sh --previous
```

Backups são dumps custom PostgreSQL, validados por `pg_restore --list`, protegidos em modo 600 e acompanhados de SHA-256. A retenção padrão é 30 dias e preserva o mais recente e o associado ao estado anterior.

Rollback troca somente web e worker para uma imagem previamente implantada e preserva `.env`, PostgreSQL, volume e backups. Nunca restaura banco automaticamente. Se uma implantação aplicou migrations, não improvise downgrade: preserve o backup, interrompa e trate como `DB_ROLLBACK_DECISION_REQUIRED=SIM` com revisão humana.

## Estado, evidências e validação humana

Estado e evidências sanitizadas ficam em `runtime/state`, `runtime/evidence` e `runtime/deployments.log` (diretórios 700, arquivos 600). Confira SHA/imagem, três serviços, volume, migrations, reinícios, `/health/`, `/conta/entrar/` e estáticos. Não use credenciais reais em automação de login.

O status termina em `STATUS=HEALTHY`, `STATUS=DEGRADED` ou `STATUS=UNAVAILABLE`. Para falhas, execute primeiro preflight/status, confirme espaço, Docker, checkout e permissões, e leia somente logs sanitizados. Não edite estado manualmente nem aponte para recursos do piloto.

Domínio, DNS, proxy reverso e HTTPS pertencem a uma fase posterior. Quando HTTPS estiver efetivamente configurado, altere `DJANGO_SESSION_COOKIE_SECURE=1` e `DJANGO_CSRF_COOKIE_SECURE=1`, valide o fluxo e remova a exposição direta da porta 8850. Este documento não autoriza DNS/TLS, deploy, cópia de dados do piloto, criação de usuários reais nem acesso ao banco real.
