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
| `/api/execute` | POST | Executa INSERT/UPDATE/DELETE (body: `{"sql": "..."}`) |
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
