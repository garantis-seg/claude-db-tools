"""As rotas REST sao o contrato do servico, e nada fora deste repo acusa quando ele muda.

Toda sessao do Claude chama estas rotas por curl, sem cliente versionado: rota
que some, metodo que troca ou default que muda so aparece como erro na sessao
seguinte. O despacho e um if/elif dentro de `run_http_server` (src/server.py),
sem roteador que liste as rotas. Entao o teste monta o app ASGI de verdade
(capturado trocando `uvicorn.run`), troca as operacoes de src/tools por stubs
que devolvem os argumentos recebidos e confere cada rota contra a tabela abaixo,
escrita a mao de proposito: derivada do codigo, ela concordaria com qualquer
mudanca. Roda sem banco.
"""
import asyncio
import json

import pytest
import uvicorn

import src.server as srv

_OPERACOES = ["query", "execute", "count", "list_tables", "get_schema",
              "get_indexes", "get_stats", "explain_query", "get_sample"]

# O contrato: so estes pares metodo + caminho respondem; o resto e 404.
# /sse e /messages/ eram o transporte MCP, que saiu do servico: entram na
# varredura para que a volta dele seja decisao, nao efeito colateral.
CONTRATO = {
    ("GET", "/"), ("GET", "/health"),
    ("GET", "/api/tables"), ("POST", "/api/query"), ("POST", "/api/execute"),
    ("GET", "/api/count"), ("GET", "/api/schema"), ("GET", "/api/indexes"),
    ("GET", "/api/stats"), ("GET", "/api/sample"), ("POST", "/api/explain"),
}
_FORA = ["/sse", "/messages/", "/messages/x", "/api", "/api/nope"]
_METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

# metodo, caminho, query string, corpo -> operacao chamada e os argumentos que
# ela recebe (os defaults de cada rota estao aqui).
ROTAS = [
    ("GET", "/api/tables", "", None, "list_tables", ["public"]),
    ("GET", "/api/tables", "schema=cnpj_raw", None, "list_tables", ["cnpj_raw"]),
    ("POST", "/api/query", "", {"sql": "SELECT 1"}, "query", ["SELECT 1", 1000]),
    ("POST", "/api/query", "", {"sql": "SELECT 1", "limit": 5}, "query", ["SELECT 1", 5]),
    ("POST", "/api/execute", "", {"sql": "UPDATE t SET a = 1"},
     "execute", ["UPDATE t SET a = 1", False]),
    ("POST", "/api/execute", "", {"sql": "UPDATE t SET a = 1", "allow_mojibake": True},
     "execute", ["UPDATE t SET a = 1", True]),
    ("GET", "/api/count", "table=a.b", None, "count", ["a.b", None]),
    ("GET", "/api/count", "table=a.b&where=situacao%20%3D%20%2702%27", None,
     "count", ["a.b", "situacao = '02'"]),
    ("GET", "/api/schema", "table=t", None, "get_schema", ["t", "public"]),
    ("GET", "/api/schema", "table=t&schema=s", None, "get_schema", ["t", "s"]),
    ("GET", "/api/indexes", "", None, "get_indexes", [None, "cnpj_raw"]),
    ("GET", "/api/indexes", "table=t&schema=s", None, "get_indexes", ["t", "s"]),
    ("GET", "/api/stats", "table=t", None, "get_stats", ["t", "cnpj_raw"]),
    ("GET", "/api/stats", "table=t&schema=s", None, "get_stats", ["t", "s"]),
    ("GET", "/api/sample", "table=t", None, "get_sample", ["t", "public", 10]),
    ("GET", "/api/sample", "table=t&schema=s&limit=3", None, "get_sample", ["t", "s", 3]),
    ("POST", "/api/explain", "", {"sql": "SELECT 1"}, "explain_query", ["SELECT 1", True]),
    ("POST", "/api/explain", "", {"sql": "SELECT 1", "analyze": False},
     "explain_query", ["SELECT 1", False]),
]

