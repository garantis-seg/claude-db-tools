"""Guarda de manutencao que trava, no `/api/execute`.

O criterio da casa para "isto vai por migration" e "TRAVA TABELA QUENTE?", nao
"muda dado?": VACUUM FULL, REINDEX sem CONCURRENTLY e CLUSTER nao mudam uma linha,
mas seguram a tabela pela duracao inteira. A guarda os recusa ANTES de executar e
a recusa aponta a migration.

Como em `test_guarda_espinha.py`, o que se guarda e a DECISAO: `execute_write` e
trocado por um espiao e teste nenhum toca o banco — teste que precisasse de DB
seria pulado no CI, e a guarda nasceria morta.

⭐ Os testes passam SO pela porta publica (`execute`), de proposito: com o
`query.py` de antes da guarda, este arquivo roda inteiro, o bloco 1 fica vermelho
e o bloco 2 fica verde. E essa a prova de que os dois blocos medem a guarda.

  1. RECUSA (controle POSITIVO) — cada forma que trava e recusada PELA GUARDA. O
     teste exige `manutencao_guard`, que so ela escreve: sem isso, `CLUSTER t` e
     `-- x\\nVACUUM FULL t`, que o allowlist ja recusa por outro motivo, passariam
     verdes com a guarda desligada.
  2. LIBERADO (controle NEGATIVO) — a manutencao que nao trava segue chegando no
     banco. Sem este bloco, "recusa tudo que comeca por VACUUM/REINDEX" passaria
     verde e empurraria quem tem trabalho legitimo pra outra porta.
"""
import json
import logging
from importlib import import_module

import pytest

# ⚠️ `from src.tools import query` devolve a FUNCAO `query` (o __init__ do pacote
# a re-exporta e sombreia o submodulo de mesmo nome). import_module pega o modulo.
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


async def _run(sql, **kw):
    return json.loads(await qmod.execute(sql, **kw))


