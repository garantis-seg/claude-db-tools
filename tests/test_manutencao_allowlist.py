"""VACUUM / ANALYZE / REINDEX no allowlist do `execute`: o que entra e em que modo.

Manutencao recorrente nao cabe no ledger de `app.schema_migrations`, que existe
pra mudanca de SCHEMA — e bloat volta. Por isso ela roda aqui. Mas so a que NAO
trava a tabela: VACUUM FULL, REINDEX sem CONCURRENTLY e CLUSTER sao recusados
antes do allowlist e vao por migration (`test_guarda_manutencao.py`).

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
    "VACUUM (ANALYZE) leads.meritos",
    "ANALYZE leads.meritos",
    "REINDEX TABLE CONCURRENTLY leads.meritos",
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
    await _run("VACUUM (ANALYZE) leads.meritos")
    assert espiao[-1]["autocommit"] is True


@pytest.mark.asyncio
async def test_analyze_segue_em_transacao(espiao):
    """⛔ Contra-exemplo: ANALYZE RODA em transacao e deve continuar assim.

    Marca-lo como autocommit trocaria o rollback-em-erro dele por escrita solta.
    Sem este teste, alargar o predicado pra `startswith(("VACUUM", "ANALYZE"))`
    — que parece mais 'consistente' — passaria verde.
    """
    await _run("ANALYZE leads.meritos")
    assert espiao[-1]["autocommit"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    "CREATE INDEX CONCURRENTLY ix_teste ON leads.meritos (id)",
    # o unico REINDEX que passa a guarda, e o PG tambem o proibe em transacao
    "REINDEX INDEX CONCURRENTLY leads.ix_teste",
])
async def test_concurrently_continua_com_autocommit(sql, espiao):
    """A razao ORIGINAL do autocommit nao pode ter sido perdida na mudanca."""
    await _run(sql)
    assert espiao[-1]["autocommit"] is True


@pytest.mark.asyncio
async def test_select_continua_recusado(espiao):
    """Sanity: o allowlist nao virou 'aceita tudo'."""
    out = await _run("SELECT 1")
    assert out["success"] is False
    assert not espiao, "SELECT chegou no execute_write"
