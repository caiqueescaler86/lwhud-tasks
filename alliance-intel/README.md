# Alliance Intel — site temporario

Este aplicativo Streamlit vive numa pasta independente do site de tarefas. O GitHub hospeda somente o codigo (sem CSV, UID, senha ou chave Groq). Nao faz consultas ao Supabase.

## Colocar no ar (uma vez)

1. Abra https://share.streamlit.io e entre com sua conta GitHub.
2. Clique em **Create app / Deploy**. Escolha repositorio `caiqueescaler86/lwhud-tasks`, branch `main`, arquivo `alliance-intel/streamlit_app.py`. Publique como app **public**: o app pede codigo proprio, sem email aos convidados.
3. Em **Advanced settings -> Secrets** (ou App settings -> Secrets), informe os valores escolhidos:

```toml
ACCESS_PASSWORD = "COLOQUE-UM-CODIGO-LONGO-PARA-ALIANCA"
ADMIN_PASSWORD = "COLOQUE-OUTRA-SENHA-APENAS-SUA"
GROQ_API_KEY = "SUA-CHAVE-DO-GROQ"
```

4. Abra seu site, entre com `ACCESS_PASSWORD`; na barra lateral informe `ADMIN_PASSWORD` e envie o CSV exportado no Alliance Intel. Compartilhe so o link e o codigo de acesso com a alianca.

## Limitacoes importantes

- O repositorio e PUBLICO. NUNCA commit CSV, senhas, chaves ou `.streamlit/secrets.toml`.
- O upload fica em memoria compartilhada; depois de reiniciar a instancia, voce precisara enviar o CSV novamente.
- A senha compartilhada pode ser repassada; nao e autenticacao individual.
- O Groq recebe a pergunta, mas nao recebe dados de jogadores: interpreta uma consulta predefinida e o Python calcula as respostas. Nao executa scripts/SQL de nenhum tipo.
- Ha limites de tamanho do upload e consultas para reduzir abuso. Sem protecao absoluta contra ataques ou abusos de cota.
- Nao e necessario criar GitHub Actions ou modificar o site de tarefas.
