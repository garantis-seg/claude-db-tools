"""O `/api/explain` executa COM teto, e nenhuma porta nova volta a pegar conexao crua.

O DEFEITO (card 869eypyq3): `explain_query` era o UNICO caminho do servico que
pegava `get_connection()` cru e nunca mandava `SET statement_timeout`. E
`analyze=True` e o default nas duas portas (`src/server.py:184` e `:425`), entao
`EXPLAIN (ANALYZE, ...)` EXECUTA a query de verdade — sem teto.

⚠️ A EVIDENCIA DO CARD MEDIA A COISA ERRADA, e refazer a medicao dele fecha o
card errado. Ele cita `reset_val=0 / boot_val=0`, que e o default do CLUSTER e
nao o valor da SESSAO. Medido em 2026-09-09 pela porta viva:
`POST /api/explain {"sql":"SELECT (current_setting('statement_timeout')||'_L')::int"}`
respondeu **"0"** em 8/8 sondas no staging e na 1a sonda de prod, e **"100s"**
nas 12 sondas seguintes de prod (`pg_settings`: `setting=100000`, `reset_val=0`,
`source=session`). ⇒ o teto que as vezes aparecia era VAZAMENTO do `SET` que
`execute_write` deixa commitado numa conexao do pool — teto por sorte de pool,
nao por codigo. Quem le "prod ja tem 100s" e conclui "ja tem teto" esta lendo o
residuo de outro caller.

⇒ O que este arquivo mede e o unico fato estavel: **a porta EMITE o `SET` antes
da query**. Nao o valor lido depois, que depende de quem usou a conexao antes.

A ordem invertida (teto=100s vs `--timeout=110` do Cloud Run) e o incidente de
2026-07-31 e mora em `tests/test_timeout_abaixo_do_http.py` — este aqui so
garante que a porta CHEGA naquela guarda.
"""
import ast
import json
import re
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

import pytest

from src import database as db
from src.config import settings

smod = import_module("src.tools.stats")

_RAIZ = Path(__file__).resolve().parents[1]

# O nome que nenhuma porta pode usar direto (ver o ultimo teste deste arquivo).
_CRU = "get_connection"

# Plano como o Postgres devolve: uma coluna, uma linha por linha de texto.
_PLANO = [
    "Seq Scan on cnpj_raw.empresas  (cost=0.00..8.27 rows=1 width=0)"
    " (actual time=0.021..0.022 rows=1 loops=1)",
    "Planning Time: 0.123 ms",
    "Execution Time: 42.500 ms",
]


class _FakeCursor:
    """Grava todo SQL que chega ao cursor.

    🚨 O shape das linhas SEGUE o `cursor_factory` de proposito (ver
    `test_o_plano_nao_volta_vazio_com_o_cursor_de_dict`).
    """

    def __init__(self, registro, dict_rows):
        self._registro = registro
        self._dict_rows = dict_rows
        self.description = [("QUERY PLAN",)]
        self.rowcount = -1

    def execute(self, sql, params=None):
        self._registro.append(sql)

    def _linhas(self):
        if self._dict_rows:
            return [{"QUERY PLAN": linha} for linha in _PLANO]
        return [(linha,) for linha in _PLANO]

    def fetchmany(self, size):
        return self._linhas()[:size]

    def fetchone(self):
        return self._linhas()[0]

    def close(self):
        pass


class _FakeConn:
    autocommit = False

    def __init__(self, registro):
        self._registro = registro

    def cursor(self, cursor_factory=None):
        return _FakeCursor(self._registro, dict_rows=cursor_factory is not None)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def registro(monkeypatch):
    """Todo SQL que chega ao cursor, na ordem. Patchar `src.database` basta
    porque a porta so fala com o banco pelos wrappers de la (ultimo teste)."""
    vistos = []

    @contextmanager
    def _fake():
        yield _FakeConn(vistos)

    monkeypatch.setattr(db, "get_connection", _fake)
    return vistos


@pytest.mark.asyncio
async def test_a_porta_do_explain_manda_o_teto_antes_de_executar(registro):
    """O teste do card: pre-fix, esta porta nao emitia `SET` nenhum."""
    out = json.loads(await smod.explain_query("SELECT 1", analyze=True))
    assert out["success"] is True, out

    sets = [i for i, sql in enumerate(registro) if "SET statement_timeout" in sql]
    explains = [i for i, sql in enumerate(registro) if sql.lstrip().upper().startswith("EXPLAIN")]

    assert sets, (
        "/api/explain executou sem statement_timeout. EXPLAIN ANALYZE EXECUTA a "
        "query: sem teto ela sobrevive ao 504 do Cloud Run (110s) e segura slot "
        "de concorrencia + conexao do pool — o incidente de 2026-07-31 por outra "
        "porta. SQL que chegou ao cursor: {}".format(registro)
    )
    assert explains, "o EXPLAIN nem chegou ao cursor: {}".format(registro)
    assert min(sets) < min(explains), (
        "o SET saiu DEPOIS do EXPLAIN — teto que chega tarde nao e teto: {}".format(registro)
    )


