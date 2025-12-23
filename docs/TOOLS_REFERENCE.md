# Referência de Tools

Documentação completa de todas as tools disponíveis no claude-db-tools.

---

## AVISO IMPORTANTE

Estas tools são **exclusivamente para uso do Claude Code** em tarefas de desenvolvimento e debugging.

**NUNCA** crie serviços ou código de produção que dependam destas tools.

---

## Query Tools

### db_query

Executa queries SELECT.

**Parâmetros:**
- `sql` (obrigatório): Query SQL (SELECT ou WITH)
- `limit` (opcional): Máximo de rows (default: 1000, max: 10000)

**Retorno:** JSON com columns, data, rows, execution_time_ms

**Exemplos:**
```
db_query("SELECT * FROM cnpj_raw.empresas LIMIT 10")
db_query("SELECT cnpj_basico, razao_social FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
db_query("SELECT COUNT(*) FROM cnpj_raw.estabelecimentos", limit=1)
```

---

### db_execute

Executa operações de escrita (DDL/DML).

**Parâmetros:**
- `sql` (obrigatório): Statement SQL

**Operações permitidas:** INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, TRUNCATE, GRANT, REVOKE

**Retorno:** JSON com rows_affected, execution_time_ms

**Exemplos:**
```
db_execute("INSERT INTO my_table (col1) VALUES ('value')")
db_execute("UPDATE cnpj_raw.empresas SET processed = true WHERE id = 123")
db_execute("CREATE INDEX idx_name ON table(column)")
db_execute("DELETE FROM temp_table WHERE created_at < NOW() - INTERVAL '7 days'")
```

---

### db_count

Conta rows em uma tabela.

**Parâmetros:**
- `table` (obrigatório): Nome completo da tabela (schema.tabela)
- `where` (opcional): Cláusula WHERE sem a palavra WHERE

**Retorno:** JSON com count, execution_time_ms

**Exemplos:**
```
db_count("cnpj_raw.empresas")
db_count("cnpj_raw.estabelecimentos", "situacao_cadastral = '02'")
db_count("public.users", "active = true AND created_at > '2024-01-01'")
```

---

## Schema Tools

### db_list_tables

Lista tabelas de um schema.

**Parâmetros:**
- `schema` (opcional): Nome do schema (default: "public")

**Retorno:** JSON com lista de tabelas (nome, size, estimated_rows)

**Exemplos:**
```
db_list_tables()                # public schema
db_list_tables("cnpj_raw")      # cnpj_raw schema
```

---

### db_get_schema

Mostra estrutura de uma tabela.

**Parâmetros:**
- `table` (obrigatório): Nome da tabela (sem schema)
- `schema` (opcional): Nome do schema (default: "public")

**Retorno:** JSON com colunas (nome, tipo, nullable, default)

**Exemplos:**
```
db_get_schema("empresas", "cnpj_raw")
db_get_schema("users")
db_get_schema("estabelecimentos", "cnpj_raw")
```

---

### db_get_indexes

Lista índices de uma tabela ou schema.

**Parâmetros:**
- `table` (opcional): Nome da tabela para filtrar
- `schema` (opcional): Nome do schema (default: "cnpj_raw")

**Retorno:** JSON com índices (nome, tabela, tipo, size)

**Exemplos:**
```
db_get_indexes()                          # Todos do cnpj_raw
db_get_indexes("empresas")                # Só da tabela empresas
db_get_indexes(schema="public")           # Todos do public
```

---

## Stats Tools

### db_get_stats

Estatísticas detalhadas de uma tabela.

**Parâmetros:**
- `table` (obrigatório): Nome da tabela (sem schema)
- `schema` (opcional): Nome do schema (default: "cnpj_raw")

**Retorno:** JSON com row_count, dead_rows, size, last_vacuum, last_analyze

**Exemplos:**
```
db_get_stats("empresas")
db_get_stats("estabelecimentos")
db_get_stats("users", "public")
```

---

### db_explain

Analisa performance de uma query com EXPLAIN ANALYZE.

**Parâmetros:**
- `sql` (obrigatório): Query SQL para analisar
- `analyze` (opcional): Se deve executar a query (default: true)

**Retorno:** JSON com query_plan, planning_time_ms, execution_time_ms

**Exemplos:**
```
db_explain("SELECT * FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
db_explain("SELECT * FROM large_table", analyze=false)  # Só plano, sem executar
```

---

## Sample Tools

### db_get_sample

Amostra de dados de uma tabela.

**Parâmetros:**
- `table` (obrigatório): Nome da tabela (sem schema)
- `schema` (opcional): Nome do schema (default: "public")
- `limit` (opcional): Número de rows (default: 10, max: 100)

**Retorno:** JSON com columns, data

**Exemplos:**
```
db_get_sample("empresas", "cnpj_raw")
db_get_sample("users", limit=5)
db_get_sample("estabelecimentos", "cnpj_raw", 50)
```

---

## Health Tool

### db_health

Verifica saúde da conexão com o banco.

**Parâmetros:** Nenhum

**Retorno:** JSON com status, database_connected

**Exemplo:**
```
db_health()
```

---

## Limites e Timeouts

| Limite | Valor | Descrição |
|--------|-------|-----------|
| Query timeout | 5 min | Tempo máximo de execução |
| Max rows | 10.000 | Máximo de linhas retornadas |
| Pool connections | 25 | Máximo de conexões simultâneas |
| Connect timeout | 10s | Timeout de conexão |

---

## Tratamento de Erros

Todas as tools retornam JSON com estrutura consistente:

**Sucesso:**
```json
{
  "success": true,
  "data": [...],
  ...
}
```

**Erro:**
```json
{
  "success": false,
  "error": "Mensagem de erro"
}
```
