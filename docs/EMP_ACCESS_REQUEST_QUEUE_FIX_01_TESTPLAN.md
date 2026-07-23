# Plano de validação

1. Enviar uma solicitação pública válida e confirmar criação imediata na fila.
2. Repetir os mesmos dados em até 24 horas e confirmar ausência de duplicação com mensagem explícita.
3. Enviar solicitações de documentos diferentes pelo mesmo IP e confirmar que todas são registradas.
4. Exceder cinco envios do mesmo documento e IP em uma hora e confirmar bloqueio apenas dessa identidade.
5. Rejeitar uma solicitação e reenviar os mesmos dados, confirmando a criação de nova entrada pendente.
6. Filtrar a fila por empresa antes do vínculo e confirmar exibição por correspondência do documento protegido.
7. Confirmar persistência visual dos filtros e funcionamento de Limpar filtros.
8. Executar check, makemigrations --check, suíte customer_portal e Ruff.