@pytest.mark.asyncio
async def test_o_teto_da_porta_e_o_query_timeout_do_config(registro):
    """Fonte unica: o valor tem que vir do `config.py`, que a guarda de
    `test_timeout_abaixo_do_http.py` mantem abaixo do `--timeout` do Cloud Run.
    Um literal proprio aqui seria a 3a copia da linha e sairia do alcance daquela
    guarda em silencio."""
    await smod.explain_query("SELECT 1", analyze=True)
    setados = [sql for sql in registro if "SET statement_timeout" in sql]
    assert setados, registro
    valores = {int(m) for sql in setados for m in re.findall(r"'(\d+)s'", sql)}
    assert valores == {settings.query_timeout}, (
        "teto da porta {} != query_timeout do config ({}s)".format(valores, settings.query_timeout)
    )


@pytest.mark.asyncio
async def test_o_plano_nao_volta_vazio_com_o_cursor_de_dict(registro):
    """🚨 ARMADILHA MEDIDA: `execute_query` usa `RealDictCursor`. Se o plano for
    lido por indice posicional, a resposta vira `plan: []` (ou erro engolido) com
    `success: true` — o pior shape possivel: a porta parece funcionar."""
    out = json.loads(await smod.explain_query("SELECT 1", analyze=True))
    assert out["success"] is True, out
    assert out["plan"] == _PLANO, out["plan"]
    assert out["timing"]["execution_time_ms"] == 42.5
    assert out["timing"]["planning_time_ms"] == 0.123


def test_o_outro_sitio_do_teto_tambem_emite(registro):
    """⛔ O teto vive em EXATAMENTE 2 lugares (`execute_query` e `execute_write`),
    e depois deste fix as 5 portas herdam de um dos dois. Medido: apagar o `SET`
    do `execute_write` deixava a suite inteira VERDE — mutante vivo no sitio
    irmao daquele que este card conserta. Um mutante em UM sitio nao prova o
    outro."""
    db.execute_write("INSERT INTO zz_t (a) VALUES (1)")
    assert any("SET statement_timeout" in sql for sql in registro), (
        "o caminho de ESCRITA executou sem teto: {}".format(registro)
    )


@pytest.mark.asyncio
async def test_erro_do_banco_vira_resposta_de_erro_e_nao_estoura(monkeypatch):
    """O ramo de excecao: o proprio teto mata a query com `QueryCanceled`, e isso
    tem de sair como `success: false` com a mensagem — nao como 500 do ASGI."""
    def _explode(*a, **k):
        raise RuntimeError("canceling statement due to statement timeout")

    monkeypatch.setattr(smod, "execute_query", _explode)
    out = json.loads(await smod.explain_query("SELECT pg_sleep(9999)", analyze=True))
    assert out["success"] is False
    assert "statement timeout" in out["error"]


def test_nenhuma_porta_pega_conexao_crua():
    """Fecha a porta NOVA por construcao (o card: 3a vez em 2 dias que uma porta
    deste servico nao herda um freio que as outras tem).

    `src/tools/*` fala com o banco pelos wrappers `execute_query`/`execute_write`,
    que sao os DOIS unicos lugares do repo que mandam `SET statement_timeout`.
    Quem pega `get_connection` direto sai do alcance do freio — foi exatamente
    como o `/api/explain` ficou sem teto.
    """
    culpados = {}
    for p in sorted((_RAIZ / "src" / "tools").glob("*.py")):
        # ⛔ O predicado e AST, nao substring: `get_connection` aparece de
        # proposito nos COMENTARIOS que explicam por que a porta nao o usa mais,
        # e uma guarda que o proprio comentario derruba vira guarda AFROUXADA na
        # proxima sessao. Aqui so o NOME usado conta.
        achados = []
        for no in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(no, ast.ImportFrom) and any(a.name == _CRU for a in no.names):
                achados.append("linha {}: import".format(no.lineno))
            elif isinstance(no, ast.Name) and no.id == _CRU:
                achados.append("linha {}: uso".format(no.lineno))
            elif isinstance(no, ast.Attribute) and no.attr == _CRU:
                achados.append("linha {}: uso".format(no.lineno))
        if achados:
            culpados[p.name] = achados
    assert not culpados, (
        "conexao crua em src/tools/ — ela nao passa pelo `SET statement_timeout` "
        "de database.py: {}".format(culpados)
    )
