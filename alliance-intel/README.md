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

The portal now has a DS Intel section after login, even without an Alliance CSV upload. Existing CSV and Groq features are unchanged. DS uses a dedicated, read-only PostgreSQL login through the Supabase Session pooler. No Authentication user is required. First execute the existing LWHUD `ds_intel_cloud_setup.sql`, then `ds_reader_setup.sql` in this directory; it returns a randomly generated reader password. In Supabase Connect > Session pooler, copy the exact host and use the generated reader username/password in the single private Streamlit secret:

```toml
DS_DATABASE_URL = "postgresql://lw_ds_streamlit_reader.PROJECT_REF:GENERATED_PASSWORD@POOLER_HOST:5432/postgres"
```

The reader is restricted by RLS to NWG server 1512, current matches, and explicit column grants. The SQL script must be adapted deliberately for a different alliance. Existing installations may optionally keep the former Auth RPC reader configuration instead, without setting DS_DATABASE_URL:

```toml
DS_SUPABASE_URL = "https://PROJECT.supabase.co"
DS_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_..."
DS_READ_EMAIL = "reader@example.com"
DS_READ_PASSWORD = "separate-reader-password"
```

Never commit actual credentials. DS Intel uses the existing ACCESS_PASSWORD portal login; visitors do not need Supabase accounts or a second access code. The dedicated reader credentials stay in server-side Streamlit Secrets. Do not use a service-role key. Execute the LWHUD database setup and authorize the actual desktop collector separately. Do not grant DS publication to an unverified installation. For the database login route, the new reader SQL replaces the reader portion of the former Auth grant script. DS rosters and rival hypotheses are captured by the HUD, cached for 60 seconds, and removed weekly in the database. Draft plans are session-local, not official/shared. PNG in EN/PT/TR/ZH and CSV are generated deterministically, without Groq. Web CSV player IDs are match-specific pseudonyms. The map is an original schematic based on the classic arrangement, not an exact game screenshot. The CJK fonts are installed via packages.txt; for local testing install fonts-noto-cjk, fonts-noto-core, fonts-dejavu-core on Linux or Microsoft YaHei on Windows.

Desktop/web planner source is identical; copy ds_intel.py and ds_intel_render.py from LWHUD when updating either. No live Supabase integration test is possible until the owner executes setup and configures the reader.

The PostgreSQL reader obtains Supabase's hosted root CA once per process using authenticated HTTPS from the official Supabase Studio certificate download URL. It uses a temporary CA file for psycopg with `sslmode=verify-full` (certificate and hostname verification). No additional secret is required. If the CA download or validation fails, the reader refuses the database connection; it does not fall back to unverified SSL.
