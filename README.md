# claude-db-tools

MCP Server para acesso ao PostgreSQL - Ferramentas para o Claude Code interagir com bancos Cloud SQL.

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

## Instalação

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

## Tools Disponíveis

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

## Exemplos de Uso

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
│   ├── server.py          # Entry point MCP
│   ├── config.py          # Configurações
│   ├── database.py        # Connection pooling
│   └── tools/             # Tools MCP
│       ├── query.py       # query, execute, count
│       ├── schema.py      # list_tables, get_schema, get_indexes
│       ├── stats.py       # get_stats, explain_query
│       └── sample.py      # get_sample
├── docs/                  # Documentação adicional
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
