"""VACUUM / ANALYZE / REINDEX no allowlist do `execute` (2026-08-15).

Ate aqui o unico jeito de rodar VACUUM FULL em prod era escrever uma migration
de um statement so e chamar `run-migration-internal?autocommit=true` no fe-api —
o que poe manutencao RECORRENTE no ledger de `app.schema_migrations`, que existe
pra mudanca de SCHEMA. E ela recorre: bloat volta.

O que motivou: censo do banco em 2026-08-15 achou 6 tabelas com ~2,9 GB de
arquivo pra ~20 MB de dado real (`leads.meritos` = 642 kB de dado num arquivo de
428 MB, fator 682x). Dois design docs do execucao-fiscal ja tinham adiado esse
reclaim nomeando a ferramenta que faltava.

⚠️ Estes testes NAO tocam o banco de proposito — eles trocam `execute_write` por
um espiao. O que se guarda aqui e a DECISAO (aceita? com autocommit?), nao o
efeito no Postgres. Um teste que precisasse de DB seria pulado no CI (o
`pytestmark` de `test_tools.py` pula tudo sem `DB_PASSWORD`) e a guarda nasceria
morta.
"""
import json
from importlib import import_module

import pytest

# ⚠️ `from src.tools import query` devolve a FUNCAO `query` (o __init__ do pacote
# a re-exporta e sombreia o submodulo de mesmo nome), e o monkeypatch morre com
# "has no attribute 'execute_write'". import_module pega o modulo.
qmod = import_module("src.tools.query")


@pytest.fixture
def espiao(monkeypatch):
    """Substitui execute_write e registra como foi chamado."""
    chamadas = []

    def fake(sql, params=None, autocommit=False, **kw):
        chamadas.append({"sql": sql, "autocommit": autocommit})
        return 0

    monkeypatch.setattr(qmod, "execute_write", fake)
    return chamadas


async def _run(sql):
    return json.loads(await qmod.execute(sql))


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    "VACUUM (FULL, ANALYZE) leads.meritos",
    "ANALYZE leads.meritos",
    "REINDEX TABLE leads.meritos",
])
async def test_manutencao_e_aceita(sql, espiao):
    assert (await _run(sql))["success"] is True, f"{sql} foi recusado pelo allowlist"


@pytest.mark.asyncio
async def test_vacuum_vai_com_autocommit(espiao):
    """Sem isto o VACUUM passa o allowlist e morre no Postgres.

    `execute_write` abre transacao implicita por default, e o Postgres proibe
    VACUUM dentro de bloco de transacao — o erro sairia como
    "VACUUM cannot run inside a transaction block", que parece bug do banco e
    nao configuracao da ferramenta.
    """
    await _run("VACUUM (FULL, ANALYZE) leads.meritos")
    assert espiao[-1]["autocommit"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", ["ANALYZE leads.meritos", "REINDEX TABLE leads.meritos"])
async def test_analyze_e_reindex_seguem_em_transacao(sql, espiao):
    """⛔ Contra-exemplo: os dois RODAM em transacao e devem continuar assim.

    Marca-los como autocommit trocaria o rollback-em-erro deles por escrita
    solta. Sem este teste, alargar o predicado pra `startswith(("VACUUM",
    "ANALYZE", "REINDEX"))` — que parece mais 'consistente' — passaria verde.
    """
    await _run(sql)
    assert espiao[-1]["autocommit"] is False


@pytest.mark.asyncio
async def test_concurrently_continua_com_autocommit(espiao):
    """A razao ORIGINAL do autocommit nao pode ter sido perdida na mudanca."""
    await _run("CREATE INDEX CONCURRENTLY ix_teste ON leads.meritos (id)")
    assert espiao[-1]["autocommit"] is True


@pytest.mark.asyncio
async def test_select_continua_recusado(espiao):
    """Sanity: o allowlist nao virou 'aceita tudo'."""
    out = await _run("SELECT 1")
    assert out["success"] is False
    assert not espiao, "SELECT chegou no execute_write"
