# Alliance Intel (temporario)

Site Streamlit sem consulta a Supabase e sem acesso ao computador de ninguem.

## Publicar / atualizar
- App: `alliance-intel/streamlit_app.py` neste repositorio.
- Streamlit Secrets obrigatorios: `ACCESS_PASSWORD` (12+ caracteres), `ADMIN_PASSWORD` (diferente) e `GROQ_API_KEY`.
- Opcional: `GROQ_MODEL = "openai/gpt-oss-20b"`. Modelos previstos: `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`.
- No site: informe ACCESS_PASSWORD, abra **CSV** (canto superior direito), digite ADMIN_PASSWORD e envie o CSV exportado do Alliance Intel.

## Interface
- Tela principal: chat IA.
- Aba Jogadores: busca, filtro por cargo e colunas essenciais.
- Seletor de idioma: PT / EN / ZH simplificado / TR.
- 6 equipes equilibradas por poder podem ser geradas mesmo sem Groq.
- O admin pode clicar em **Testar Groq** dentro de **CSV** para ver o codigo de erro.
- Respostas de calculo sao geradas localmente: Groq recebe somente a pergunta, nunca os jogadores.

## Erro Groq 403
403 significa acesso negado; pode ser bloqueio do modelo nas permissões da conta/projeto.
Use o botao **Testar Groq** para receber o codigo especifico.
Confira https://console.groq.com/settings/limits e os limites de gastos.
Uma troca de modelo so ajuda se o novo estiver permitido no seu projeto.
Nao ha como confirmar a autorizacao sem a chave configurada no proprio Streamlit.

## Privacidade e limites
- Nao adicione CSV, UID, senha, chave Groq ou Secrets ao GitHub. Este repositorio e publico.
- UID e excluido na ingestao; dados ficam em memoria na instancia Streamlit.
- O upload nao e persistente. Apos reiniciar o site, o administrador deve enviar outro CSV.
- Uma senha de acesso compartilhada pode ser repassada. E um sistema temporario, sem contas individuais.
- Entrada do CSV e perguntas nunca sao executadas como SQL ou Python.
- Nenhuma GitHub Action, novo banco ou infraestrutura adicional e necessaria.
