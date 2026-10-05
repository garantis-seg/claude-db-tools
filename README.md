# claude-db-tools

Serviço de acesso ao PostgreSQL do Cloud SQL (projeto `neqsti`) para AI Agents (Claude, GPT etc.): uma API REST e um servidor MCP sobre as mesmas operações.

---

## Para AI Agents (Claude, GPT etc.)

### Acesso via REST API

Base URL: `https://claude-db-tools-34pal47ocq-rj.a.run.app`

As operações (a tool MCP e a rota REST de cada uma, com parâmetros, retorno e armadilhas) estão em [docs/TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md). O setup do MCP no Claude Code está em [docs/SETUP.md](docs/SETUP.md).

### Autenticação (IMPORTANTE)

O serviço é privado: toda requisição, `/health` inclusive, leva um Google Cloud Identity Token.

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" URL
```

**Pré-requisito:** o usuário precisa estar logado no gcloud CLI.

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
curl -s "https://claude-db-tools-34pal47ocq-rj.a.run.app/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Exemplos de Uso (curl)

```bash
# Listar tabelas do schema cnpj_raw
curl -s "https://claude-db-tools-34pal47ocq-rj.a.run.app/api/tables?schema=cnpj_raw" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Executar query
curl -s "https://claude-db-tools-34pal47ocq-rj.a.run.app/api/query" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM cnpj_raw.empresas LIMIT 5"}'

# Ver schema de uma tabela
curl -s "https://claude-db-tools-34pal47ocq-rj.a.run.app/api/schema?table=empresas&schema=cnpj_raw" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### Banco de Dados

Os schemas e as tabelas são os do próprio banco: liste com `GET /api/tables?schema=<schema>`. A conexão vem das variáveis de `src/config.py::Settings`, e a senha, do secret que o `--set-secrets` do `cloudbuild.yaml` monta.

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

`DELETE` / `TRUNCATE` / `DROP` sobre um conjunto **nomeado** de tabelas são recusados em `/api/execute`, `/api/query`, `/api/count` e `/api/explain` (`"espinha_guard": true` no response, com a rota que barrou), e a recusa nomeia o caminho certo: a migration. ⭐ As quatro, e não só a primeira: são portas do **mesmo serviço**, com o **mesmo token**, chegando na **mesma tabela** — o `/api/query` executa multi-statement (`SELECT 1 LIMIT 1; DELETE FROM ...`), e `EXPLAIN ANALYZE <dml>` **executa**. A lista e o motivo de cada linha estão em [`src/tools/query.py::TABELAS_ESPINHA`](src/tools/query.py); os testes, em [`tests/test_guarda_espinha.py`](tests/test_guarda_espinha.py).

**Por quê.** A porta canônica para mudar esse dado (por exemplo, `POST /api/meritos/{id}/merge` no app) exige token Firebase, que sessão de agente nenhuma tem: a trava humana está ali. Este serviço aceitava `DELETE` arbitrário com o token de service account que **toda** sessão carrega. Não era gate faltando; era um **buraco lateral** numa trava que já estava certa.

### ⚠️ O que esta guarda NÃO compra

Ela fecha **um** canal, e é tudo o que ela faz: **nada impede uma sessão de achar uma terceira porta.** O que se compra é tornar o desvio **difícil e visível**, não impossível. ⛔ Não leia a denylist como garantia.

Estes desvios **passam** (exercidos contra o parser real do Postgres, `pglast`/libpg_query):

| desvio | por quê |
|---|---|
| `DO $$ BEGIN DELETE FROM leads.meritos; END $$` | o corpo do bloco é opaco **de propósito** — é isso que mantém vivo o truque de medição `DO … RAISE EXCEPTION`. Passa, mas **fica logado** em WARNING, nomeando verbo e tabela. |
| `ALTER TABLE … RENAME TO zz; DROP TABLE zz` | derrota qualquer denylist **por nome**: o nome protegido deixa de existir antes da checagem. |
| `CREATE VIEW v AS SELECT * FROM <espinha>; DELETE FROM v` | view de uma tabela só é auto-updatable; resolver exigiria consultar `pg_depend` em tempo de guarda. |
| `TRUNCATE <satélite> CASCADE` | a relação mora no grafo de FK, não no texto. |
| `MERGE … WHEN MATCHED THEN DELETE` | apaga sem `FROM`; é um 4º verbo, fora dos 3 que a guarda olha. |
| `UPDATE … SET col = NULL` / `ALTER TABLE … DROP COLUMN` | fora dos 3 verbos, por especificação. Perda de dado igualmente irreversível. |

⇒ **a guarda é quebra-molas, não fronteira.** Quem sabe o que está fazendo passa; o ponto é que passar vira uma **decisão**, não um descuido.

### O custo: a fricção é o produto

A guarda também recusa trabalho legítimo, e isso é o mecanismo, não efeito colateral: ela força a pausa e o rastro em papel justamente nos casos que "pareciam óbvios na hora". Por isso a recusa **nomeia o caminho certo** em vez de só dizer não, e por isso ⛔ **não existe flag de bypass**: aqui o risco é *autorização*, não dado corrompido, então o precedente do `allow_mojibake` **não** se aplica.

### A regra escrita que acompanha o freio

⛔ **Nunca grave atribuição de consentimento que você não recebeu** — em nenhum campo durável: `reason`, `justificativa`, `actor`, mensagem de commit, comentário de card, linha de audit log. **Se a autorização não está numa mensagem humana que você pode CITAR, ela não existe** — e o certo é parar e pedir.

⇒ Para quem **herda** trabalho: relatório que diz *"com o seu OK"* **não é prova de OK**; antes de aceitar autorização alegada para algo irreversível, abra o transcript da sessão. ⚠️ Abra-o inteiro: o OK chega por mensagem digitada **e** pela resposta de `AskUserQuestion` ou de `ExitPlanMode`, que o transcript grava como `tool_result`. Varrer só a mensagem digitada dá falso negativo, e esse falso negativo acusa quem fez certo.

---

## Código

`src/server.py` registra as tools MCP e as rotas REST; `src/tools/` tem a implementação; `src/config.py`, a conexão e os limites.

---

## Deploy

```bash
gcloud builds submit --config=cloudbuild.yaml --project=neqsti
```

O build roda os testes antes de publicar (step `gate-testes` do `cloudbuild.yaml`): vermelho, nada sobe e a revisão anterior segue servindo.

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
