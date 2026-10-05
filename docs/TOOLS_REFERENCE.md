# Referência das operações

Cada operação existe como tool MCP e como rota REST, com os mesmos parâmetros e os mesmos defaults. As duas portas são registradas em `src/server.py` (as tools com `@mcp.tool()`, as rotas em `run_http_server`), e a implementação mora em `src/tools/`.

⛔ É ferramenta de desenvolvimento: nada de produção depende destas operações (ver o [README](../README.md)).

| Tool MCP | Rota REST | O que faz |
|---|---|---|
| `db_query` | `POST /api/query` | SELECT |
| `db_execute` | `POST /api/execute` | escrita: DML, DDL e manutenção |
| `db_count` | `GET /api/count` | conta linhas |
| `db_list_tables` | `GET /api/tables` | lista as tabelas de um schema |
| `db_get_schema` | `GET /api/schema` | colunas de uma tabela |
| `db_get_indexes` | `GET /api/indexes` | índices de uma tabela ou de um schema |
| `db_get_stats` | `GET /api/stats` | estatísticas de uma tabela |
| `db_explain` | `POST /api/explain` | plano de execução |
| `db_get_sample` | `GET /api/sample` | amostra de linhas |
| `db_health` | `GET /health` | conexão com o banco (a rota REST responde em outro formato) |

Na REST, os parâmetros vão no corpo JSON (POST) ou na query string (GET), com o nome que têm na tool.

