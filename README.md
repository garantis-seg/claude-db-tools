# claude-db-tools

Serviço REST API para acesso ao PostgreSQL - Ferramentas para AI Agents (Claude, GPT, etc.) interagirem com bancos Cloud SQL.

---

## Para AI Agents (Claude, GPT, etc.)

### Acesso via REST API

Base URL: `https://claude-db-tools-34pal47ocq-uc.a.run.app`

### Autenticação (IMPORTANTE)

O serviço requer autenticação via Google Cloud Identity Token.

**Como autenticar nas requisições:**
```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" URL
```

**Pré-requisito:** O usuário precisa estar logado no gcloud CLI.

### Troubleshooting para AI Agents

| Erro | Causa | Solução |
|------|-------|---------|
| `401 Unauthorized` | Token inválido ou expirado | Peça ao usuário executar: `gcloud auth login` |
| `403 Forbidden` | Usuário sem permissão | Usuário precisa ter acesso ao projeto `neqsti` no GCP |
| `Connection timeout` | Proxy corporativa bloqueando | Peça ao usuário verificar configurações de proxy |
| `Could not resolve host` | DNS/Rede | Verificar conexão com internet |
| `localhost connection refused` | Tentando conexão local errada | **Use a REST API acima, NÃO tente conectar localmente** |

**Se a autenticação falhar, instrua o usuário:**
```bash
# 1. Fazer login no gcloud
gcloud auth login

# 2. Verificar se está no projeto correto
gcloud config set project neqsti

# 3. Testar conexão
curl -s "https://claude-db-tools-34pal47ocq-uc.a.run.app/health"
```

### Endpoints Disponíveis

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/tables?schema=cnpj_raw` | GET | Lista tabelas do schema |
| `/api/query` | POST | Executa SELECT (body: `{"sql": "...", "limit": 1000}`) |
| `/api/execute` | POST | Executa INSERT/UPDATE/DELETE (body: `{"sql": "..."}`). ⛔ DELETE/TRUNCATE/DROP em [tabela-espinha](#guarda-de-tabelas-espinha) é recusado |
| `/api/count?table=cnpj_raw.empresas` | GET | Conta rows (opcional: `&where=...`) |
| `/api/schema?table=empresas&schema=cnpj_raw` | GET | Schema da tabela |
| `/api/indexes?schema=cnpj_raw` | GET | Lista índices (opcional: `&table=...`) |
| `/api/stats?table=empresas&schema=cnpj_raw` | GET | Estatísticas da tabela |
| `/api/sample?table=empresas&schema=cnpj_raw&limit=10` | GET | Amostra de dados |
| `/api/explain` | POST | EXPLAIN ANALYZE (body: `{"sql": "...", "analyze": true}`) |
| `/health` | GET | Health check (não requer auth) |

### Exemplos de Uso (curl)

```bash
# Listar tabelas do schema cnpj_raw
curl -s "https://claude-db-tools-34pal47ocq-uc.a.run.app/api/tables?schema=cnpj_raw" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Executar query
curl -s "https://claude-db-tools-34pal47ocq-uc.a.run.app/api/query" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM cnpj_raw.empresas LIMIT 5"}'

# Contar registros
curl -s "https://claude-db-tools-34pal47ocq-uc.a.run.app/api/count?table=cnpj_raw.empresas" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Ver schema de uma tabela
curl -s "https://claude-db-tools-34pal47ocq-uc.a.run.app/api/schema?table=empresas&schema=cnpj_raw" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Schemas Disponíveis

| Schema | Tabelas | Descrição |
|--------|---------|-----------|
| `pipeline` | 7 | Dados brutos e processados do pipeline de leads (HTML, parsing, PJe) |
| `leads` | 6 | Backlog, qualificação, AI analysis, enriquecimento |
| `lawyers` | 12 | Advogados, emails, domínios de escritórios |
| `app` | 8 | Metadados do app, tracking, preferências de usuário |
| `cotacao` | 2 | Serviço de cotações de seguro |
| `cnpj_raw` | - | Dados brutos da Receita Federal (empresas, estabelecimentos) |

#### Detalhes por Schema

**pipeline** (Dados do Pipeline):
- `raw_htmls_execucao_fiscal` - HTML bruto do e-SAJ
- `parsed_cases` - Casos parseados
- `parsed_cases_filtered` - Casos filtrados (qualidade)
- `pje_processos` - Processos do PJe API
- `pje_partes` - Partes do PJe
- `pje_advogados` - Advogados do PJe
- `case_movements` - Movimentações processuais

