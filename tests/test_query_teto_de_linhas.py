"""O `/api/query` anexa o teto de linhas so quando o SQL nao tem LIMIT.

`LIMIT` conta como palavra inteira: uma coluna `limite_*` desligava o teto, em silencio.
E o `;` final seguido de quebra de linha virava `...;\\n LIMIT n`, erro de sintaxe.
"""
import json
from importlib import import_module

import pytest

# `from src.tools import query` devolve a FUNCAO (ver test_guarda_espinha.py).
qmod = import_module("src.tools.query")


@pytest.fixture
def sql_executado(monkeypatch):
    vistos = []
    monkeypatch.setattr(qmod, "execute_query", lambda sql, *a, **k: vistos.append(sql) or [])
    return vistos


@pytest.mark.asyncio
@pytest.mark.parametrize("sql, esperado", [
    ("SELECT limite_dia FROM t", "SELECT limite_dia FROM t\nLIMIT 7"),
    ("SELECT 1;\n", "SELECT 1\nLIMIT 7"),
    ("SELECT 1 -- nota", "SELECT 1 -- nota\nLIMIT 7"),
    ("SELECT 1 LIMIT 5", "SELECT 1 LIMIT 5"),
])
async def test_o_teto_entra_so_quando_falta_limit(sql_executado, sql, esperado):
    assert json.loads(await qmod.query(sql, limit=7))["success"] is True
    assert sql_executado == [esperado]