# ---------------------------------------------------------------------------
# 1. RECUSA — controle POSITIVO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("sql,comando", [
    # --- VACUUM FULL: sem parenteses, o FULL vem colado no VACUUM -------------
    ("VACUUM FULL leads.processos", "VACUUM FULL"),
    ("vacuum full leads.processos", "VACUUM FULL"),
    ("Vacuum Full Verbose Analyze leads.processos", "VACUUM FULL"),
    # sem alvo: o banco inteiro
    ("VACUUM FULL", "VACUUM FULL"),
    # --- ... ou como opcao entre parenteses, em qualquer posicao --------------
    ("VACUUM (FULL, ANALYZE) leads.processos", "VACUUM FULL"),
    ("vacuum (analyze, full) leads.processos", "VACUUM FULL"),
    ("VACUUM(FULL)leads.processos", "VACUUM FULL"),
    ("VACUUM (VERBOSE, FULL true) leads.processos", "VACUUM FULL"),
    ("VACUUM (FULL 1) leads.processos", "VACUUM FULL"),
    # nome de opcao citado e IDENT pro PG, e liga a opcao do mesmo jeito
    ('VACUUM ("full") leads.processos', "VACUUM FULL"),
    # o PG le a lista em ordem e a ultima ocorrencia vence
    ("VACUUM (FULL false, FULL) leads.processos", "VACUUM FULL"),
    # --- REINDEX sem CONCURRENTLY, todos os alvos -----------------------------
    ("REINDEX TABLE leads.processos", "REINDEX"),
    ("REINDEX INDEX leads.ix_processos_numero", "REINDEX"),
    ("REINDEX SCHEMA leads", "REINDEX"),
    ("REINDEX DATABASE cnpj_database", "REINDEX"),
    ("REINDEX SYSTEM cnpj_database", "REINDEX"),
    ("reindex table leads.processos", "REINDEX"),
    ("REINDEX (VERBOSE) TABLE leads.processos", "REINDEX"),
    # --- CONCURRENTLY fora da posicao canonica nao libera ---------------------
    # na lista de opcoes ele aceita valor, e o valor e que decide
    ("REINDEX (CONCURRENTLY false) TABLE leads.processos", "REINDEX"),
    ("REINDEX (CONCURRENTLY 'off') TABLE leads.processos", "REINDEX"),
    # e o NOME do alvo, nao a palavra-chave
    ('REINDEX TABLE "concurrently"', "REINDEX"),
    ("REINDEX TABLE leads.concurrently", "REINDEX"),
    # so em comentario ou em string, nao e comando
    ("REINDEX TABLE /* CONCURRENTLY */ leads.processos", "REINDEX"),
    ("REINDEX TABLE leads.processos; COMMENT ON TABLE zz IS 'CONCURRENTLY'", "REINDEX"),
    # o CONCURRENTLY de um statement nao libera o REINDEX do seguinte
    ("REINDEX INDEX CONCURRENTLY leads.ix_a; REINDEX INDEX leads.ix_b", "REINDEX"),
    # --- CLUSTER, com e sem alvo ----------------------------------------------
    ("CLUSTER leads.processos USING ix_processos_numero", "CLUSTER"),
    ("CLUSTER leads.processos", "CLUSTER"),
    ("CLUSTER", "CLUSTER"),
    ("cluster verbose", "CLUSTER"),
    ("CLUSTER (VERBOSE) leads.processos", "CLUSTER"),
    # --- comentario SQL antes do comando --------------------------------------
    ("-- reclaim do bloat\nVACUUM FULL leads.processos", "VACUUM FULL"),
    ("/* manutencao */ REINDEX TABLE leads.processos", "REINDEX"),
    ("-- x\n/* y */\nCLUSTER leads.processos", "CLUSTER"),
    ("VACUUM /* sem pressa */ FULL leads.processos", "VACUUM FULL"),
    # --- multi-statement: o lider e liberado, o que trava vem depois ----------
    ("ANALYZE leads.processos; VACUUM FULL leads.processos", "VACUUM FULL"),
    ("VACUUM leads.processos; REINDEX TABLE leads.processos", "REINDEX"),
    ("INSERT INTO zz_log (t) VALUES ('x'); CLUSTER leads.processos USING ix", "CLUSTER"),
    ("ANALYZE zz; -- agora sim\nREINDEX INDEX leads.ix_a", "REINDEX"),
    # `;` dentro de string nao separa statement — e o de fora separa
    ("INSERT INTO zz_log (t) VALUES ('a;b');VACUUM(FULL)zz_t", "VACUUM FULL"),
])
async def test_manutencao_que_trava_e_recusada(sql, comando, espiao):
    out = await _run(sql)
    assert out.get("manutencao_guard") is True, "PASSOU pela guarda: {!r}".format(sql)
    assert out["success"] is False
    assert out["comando"] == comando
    assert out["rota"] == "/api/execute"
    assert not espiao, "chegou no execute_write: {!r}".format(sql)


@pytest.mark.asyncio
async def test_literal_aberto_decide_pelo_texto_cru(espiao):
    """Lexer que termina com literal aberto pode ter mascarado o que o PG executa.

    Mesma rede da guarda de espinha: a decisao volta pro texto CRU.
    """
    out = await _run("INSERT INTO zz_log (t) VALUES ('aberto); VACUUM FULL leads.processos")
    assert out.get("manutencao_guard") is True
    assert out["comando"] == "VACUUM FULL (SQL nao parseavel)"
    assert not espiao


@pytest.mark.asyncio
async def test_a_recusa_diz_o_porque_e_o_caminho(espiao):
    """⛔ Recusa que nao diz o caminho certo faz a pessoa procurar outra porta."""
    erro = (await _run("VACUUM FULL leads.processos"))["error"]
    assert "ACCESS EXCLUSIVE" in erro, "a mensagem nao diz por que recusou"
    assert "run-migration-internal" in erro
    assert "deploy-gate: autocommit" in erro, "VACUUM numa migration exige autocommit"
    assert "deploy-e-migrations-fe-api" in erro
    assert "REINDEX INDEX CONCURRENTLY" in erro, "falta a saida que nao trava"


@pytest.mark.asyncio
async def test_allow_mojibake_nao_pula_a_guarda(espiao):
    """O unico flag do `execute` e de outro risco; nao ha flag pra esta guarda."""
    out = await _run("CLUSTER leads.processos", allow_mojibake=True)
    assert out.get("manutencao_guard") is True
    assert not espiao


@pytest.mark.asyncio
async def test_a_recusa_e_visivel_no_log(espiao, caplog):
    """⛔ Recusa silenciosa vira 'o comando nao fez nada'. O log guarda o SQL."""
    with caplog.at_level(logging.WARNING, logger=qmod.__name__):
        await _run("ANALYZE zz; REINDEX TABLE leads.processos")
    linha = "\n".join(r.getMessage() for r in caplog.records)
    assert "manutencao_guard" in linha
    assert "REINDEX" in linha
    assert "leads.processos" in linha


