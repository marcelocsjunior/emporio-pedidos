# EMP-CUSTOMER-ACCESS-MANAGERS-SAFE-02

## Objetivo

Aplicar a política nominal de administração de acessos dos clientes sem depender de senha, sessão HTTP ou existência prévia da conta `suporte`.

## Política

Somente usuários ativos com os nomes normalizados `angela`, `suporte` e `ti` podem:

- criar usuários de clientes;
- vincular usuários às empresas;
- ativar ou bloquear acessos;
- redefinir senhas;
- consultar e revisar o histórico da fila.

Perfis, grupos, `staff`, superusuário e a capability `manage_companies` não concedem essa autorização a outros usuários.

## Validação segura

O comando abaixo é somente leitura:

```bash
python manage.py verify_customer_access_policy
```

Ele valida diretamente o backend e não realiza requisições HTTP. Isso evita interpretar como falha de autorização o redirecionamento legítimo para troca obrigatória de senha.

Regras operacionais da validação:

- `angela` e `ti` devem existir e estar ativos;
- `suporte` pode ainda não existir;
- quando `suporte` for criado e ativado, receberá a autorização nominal automaticamente;
- usuários designados inativos continuam bloqueados;
- nenhuma linha é criada, alterada ou removida no banco.

## Implantação NBBIO

A implantação parte exclusivamente do SHA restaurado `79585ee98bc6eda14cefc034cb4f1b63b082e485`, na VM `srvenp`, IP `192.168.88.121`, porta `8020`.

O pacote deve:

1. validar host, IP, serviços, health e SHA ativo;
2. validar o baseline dos arquivos operacionais;
3. criar backup dos arquivos e `pg_dump`;
4. aplicar somente a política e o comando de verificação;
5. reconstruir apenas `web` e `worker`;
6. executar `check`, migrations pendentes, health e o verificador read-only;
7. registrar o novo SHA somente após sucesso completo;
8. restaurar fonte e imagens anteriores automaticamente em qualquer falha.

A VPS externa permanece fora do escopo.