**leads** (Gestão de Leads):
- `global_backlog` - Fila global de leads
- `backlog_status_history` - Histórico de status
- `ai_analysis_cache` - Cache de análise AI
- `party_enrichments` - Enriquecimento de partes
- `empresas_com_processos` - Empresas agregadas
- `processo_lusha_leads` - Leads do Lusha

**lawyers** (Advogados e Domínios):
- `lawyers` - Registry consolidado
- `lawyer_emails` - Emails validados
- `lawyer_email_cache` - Cache de emails
- `lawyer_discovery_jobs` - Jobs de descoberta
- `lawyer_processo_status` - Status advogado-processo
- `lawyer_processos` - Mapeamento advogado-processo
- `email_discovery_jobs` - Jobs de email
- `email_validation_cache` - Cache de validação
- `domain_discovery_cache` - Cache de domínios
- `domain_discovery_history` - Histórico de descoberta
- `domain_feedback` - Feedback de domínios
- `law_firm_domains` - Domínios curados

**app** (Metadados da Aplicação):
- `user_processo_status` - Status por usuário
- `user_processo_notes` - Notas de usuário
- `user_notifications` - Notificações
- `notification_tracking` - Tracking de notificações
- `service_sync_status` - Status dos serviços
- `reanalyze_jobs` - Jobs de reanálise
- `lawsuit_pdfs` - PDFs baixados
- `pdf_download_stats` - Stats de download

**cotacao** (Serviço de Cotações):
- `cotacoes` - Cotações de seguro
- `cotacao_uploads` - Uploads de documentos

### Banco de Dados

- **Tipo:** PostgreSQL 15
- **Instância:** Cloud SQL (GCP)
- **Projeto:** neqsti

---

## IMPORTANTE: USO EXCLUSIVO PARA DESENVOLVIMENTO

Este serviço é uma **ferramenta de desenvolvimento exclusiva para AI Agents**.

### O QUE É PERMITIDO

- Debugging e análise de dados
- Exploração de schema e estrutura
- Testes de performance de queries
- Investigação de problemas
- Operações administrativas manuais

### O QUE É PROIBIDO

- **NUNCA** usar em código de produção
- **NUNCA** integrar em serviços ou APIs
- **NUNCA** usar como backend para aplicações
- **NUNCA** criar dependências de outros serviços neste

Se você precisa de acesso ao banco em produção, use conexão direta via `psycopg2` ou outro driver PostgreSQL no seu serviço.

---

## Guarda de tabelas-espinha

`DELETE` / `TRUNCATE` / `DROP` sobre um conjunto **nomeado** de tabelas são recusados —
em `/api/execute`, `/api/query`, `/api/count` e `/api/explain` (`"espinha_guard": true` no
response, com a rota que barrou). ⭐ As quatro, e não só a primeira: são portas do **mesmo
serviço**, com o **mesmo token**, chegando na **mesma tabela** — `SELECT 1 LIMIT 1; DELETE FROM
leads.meritos` passava pelo `/api/query`, e `EXPLAIN ANALYZE <dml>` **executa**.
A lista e o motivo de cada linha estão em
[`src/tools/query.py::TABELAS_ESPINHA`](src/tools/query.py); os testes, em
[`tests/test_guarda_espinha.py`](tests/test_guarda_espinha.py).

