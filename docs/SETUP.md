# Setup do claude-db-tools

Guia completo para configurar o MCP Server no Claude Code.

---

## URLs do Servico

| Ambiente | URL |
|----------|-----|
| Cloud Run | `https://claude-db-tools-34pal47ocq-uc.a.run.app` |
| Health Check | `https://claude-db-tools-34pal47ocq-uc.a.run.app/health` |
| SSE Endpoint | `https://claude-db-tools-34pal47ocq-uc.a.run.app/sse` |

---

## Opcao 1: Usar o Servidor Remoto (Recomendado)

O servidor ja esta deployado no Cloud Run e conectado ao banco de dados.

### Para Windows

```powershell
# Adicionar ao Claude Code
claude mcp add claude-db-tools --transport sse https://claude-db-tools-34pal47ocq-uc.a.run.app/sse
```

### Verificar Instalacao

```bash
# Listar servidores MCP
claude mcp list

# Ou via comando /mcp dentro do Claude Code
/mcp
```

---

## Opcao 2: Rodar Localmente (Desenvolvimento)

Se precisar rodar o servidor localmente (requer acesso a VPC do GCP):

### Passo 1: Instalar Dependencias

```bash
cd c:\Users\Eltonxp\dev\Garantis\claude-db-tools
pip install -r requirements.txt
```

### Passo 2: Configurar Credenciais

Criar arquivo `.env`:
```
DB_HOST=172.17.0.5
DB_PORT=5432
DB_NAME=cnpj_database
DB_USER=postgres
DB_PASSWORD=<senha_do_secret_manager>
```

### Passo 3: Adicionar ao Claude Code

```bash
claude mcp add claude-db-tools \
  --transport stdio \
  --scope user \
  --env DB_HOST=172.17.0.5 \
  --env DB_NAME=cnpj_database \
  --env DB_USER=postgres \
  --env DB_PASSWORD=<senha> \
  -- python c:\Users\Eltonxp\dev\Garantis\claude-db-tools\src\server.py
```

**Nota:** A conexao local so funciona se voce estiver dentro da VPC do GCP (via VPN ou Cloud Shell).

---

## Testar o Servidor

### Via Health Check

```bash
curl -s "https://claude-db-tools-34pal47ocq-uc.a.run.app/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

Resposta esperada:
```json
{"status":"healthy","database":"connected","version":"1.0.0"}
```

### Via Claude Code

Abra uma conversa com o Claude e peca:

```
Liste as tabelas do schema cnpj_raw
```

O Claude deve usar a tool `db_list_tables` automaticamente.

---

## Troubleshooting

### Erro: "Connection refused" no servidor remoto

Verifique se o token de identidade esta valido:
```bash
gcloud auth print-identity-token
```

### Erro: "DB_PASSWORD environment variable is required"

A senha do banco nao foi configurada. Isso so acontece no modo local.

### Servidor nao aparece no `/mcp`

Remova e adicione novamente:
```bash
claude mcp remove claude-db-tools
claude mcp add claude-db-tools --transport sse https://claude-db-tools-34pal47ocq-uc.a.run.app/sse
```

---

## Seguranca

- O servidor requer autenticacao via token GCP
- Conexoes usam pool com limite de 25 conexoes
- Queries tem timeout de 5 minutos
- Maximo de 10.000 rows por query

---

## Tools Disponiveis

| Tool | Descricao |
|------|-----------|
| `db_query` | Executa SELECT queries |
| `db_execute` | Executa INSERT/UPDATE/DELETE |
| `db_count` | Conta rows em uma tabela |
| `db_list_tables` | Lista tabelas de um schema |
| `db_get_schema` | Mostra schema de uma tabela |
| `db_get_indexes` | Lista indices |
| `db_get_stats` | Estatisticas de tabela |
| `db_explain` | EXPLAIN ANALYZE de queries |
| `db_get_sample` | Amostra de rows |
| `db_health` | Verifica conexao com o banco |