# Parametro obrigatorio faltando da 400; excecao da operacao da 500 com a mensagem.
ERROS = [
    ("POST", "/api/query", "", {}, 400, {"error": "sql is required"}),
    ("POST", "/api/execute", "", {}, 400, {"error": "sql is required"}),
    ("POST", "/api/explain", "", {}, 400, {"error": "sql is required"}),
    ("GET", "/api/count", "", None, 400, {"error": "table is required"}),
    ("GET", "/api/schema", "", None, 400, {"error": "table is required"}),
    ("GET", "/api/stats", "", None, 400, {"error": "table is required"}),
    ("GET", "/api/sample", "", None, 400, {"error": "table is required"}),
    ("GET", "/api/tables", "schema=boom", None, 500, {"error": "explodiu"}),
    ("POST", "/api/query", "", {"sql": "boom"}, 500, {"error": "explodiu"}),
    ("POST", "/api/execute", "", {"sql": "boom"}, 500, {"error": "explodiu"}),
    ("GET", "/api/count", "table=boom", None, 500, {"error": "explodiu"}),
    ("GET", "/api/schema", "table=boom", None, 500, {"error": "explodiu"}),
    ("GET", "/api/indexes", "table=boom", None, 500, {"error": "explodiu"}),
    ("GET", "/api/stats", "table=boom", None, 500, {"error": "explodiu"}),
    ("GET", "/api/sample", "table=boom", None, 500, {"error": "explodiu"}),
    ("POST", "/api/explain", "", {"sql": "boom"}, 500, {"error": "explodiu"}),
]


@pytest.fixture
def app(monkeypatch):
    for nome in _OPERACOES:
        async def stub(*args, _nome=nome):
            if "boom" in args:
                raise RuntimeError("explodiu")
            return json.dumps({"operacao": _nome, "args": list(args)})
        monkeypatch.setattr(srv, nome, stub)
    monkeypatch.setattr(srv, "check_connection", lambda: True)
    capturado = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: capturado.update(app=app))
    srv.run_http_server()
    return capturado["app"]


def _chama(app, metodo, caminho, qs="", corpo=None):
    entrada = [{"type": "http.request", "more_body": False,
                "body": b"" if corpo is None else json.dumps(corpo).encode()}]
    saida = []

    async def receive():
        return entrada.pop(0) if entrada else {"type": "http.disconnect"}

    async def send(msg):
        saida.append(msg)

    scope = {"type": "http", "method": metodo, "path": caminho,
             "query_string": qs.encode(), "headers": []}
    asyncio.run(app(scope, receive, send))
    inicio = next(m for m in saida if m["type"] == "http.response.start")
    headers = {bytes(k).decode().lower(): bytes(v).decode() for k, v in inicio["headers"]}
    body = b"".join(m.get("body", b"") for m in saida if m["type"] == "http.response.body")
    return inicio["status"], headers, json.loads(body)


@pytest.mark.parametrize("metodo,caminho,qs,corpo,operacao,args", ROTAS)
def test_a_rota_chega_na_operacao_com_os_parametros_e_defaults(app, metodo, caminho, qs,
                                                               corpo, operacao, args):
    status, headers, body = _chama(app, metodo, caminho, qs, corpo)
    assert status == 200
    assert body == {"operacao": operacao, "args": args}
    assert headers["content-type"] == "application/json"
    assert headers["access-control-allow-origin"] == "*"


@pytest.mark.parametrize("metodo,caminho,qs,corpo,status_esperado,body_esperado", ERROS)
def test_erro_de_rota_sai_so_com_error(app, metodo, caminho, qs, corpo, status_esperado,
                                       body_esperado):
    status, _, body = _chama(app, metodo, caminho, qs, corpo)
    assert (status, body) == (status_esperado, body_esperado)


@pytest.mark.parametrize("caminho", ["/", "/health"])
def test_health(app, caminho):
    status, headers, body = _chama(app, "GET", caminho)
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body == {"status": "healthy", "database": "connected", "version": "1.0.0"}


def test_so_as_rotas_do_contrato_respondem(app):
    caminhos = sorted({c for _, c in CONTRATO} | set(_FORA))
    respondem = set()
    for metodo in _METODOS:
        for caminho in caminhos:
            status, _, body = _chama(app, metodo, caminho, "table=t", {"sql": "SELECT 1"})
            if status == 404:
                assert body == {"error": "Not found"}
            else:
                respondem.add((metodo, caminho))
    assert respondem == CONTRATO
