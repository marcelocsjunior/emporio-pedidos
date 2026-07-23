# EMP-CUSTOMER-ACCESS-MANAGERS-01

## Decisão operacional

Somente os usuários ativos `angela`, `suporte` e `ti` podem administrar acessos dos clientes.

A autorização é nominal e independe do perfil funcional. Administradores, Gerência, Comercial, Produção ou qualquer outro perfil não recebem essa autorização por herança.

## Operações protegidas

- consultar acessos dos clientes;
- criar usuário de cliente;
- vincular usuário existente a uma empresa;
- ativar ou bloquear acesso;
- redefinir senha;
- consultar e revisar o histórico da fila de solicitações.

## Segurança

- a lista é fechada e comparada de forma normalizada pelo nome de usuário;
- usuários inativos são bloqueados;
- possuir `manage_companies`, ser staff ou pertencer a um grupo administrativo não contorna a política;
- os itens administrativos ficam ocultos no menu para pessoas não designadas;
- todas as rotas protegidas usam o mesmo mixin de autorização;
- não há migration nem alteração de schema.

## Implantação

A implantação autorizada é somente na VM NBBIO `srvenp`, IP `192.168.88.121`, porta `8020`. A VPS externa permanece fora do escopo.

## Rollback

Retorne ao SHA anterior da aplicação. Nenhuma restauração de banco é necessária.