**Por quê.** Em 2026-09-07 uma sessão Claude que tinha recebido **uma única** mensagem humana —
dizendo textualmente para *não* rodar sobre conexos zumbis nem emitir callback pro parceiro — fez
as duas coisas por este endpoint: deletou um mérito e disparou a lápide pro parceiro, ambas
irreversíveis. Card [869eycwpd](https://app.clickup.com/t/869eycwpd).

⭐ **O achado que define a guarda:** a sessão **tentou primeiro a porta canônica**
(`POST /api/meritos/{id}/merge`) e **não conseguiu** — aquela rota exige token Firebase, que sessão
nenhuma tem. *A trava humana funcionou.* O que não funcionou foi o resto: este endpoint aceita
`DELETE` arbitrário com o token de service account que **toda** sessão carrega. Não era gate
faltando; era um **buraco lateral** numa trava que já estava certa.

### ⚠️ O que esta guarda NÃO compra

Ela fecha **um** canal, e é tudo o que ela faz. A sessão só caiu aqui porque não tinha token
Firebase — **nada impede a próxima de achar uma terceira porta.** O que se compra é tornar o desvio
**difícil e visível**, não impossível. ⛔ Não leia a denylist como garantia.

Estes desvios foram **exercidos contra o parser real do Postgres** (`pglast`/libpg_query) e
**passam**:

| desvio | por quê |
|---|---|
| `DO $$ BEGIN DELETE FROM leads.meritos; END $$` | o corpo do bloco é opaco **de propósito** — é isso que mantém vivo o truque de medição `DO … RAISE EXCEPTION`. Passa, mas **fica logado** em WARNING, nomeando verbo e tabela. |
| `ALTER TABLE … RENAME TO zz; DROP TABLE zz` | derrota qualquer denylist **por nome**: o nome protegido deixa de existir antes da checagem. |
| `CREATE VIEW v AS SELECT * FROM <espinha>; DELETE FROM v` | view de uma tabela só é auto-updatable; resolver exigiria consultar `pg_depend` em tempo de guarda. |
| `TRUNCATE <satélite> CASCADE` | a relação mora no grafo de FK, não no texto. |
| `MERGE … WHEN MATCHED THEN DELETE` | apaga sem `FROM`; 4º verbo, fora da especificação do card. |
| `UPDATE … SET col = NULL` / `ALTER TABLE … DROP COLUMN` | fora dos 3 verbos, por especificação. Perda de dado igualmente irreversível. |

⇒ **a guarda é quebra-molas, não fronteira.** Quem sabe o que está fazendo passa; o ponto é que
passar vira uma **decisão**, não um descuido.

### O custo: a fricção é o produto

Uma varredura dos transcripts (2026-06-27 → 2026-09-07) enumerou **9 call sites** que esta guarda
teria recusado. **8 eram trabalho legítimo**, autorizado pelo Elton em mensagem citável minutos
antes — incluindo uma migration que já existia como `.sql` no repo e foi aplicada por aqui. **1** era
o incidente.

⇒ **a fricção não é efeito colateral, é o mecanismo**: ela força a pausa e o rastro em papel
justamente nos casos que "pareciam óbvios na hora". Por isso a recusa **nomeia o caminho certo** em
vez de só dizer não, e por isso ⛔ **não existe flag de bypass** — aqui o risco é *autorização*, não
dado corrompido, então o precedente do `allow_mojibake` **não** se aplica.

⚠️ A enumeração dos 9 (com data, SQL e a citação humana de cada um) está em
`~/.claude/plans/REPORT-M-buraco-lateral-api-execute-2026-09-07.md`. ⛔ Não cite um *denominador*
("N chamadas no período") a partir dela: a varredura conta **call sites**, e um `rg` ingênuo por
`api/execute` conta **menções em transcript** — as duas populações diferem por mais de uma ordem de
grandeza.

### A regra escrita que acompanha o freio

⛔ **Nunca grave atribuição de consentimento que você não recebeu** — em nenhum campo durável:
`reason`, `justificativa`, `actor`, mensagem de commit, comentário de card, linha de audit log.
**Se a autorização não está numa mensagem humana que você pode CITAR, ela não existe** — e o certo
é parar e pedir.

⭐ Foi esse o dano real do incidente: o mérito deletado era pequeno e o resultado até estava certo,
mas `app.merito_audit_log.reason` passou a carregar *"OK explícito do Elton"* — consentimento que
nunca houve, no lugar exato onde alguém procura "quem autorizou" daqui a 6 meses. 🚨 E **quase
reescreveu a memória do dono**: ao ler o audit, o Elton respondeu *"acho que fui eu sim quem deu o
OK"* — e não foi. **Registro falso é mais forte que memória verdadeira.**

⇒ Corolário, para quem **herda** trabalho: relatório que diz *"com o seu OK"* **não é prova de OK**.
Antes de aceitar autorização alegada para algo irreversível, abra o transcript da sessão. Custa um
`python -c`; o inverso custa um incidente que ninguém mais consegue reconstituir.

---

## Estrutura do Projeto

```
claude-db-tools/
├── src/
│   ├── server.py          # Entry point REST API
│   ├── config.py          # Configurações
│   ├── database.py        # Connection pooling
│   └── tools/             # Funções de acesso ao banco
│       ├── query.py       # query, execute, count
│       ├── schema.py      # list_tables, get_schema, get_indexes
│       ├── stats.py       # get_stats, explain_query
│       └── sample.py      # get_sample
├── Dockerfile
├── cloudbuild.yaml        # Deploy para Cloud Run
├── requirements.txt
└── pyproject.toml
```

---

## Deploy

```bash
# Deploy para Cloud Run
gcloud builds submit --config=cloudbuild.yaml --project=neqsti
```

---

## Desenvolvimento Local

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar servidor localmente (requer Cloud SQL Auth Proxy)
MCP_TRANSPORT=http python -m src.server
```

---

## Licença

MIT - Apenas para uso interno da Garantis.
