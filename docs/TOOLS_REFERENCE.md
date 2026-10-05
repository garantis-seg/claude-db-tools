# Referência das rotas

Cada operação é uma rota REST, registrada em `src/server.py` (`run_http_server`), e a implementação mora em `src/tools/`. A autenticação e os exemplos com `curl` estão no [README](../README.md).

⛔ É ferramenta de desenvolvimento: nada de produção depende destas rotas (ver o [README](../README.md)).

| Rota | O que faz |
|---|---|
| `POST /api/query` | SELECT |
| `POST /api/execute` | escrita: DML, DDL e manutenção |
| `GET /api/count` | conta linhas |
| `GET /api/tables` | lista as tabelas de um schema |
| `GET /api/schema` | colunas de uma tabela |
| `GET /api/indexes` | índices de uma tabela ou de um schema |
| `GET /api/stats` | estatísticas de uma tabela |
| `POST /api/explain` | plano de execução |
| `GET /api/sample` | amostra de linhas |
| `GET /health` (e `GET /`) | conexão com o banco |

Os parâmetros vão no corpo JSON (POST) ou na query string (GET).

- ⚠️ Passe sempre o `schema`: o default de várias rotas é `public`, que está vazio de propósito.
- ⛔ `DELETE`, `TRUNCATE` e `DROP` sobre tabela-espinha são recusados em `/api/query`, `/api/execute`, `/api/count` e `/api/explain` (`espinha_guard: true` na resposta), e a recusa diz o caminho certo: a migration. A lista, o porquê e os limites da guarda: [README](../README.md#guarda-de-tabelas-espinha).

---

## Leitura

### `POST /api/query`

Executa um SELECT.

- `sql` (obrigatório): começa por `SELECT` ou `WITH`; comentário no topo do texto é recusado.
- `limit` (opcional): máximo de linhas (default 1000).

**Retorno:** `success`, `rows`, `columns`, `data`, `execution_time_ms`.

⚠️ **A resposta corta em silêncio.** Sem `LIMIT` no texto, a rota acrescenta `LIMIT <limit>`; com ou sem ele, a leitura para no teto `max_rows`. Nenhum campo avisa que cortou: para contar, agregue no servidor (`count(*)`), e ao paginar confira o total contra um `count(*)` na mesma rodada.

```json
{"sql": "SELECT cnpj_basico, razao_social FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'"}
```

### `GET /api/count`

- `table` (obrigatório): `schema.tabela`.
- `where` (opcional): a cláusula sem a palavra `WHERE`, concatenada crua no SQL. Vai na query string, então precisa de URL-encoding (no `curl`, `-G` com `--data-urlencode`).

**Retorno:** `success`, `table`, `count`, `where`, `execution_time_ms`.

É um `COUNT(*)` exato: em tabela grande pode estourar o timeout. A estimativa barata é o `estimated_rows` do `GET /api/tables`.

```bash
curl -s -G "https://claude-db-tools-34pal47ocq-rj.a.run.app/api/count" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  --data-urlencode "table=cnpj_raw.estabelecimentos" \
  --data-urlencode "where=situacao_cadastral = '02'"
```

### `GET /api/tables`

- `schema` (opcional, default `public`).

**Retorno:** `success`, `schema`, `total_tables` e, por tabela, `table_name`, `size`, `estimated_rows`, `estimated_rows_as_of` e `live_tup_since_stats_reset`.

O `estimated_rows` vem do `pg_class.reltuples`, que sobrevive a um restart do cluster e vale até o último analyze (`estimated_rows_as_of`). O `live_tup_since_stats_reset` é contador do coletor de estatísticas e zera quando o cluster perde as estatísticas (num crash, por exemplo): ⛔ não o use para provar que uma tabela está vazia.

### `GET /api/schema`

- `table` (obrigatório): o nome sem o schema.
- `schema` (opcional, default `public`).

**Retorno:** `success`, `full_name`, `row_count` e `columns` (`name`, `type`, `nullable`, `default`, `max_length`).

O `row_count` é um `COUNT(*)` exato: em tabela grande, a chamada pode estourar o timeout.

### `GET /api/indexes`

- `table` (opcional): filtra por tabela.
- `schema` (opcional, default `cnpj_raw`).

**Retorno:** `success`, `schema`, `table`, `total_indexes` e, por índice, `table_name`, `index_name`, `size`, `index_type` e `definition`.

### `GET /api/stats`

- `table` (obrigatório): o nome sem o schema.
- `schema` (opcional, default `cnpj_raw`).

**Retorno:** `success`, `full_name`, `row_count` (um `COUNT(*)` exato), `estimated_live_rows`, `dead_rows`, `modifications_since_analyze`, `size` (`total`, `table`, `indexes`) e `maintenance` (último vacuum e último analyze, manual e automático).

`estimated_live_rows`, `dead_rows` e `modifications_since_analyze` são contadores do coletor de estatísticas: zeram quando o cluster perde as estatísticas.

### `POST /api/explain`

- `sql` (obrigatório).
- `analyze` (opcional, default `true`).

**Retorno:** `success`, `analyzed`, `query`, `plan` (as linhas do plano) e `timing` (`planning_time_ms`, `execution_time_ms`, `total_time_ms`).

⚠️ Com `analyze` (o default), o Postgres **executa** o comando, DML inclusive. Nada é commitado, mas efeito não transacional (sequência, advisory lock) fica. Para ver só o plano, `"analyze": false`.

### `GET /api/sample`

- `table` (obrigatório): o nome sem o schema.
- `schema` (opcional, default `public`).
- `limit` (opcional, default 10, teto 100).

**Retorno:** `success`, `full_name`, `rows_returned`, `columns`, `data`.

### `GET /health` (e `GET /`)

Sem parâmetros. Devolve `status` (`healthy` ou `unhealthy`), `database` (`connected` ou `disconnected`) e `version`.

---

## Escrita

### `POST /api/execute`

- `sql` (obrigatório): começa por um dos verbos de `allowed_operations` em `src/tools/query.py::execute` (DML, DDL, `DO` e a manutenção `VACUUM`, `ANALYZE` e `REINDEX`).
- `allow_mojibake` (opcional, default `false`): libera SQL com a assinatura de mojibake, só para reparo de dado. Não libera a guarda de tabelas-espinha nem a de manutenção.

**Retorno:** `success`, `rows_affected`, `execution_time_ms`, `message`.

- ⛔ SQL com a assinatura de mojibake (texto UTF-8 relido como CP1252 no cliente) é recusado (`mojibake_guard: true`): componha o não-ASCII com `chr(NNN)`, ou mande o SQL por um cliente com UTF-8 explícito.
- ⛔ `DELETE`, `TRUNCATE` e `DROP` sobre tabela-espinha são recusados (`espinha_guard: true`).
- `VACUUM` e todo comando com `CONCURRENTLY` rodam em autocommit; o resto roda numa transação, desfeita se der erro.
- ⛔ `VACUUM FULL`, `REINDEX` sem `CONCURRENTLY` e `CLUSTER` são recusados antes de executar, em qualquer statement do corpo (`manutencao_guard: true`, com o `comando` recusado): não perdem linha, mas seguram a tabela pela duração inteira, e praticamente nenhuma query passa enquanto rodam. A recusa aponta a forma que não trava (`VACUUM` sem `FULL`, `REINDEX INDEX CONCURRENTLY <índice>`) ou uma migration do frontend-api, que o deploy aplica pelo `run-migration-internal` (passo a passo na skill `deploy-e-migrations-fe-api`). Não há flag que a pule.
- ⚠️ O `CONCURRENTLY` só libera na posição canônica, logo depois de `INDEX`, `TABLE`, `SCHEMA` ou `DATABASE`. Na lista de opções (`REINDEX (CONCURRENTLY) TABLE …`) ele aceita valor, e por isso é recusado. O corpo de um `DO $$…$$` fica opaco, como na guarda de espinha.

```
{"sql": "INSERT INTO zz_tmp_scratch (col1) VALUES ('valor')"}
{"sql": "CREATE INDEX CONCURRENTLY idx_nome ON schema.tabela (coluna)"}
{"sql": "VACUUM (ANALYZE) leads.meritos"}
```

---

## Erros

A resposta das rotas `/api/...` traz `success` e, na falha, `error` com a mensagem. Falta de parâmetro obrigatório responde 400, só com `error`; rota ou método que não existe responde 404 (`{"error": "Not found"}`).

## Limites

Os limites (timeout de query, teto de linhas, pool de conexões e timeout de conexão) são os campos de `src/config.py::Settings`. O timeout de query fica abaixo do `--timeout` do Cloud Run no `cloudbuild.yaml`, para a query morrer junto com o request que a pediu.