- ⚠️ Passe sempre o `schema`: o default de várias operações é `public`, que está vazio de propósito.
- ⛔ `DELETE`, `TRUNCATE` e `DROP` sobre tabela-espinha são recusados em `db_query`, `db_execute`, `db_count` e `db_explain` (`espinha_guard: true` na resposta), e a recusa diz o caminho certo: a migration. A lista, o porquê e os limites da guarda: [README](../README.md#guarda-de-tabelas-espinha).

---

## Leitura

### db_query — `POST /api/query`

Executa um SELECT.

- `sql` (obrigatório): começa por `SELECT` ou `WITH`; comentário no topo do texto é recusado.
- `limit` (opcional): máximo de linhas (default 1000).

**Retorno:** `success`, `rows`, `columns`, `data`, `execution_time_ms`.

⚠️ **A resposta corta em silêncio.** Sem `LIMIT` no texto, a tool acrescenta `LIMIT <limit>`; com ou sem ele, a leitura para no teto `max_rows`. Nenhum campo avisa que cortou: para contar, agregue no servidor (`count(*)`), e ao paginar confira o total contra um `count(*)` na mesma rodada.

```
db_query("SELECT cnpj_basico, razao_social FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
```

### db_count — `GET /api/count`

- `table` (obrigatório): `schema.tabela`.
- `where` (opcional): a cláusula sem a palavra `WHERE`, concatenada crua no SQL.

**Retorno:** `success`, `table`, `count`, `where`, `execution_time_ms`.

É um `COUNT(*)` exato: em tabela grande pode estourar o timeout. A estimativa barata é o `estimated_rows` do `db_list_tables`.

```
db_count("cnpj_raw.estabelecimentos", "situacao_cadastral = '02'")
```

### db_list_tables — `GET /api/tables`

- `schema` (opcional, default `public`).

**Retorno:** `success`, `schema`, `total_tables` e, por tabela, `table_name`, `size`, `estimated_rows`, `estimated_rows_as_of` e `live_tup_since_stats_reset`.

O `estimated_rows` vem do `pg_class.reltuples`, que sobrevive a um restart do cluster e vale até o último analyze (`estimated_rows_as_of`). O `live_tup_since_stats_reset` é contador do coletor de estatísticas e zera quando o cluster perde as estatísticas (num crash, por exemplo): ⛔ não o use para provar que uma tabela está vazia.

### db_get_schema — `GET /api/schema`

- `table` (obrigatório): o nome sem o schema.
- `schema` (opcional, default `public`).

**Retorno:** `success`, `full_name`, `row_count` e `columns` (`name`, `type`, `nullable`, `default`, `max_length`).

O `row_count` é um `COUNT(*)` exato: em tabela grande, a chamada pode estourar o timeout.

### db_get_indexes — `GET /api/indexes`

- `table` (opcional): filtra por tabela.
- `schema` (opcional, default `cnpj_raw`).

**Retorno:** `success`, `schema`, `table`, `total_indexes` e, por índice, `table_name`, `index_name`, `size`, `index_type` e `definition`.

### db_get_stats — `GET /api/stats`

- `table` (obrigatório): o nome sem o schema.
- `schema` (opcional, default `cnpj_raw`).

**Retorno:** `success`, `full_name`, `row_count` (um `COUNT(*)` exato), `estimated_live_rows`, `dead_rows`, `modifications_since_analyze`, `size` (`total`, `table`, `indexes`) e `maintenance` (último vacuum e último analyze, manual e automático).

`estimated_live_rows`, `dead_rows` e `modifications_since_analyze` são contadores do coletor de estatísticas: zeram quando o cluster perde as estatísticas.

### db_explain — `POST /api/explain`

- `sql` (obrigatório).
- `analyze` (opcional, default `true`).

**Retorno:** `success`, `analyzed`, `query`, `plan` (as linhas do plano) e `timing` (`planning_time_ms`, `execution_time_ms`, `total_time_ms`).

⚠️ Com `analyze` (o default), o Postgres **executa** o comando, DML inclusive. Nada é commitado, mas efeito não transacional (sequência, advisory lock) fica. Para ver só o plano, `analyze=false`.

### db_get_sample — `GET /api/sample`

- `table` (obrigatório): o nome sem o schema.
- `schema` (opcional, default `public`).
- `limit` (opcional, default 10, teto 100).

**Retorno:** `success`, `full_name`, `rows_returned`, `columns`, `data`.

### db_health — `GET /health`

Sem parâmetros. A tool devolve `success`, `status` e `database_connected`; a rota REST, `status`, `database` e `version`.

---

## Escrita

### db_execute — `POST /api/execute`

- `sql` (obrigatório): começa por um dos verbos de `allowed_operations` em `src/tools/query.py::execute` (DML, DDL, `DO` e a manutenção `VACUUM`, `ANALYZE` e `REINDEX`).
- `allow_mojibake` (opcional, default `false`): libera SQL com a assinatura de mojibake, só para reparo de dado. Não libera a guarda de tabelas-espinha.

**Retorno:** `success`, `rows_affected`, `execution_time_ms`, `message`.

- ⛔ SQL com a assinatura de mojibake (texto UTF-8 relido como CP1252 no cliente) é recusado (`mojibake_guard: true`): componha o não-ASCII com `chr(NNN)`, ou mande o SQL por um cliente com UTF-8 explícito.
- ⛔ `DELETE`, `TRUNCATE` e `DROP` sobre tabela-espinha são recusados (`espinha_guard: true`).
- `VACUUM` e todo comando com `CONCURRENTLY` rodam em autocommit; o resto roda numa transação, desfeita se der erro.
- ⚠️ `VACUUM FULL` e `REINDEX` sem `CONCURRENTLY` bloqueiam a tabela enquanto rodam: em tabela quente, vão por migration.

```
db_execute("INSERT INTO zz_tmp_scratch (col1) VALUES ('valor')")
db_execute("CREATE INDEX CONCURRENTLY idx_nome ON schema.tabela (coluna)")
db_execute("VACUUM (ANALYZE) leads.meritos")
```

---

## Erros

Toda resposta das operações traz `success` e, na falha, `error` com a mensagem. A REST responde 400, só com `error`, quando falta parâmetro obrigatório.

## Limites

Os limites (timeout de query, teto de linhas, pool de conexões e timeout de conexão) são os campos de `src/config.py::Settings`. O timeout de query fica abaixo do `--timeout` do Cloud Run no `cloudbuild.yaml`, para a query morrer junto com o request que a pediu.
