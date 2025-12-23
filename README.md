# claude-db-tools

MCP Server para acesso ao PostgreSQL - Ferramentas para o Claude Code interagir com bancos Cloud SQL.

---

## Para AI Agents (Claude, GPT, etc.)

### Acesso Rápido via REST API

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
| `401 Unauthorized` | Token inválido ou expirado | Peça ao usuário para executar: `gcloud auth login` |
| `403 Forbidden` | Usuário sem permissão | Usuário precisa ter acesso ao projeto `neqsti` no GCP |
| `Connection timeout` | Proxy corporativa bloqueando | Peça ao usuário verificar configurações de proxy |
| `Could not resolve host` | DNS/Rede | Verificar conexão com internet |

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
| `/health` | GET | Health check |

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

- `cnpj_raw` - Dados brutos da Receita Federal (empresas, estabelecimentos)
- `public` - Tabelas gerais

### Banco de Dados

- **Tipo:** PostgreSQL 15
- **Instância:** Cloud SQL (GCP)
- **Projeto:** neqsti

---

## IMPORTANTE: USO EXCLUSIVO PARA DESENVOLVIMENTO

Este serviço é uma **ferramenta de desenvolvimento exclusiva para Claude Code**.

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

## Instalação (MCP Protocol)

### 1. Clonar e instalar dependências

```bash
cd c:\Users\Eltonxp\dev\Garantis\claude-db-tools
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Editar .env com as credenciais corretas
```

### 3. Adicionar ao Claude Code

```bash
claude mcp add claude-db-tools \
  --transport stdio \
  --env DB_HOST=172.17.0.5 \
  --env DB_NAME=cnpj_database \
  --env DB_USER=postgres \
  --env DB_PASSWORD=<sua_senha> \
  -- python c:\Users\Eltonxp\dev\Garantis\claude-db-tools\src\server.py
```

### 4. Verificar instalação

```bash
claude /mcp
# Deve mostrar claude-db-tools na lista de servidores
```

---

## MCP Tools Disponíveis

| Tool | Descrição |
|------|-----------|
| `db_query` | Executa SELECT queries |
| `db_execute` | Executa INSERT/UPDATE/DELETE/DDL |
| `db_count` | Conta rows com WHERE opcional |
| `db_list_tables` | Lista tabelas de um schema |
| `db_get_schema` | Mostra colunas de uma tabela |
| `db_get_indexes` | Lista índices |
| `db_get_stats` | Estatísticas de tabela |
| `db_explain` | EXPLAIN ANALYZE de queries |
| `db_get_sample` | Amostra de dados |
| `db_health` | Verifica conexão |

---

## Exemplos de Uso (linguagem natural)

Após configurar, você pode pedir ao Claude:

```
> Liste as tabelas do schema cnpj_raw
> Quantas empresas temos cadastradas?
> Me mostra o schema da tabela estabelecimentos
> SELECT * FROM cnpj_raw.empresas WHERE razao_social ILIKE '%garantis%' LIMIT 5
> Analise a performance dessa query: SELECT ...
```

O Claude usará automaticamente as tools apropriadas.

---

## Estrutura do Projeto

```
claude-db-tools/
├── src/
│   ├── server.py          # Entry point MCP + REST API
│   ├── config.py          # Configurações
│   ├── database.py        # Connection pooling
│   └── tools/             # Tools MCP
│       ├── query.py       # query, execute, count
│       ├── schema.py      # list_tables, get_schema, get_indexes
│       ├── stats.py       # get_stats, explain_query
│       └── sample.py      # get_sample
├── docs/                  # Documentação adicional
├── Dockerfile
├── cloudbuild.yaml        # Deploy para Cloud Run
├── requirements.txt
└── pyproject.toml
```

---

## Configuração

| Variável | Default | Descrição |
|----------|---------|-----------|
| `DB_HOST` | 172.17.0.5 | Host do PostgreSQL |
| `DB_PORT` | 5432 | Porta |
| `DB_NAME` | cnpj_database | Nome do banco |
| `DB_USER` | postgres | Usuário |
| `DB_PASSWORD` | (obrigatório) | Senha |
| `QUERY_TIMEOUT` | 300 | Timeout em segundos |
| `MAX_ROWS` | 10000 | Máximo de rows retornadas |

---

## Deploy

```bash
# Deploy para Cloud Run
gcloud builds submit --config=cloudbuild.yaml --project=neqsti
```

---

## Desenvolvimento

```bash
# Instalar deps de desenvolvimento
pip install -r requirements-dev.txt

# Rodar testes
pytest

# Rodar servidor localmente
python -m src.server
```

---

## Licença

MIT - Apenas para uso interno da Garantis.
