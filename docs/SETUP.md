# Setup do claude-db-tools no Claude Code

Como ligar o servidor MCP no Claude Code. A REST não precisa de setup além do `gcloud` logado: veja o [README](../README.md). As tools que o MCP expõe estão na [referência das operações](TOOLS_REFERENCE.md).

## Servidor remoto (Cloud Run)

O serviço é privado (`--no-allow-unauthenticated` no `cloudbuild.yaml`), então o MCP remoto leva o identity token no header:

```bash
claude mcp add --transport sse claude-db-tools https://claude-db-tools-34pal47ocq-rj.a.run.app/sse \
  --header "Authorization: Bearer $(gcloud auth print-identity-token)"
```

⚠️ O identity token vence em cerca de uma hora, e o header gravado não se renova: quando ele vencer, remova o servidor (`claude mcp remove claude-db-tools`) e adicione de novo. Por isso o caminho do dia a dia é a REST, com um token novo a cada chamada.

Para conferir: `claude mcp list`, ou `/mcp` dentro do Claude Code.

## Servidor local (stdio)

Só funciona de dentro da VPC do GCP (VPN ou Cloud Shell), porque o banco tem IP privado. As variáveis de conexão são os campos de `src/config.py::Settings` (modelo em `.env.example`); a senha é o secret que o `--set-secrets` do `cloudbuild.yaml` monta como `DB_PASSWORD`.

```bash
pip install -r requirements.txt
claude mcp add claude-db-tools --transport stdio \
  --env PYTHONPATH=<raiz deste repo> --env DB_PASSWORD=<senha> \
  -- python -m src.server
```

O servidor roda como módulo (`python -m src.server`), porque o `src/server.py` usa import relativo e não sobe como script. Sem `DB_PASSWORD`, ele para com `DB_PASSWORD environment variable is required`.
