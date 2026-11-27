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

## Profissão e nível (CSV novo do HUD)
- Faça upload do CSV exportado na aba Alliance Intel -> Members.
- As colunas `Profissão (código)` e `Nível profissão` são importadas e exibidas.
- Filtre por profissão na aba Jogadores ou pergunte no chat:
  - `Quantos jogadores da profissão tipo 2?`
  - `Quem tem o maior nível de profissão?`
  - `Qual a profissão de Alice?`
  - `Quantos por profissão?`
- A IA apenas interpreta perguntas; os cálculos são locais com o CSV.
- Mapeamento confirmado pelo administrador:
  - `Tipo 101` = Engenheiro (Engineer).
  - `Tipo 102` = War Leader.
- Os nomes são mostrados no idioma selecionado, preservando o código entre parênteses.
- Outros códigos permanecem numéricos, sem adivinhação.
- O CSV não é alterado nem publicado no GitHub.
- CSVs antigos sem essas colunas continuam aceitos e mostram valores vazios.
- UID é usado apenas para deduplicação na importação e é descartado antes
  de disponibilizar os dados no portal.
- Testes locais opcionais, sem GitHub Actions: `cd alliance-intel && python -m unittest test_career -v`.

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


## DS Intel (optional)

The portal now has a DS Intel section after login, even without an Alliance CSV upload. Existing CSV and Groq features are unchanged. DS reads only the scoped Supabase RPC `lw_ds_read`, via a dedicated read-only Auth user. Configure private Streamlit Secrets:

```toml
DS_ACCESS_PASSWORD = "separate-long-access-code"
DS_SUPABASE_URL = "https://PROJECT.supabase.co"
DS_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_..."
DS_READ_EMAIL = "reader@example.com"
DS_READ_PASSWORD = "separate-reader-password"
```

Never commit actual credentials. DS access password must differ from ACCESS_PASSWORD and ADMIN_PASSWORD, and be at least 12 characters. Do not use a service-role key. Execute the LWHUD database setup and explicit reader/collector grants first. DS rosters and rival hypotheses are captured by the HUD, cached for 60 seconds, and removed weekly in the database. Draft plans are session-local, not official/shared. PNG in EN/PT/TR/ZH and CSV are generated deterministically, without Groq. Web CSV player IDs are match-specific pseudonyms. The map is an original schematic based on the classic arrangement, not an exact game screenshot. The CJK fonts are installed via packages.txt; for local testing install fonts-noto-cjk, fonts-noto-core, fonts-dejavu-core on Linux or Microsoft YaHei on Windows.

Desktop/web planner source is identical; copy ds_intel.py and ds_intel_render.py from LWHUD when updating either. No live Supabase integration test is possible until the owner executes setup and configures the reader.
