# MVP-PORTAL-CLIENTE-01 — gestão de acessos

## Objetivo e conceitos

Esta fase acrescenta a gestão dos usuários do Portal B2B e uma solicitação pública sujeita a conferência humana. `Company` continua sendo o cadastro canônico do cliente; `User` é a identidade que autentica; `CustomerPortalAccess` é o vínculo entre ambos. Um cliente pode existir sem usuário, e um usuário do cliente não é um cadastro de cliente.

## Fluxo público

Na tela de login, **Solicitar acesso** abre um formulário público protegido por CSRF e honeypot. CPF/CNPJ é validado, mas somente um HMAC-SHA256 baseado no segredo da aplicação e os quatro últimos dígitos são persistidos. E-mail e telefone são normalizados. Endereço de rede e agente do navegador também são registrados apenas como HMAC para controle de abuso.

A combinação segura de documento, e-mail e telefone é idempotente por 24 horas. Um mesmo endereço de rede pode produzir no máximo cinco solicitações por hora; depois disso, o formulário mantém a mesma resposta genérica. Esses limites são temporários e não bloqueiam definitivamente um cliente legítimo.

O fluxo público não consulta nem revela empresas ou usuários existentes. Ele não cria `User`, `Company` ou `CustomerPortalAccess`.

## Fluxo administrativo

Usuários com `manage_companies` acessam **Clientes/Empresas → Acessos dos clientes** e, em cada cliente, **Acessos**. A área permite criar um usuário de portal sem privilégios internos, vincular um usuário existente elegível, consultar detalhes e auditoria, ativar, bloquear e redefinir manualmente a senha.

Senhas passam pelos validadores oficiais do Django, são gravadas por `set_password`, nunca aparecem depois da gravação nem entram na auditoria. A política já existente de troca obrigatória no primeiro acesso é reutilizada. Usuários técnicos protegidos, staff, superusuários e identidades com grupos, permissões ou capabilities internas não podem ser vinculados. Revogar um vínculo não exclui nem desativa o usuário e não altera grupos, capabilities ou outros dados.

## Análise, aprovação e rejeição

**Solicitações de acesso** oferece fila por status, período e empresa. O operador vê somente o documento e contatos mascarados, procura manualmente uma empresa existente e pode marcar a solicitação em análise.

A aprovação exige empresa, usuário elegível e confirmação humana. O documento não serve sozinho como prova de identidade. Nenhuma `Company` é criada neste fluxo; quando ela não existe, o operador deve sair e usar o cadastro normal. A rejeição exige justificativa interna, preserva a solicitação e não gera comunicação externa.

## Permissões e auditoria

Todas as rotas mutáveis e de consulta interna exigem a capability existente `manage_companies`; os overrides individuais, inclusive deny, continuam soberanos. Ações mutáveis aceitam apenas POST e operações compostas usam transação atômica.

O `AuditEvent` existente registra criação e revisão de solicitação, aprovação, rejeição, criação e vínculo de usuário, ativação, bloqueio e redefinição administrativa de senha. Payloads contêm apenas IDs, estados e motivos internos sanitizados; nunca senha, documento completo, token ou conteúdo de sessão.

## Privacidade, riscos e limitações

Nenhum e-mail é enviado. Nenhuma ativação é automática. Nenhuma Company é criada pela solicitação. O solicitante precisa ser validado por uma pessoa responsável.

O HMAC depende da proteção e estabilidade de `DJANGO_SECRET_KEY`; a rotação do segredo reduz a capacidade de reconhecer repetições antigas, sem expor documentos. O limite por rede pode agrupar pessoas atrás do mesmo NAT, por isso é curto e conservador. Esta fase não envia e-mail, WhatsApp ou SMS, não recupera senha automaticamente, não cria empresas e não constitui prova digital de identidade.

## Rollback

Reverter primeiro os commits da interface e dos serviços. Antes de reverter a migration, exportar e revisar solicitações e vínculos criados após uso operacional. A reversão remove somente os novos campos e a nova tabela, preservando Users e CustomerPortalAccess anteriores, pedidos e fechamentos. Usuários reais criados durante operação não devem ser removidos automaticamente; exigem análise individual antes de qualquer reversão destrutiva.