# ---------------------------------------------------------------------------
# 2. LIBERADO — controle NEGATIVO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    # --- VACUUM sem FULL ------------------------------------------------------
    "VACUUM leads.processos",
    "vacuum leads.processos",
    "VACUUM",
    "VACUUM ANALYZE leads.processos",
    "VACUUM FREEZE VERBOSE leads.processos",
    "VACUUM (ANALYZE) leads.processos",
    "VACUUM (VERBOSE, ANALYZE) leads.processos",
    # FULL desligado pelo valor
    "VACUUM (FULL false) leads.processos",
    "VACUUM (ANALYZE, FULL off) leads.processos",
    "VACUUM (FULL 0) leads.processos",
    # tabela/coluna cujo nome COMECA por full
    "VACUUM fullerton",
    "VACUUM (ANALYZE) leads.processos (full_name)",
    # --- ANALYZE --------------------------------------------------------------
    "ANALYZE leads.processos",
    "ANALYZE",
    "ANALYZE VERBOSE leads.processos",
    # --- REINDEX ... CONCURRENTLY, na posicao canonica ------------------------
    "REINDEX INDEX CONCURRENTLY leads.ix_processos_numero",
    "REINDEX TABLE CONCURRENTLY leads.processos",
    "reindex table concurrently leads.processos",
    "REINDEX SCHEMA CONCURRENTLY leads",
    "REINDEX (VERBOSE) TABLE CONCURRENTLY leads.processos",
    "REINDEX TABLE /* sem travar */ CONCURRENTLY leads.processos",
    "CREATE INDEX CONCURRENTLY ix_teste ON leads.processos (id)",
    # --- a palavra aparece, mas nao como comando ------------------------------
    "INSERT INTO zz_log (t) VALUES ('VACUUM FULL leads.processos; CLUSTER x')",
    "INSERT INTO zz_log (t) VALUES (1) -- depois: REINDEX TABLE leads.processos",
    "UPDATE zz_t SET cluster = 'a' WHERE id = 1",
    "ALTER TABLE zz_t ADD COLUMN reindex_at timestamptz",
    "COMMENT ON TABLE zz_t IS 'rodar VACUUM FULL na janela'",
    # --- o truque de medicao que a espinha deixa passar de proposito ----------
    "DO $$ DECLARE n int; BEGIN DELETE FROM leads.meritos WHERE id = 1; "
    "GET DIAGNOSTICS n = ROW_COUNT; RAISE EXCEPTION 'MEDIDA: %', n; END $$",
    # --- corpo de funcao: define, nao roda ------------------------------------
    "CREATE FUNCTION zz_f() RETURNS void AS $body$ BEGIN "
    "REINDEX TABLE zz_t; END $body$ LANGUAGE plpgsql",
])
async def test_manutencao_que_nao_trava_segue_liberada(sql, espiao):
    out = await _run(sql)
    assert out["success"] is True, "recusado sem precisar: {!r} -> {}".format(sql, out.get("error"))
    assert "manutencao_guard" not in out
    assert espiao, "nem chegou no execute_write: {!r}".format(sql)


@pytest.mark.asyncio
async def test_literal_aberto_sem_manutencao_que_trava_nao_e_recusado(espiao):
    """A rede do texto cru e NARROW: SQL malformado sem comando que trava segue pro
    Postgres, que e quem tem autoridade pra reclamar de sintaxe."""
    out = await _run("INSERT INTO zz_log (t) VALUES ('aberto); VACUUM zz_tmp")
    assert out["success"] is True
    assert "manutencao_guard" not in out


@pytest.mark.asyncio
async def test_reindex_concurrently_roda_em_autocommit(espiao):
    """O REINDEX que sobra e o CONCURRENTLY, e o PG o proibe em bloco de transacao.

    Sem autocommit ele passaria pela guarda e morreria em "REINDEX CONCURRENTLY
    cannot run inside a transaction block" — a guarda nova nao pode ter trocado
    o REINDEX que trava por um REINDEX que nao roda.
    """
    await _run("REINDEX TABLE CONCURRENTLY leads.processos")
    assert espiao[-1]["autocommit"] is True
