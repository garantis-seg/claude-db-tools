"""Guarda de tabelas-espinha no `/api/execute` (incidente 2026-09-07, card 869eycwpd).

O que se guarda aqui e a DECISAO (recusa? deixa passar?), nao o efeito no
Postgres — `execute_write` e trocado por um espiao, como em
`test_manutencao_allowlist.py`. Um teste que precisasse de DB seria PULADO no CI
(o `pytestmark` de `test_tools.py` pula tudo sem `DB_PASSWORD`) e a guarda
nasceria morta.

⭐ Os testes vem em TRES blocos, e os tres sao obrigatorios:
  1. RECUSA — a guarda pega o caso do incidente e cada tabela da lista.
  2. FALSO POSITIVO — o que a guarda NAO pode quebrar. Sem este bloco, "recusa
     tudo" passaria verde e a ferramenta ficaria inutil, empurrando quem tem
     trabalho legitimo a procurar uma terceira porta.
  3. BYPASS — as formas de escrever o MESMO delete que uma checagem de prefixo
     deixaria passar (multi-statement, comentario, aspas, nome nu).
"""
import json
import logging
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


# ---------------------------------------------------------------------------
# 1. RECUSA
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o_statement_do_incidente_e_recusado(espiao):
    """O caso literal: em 07/09 isto rodou e apagou o merito 1480844."""
    out = await _run("DELETE FROM leads.meritos WHERE id = 1480844")
    assert out["success"] is False
    assert out["espinha_guard"] is True
    assert out["tabela"] == "leads.meritos"
    assert out["verbo"] == "DELETE"
    assert not espiao, "o DELETE chegou no execute_write"


#: ⭐⭐ A lista ESCRITA A MAO, e ela e o ponto do arquivo inteiro.
#:
#: 🚨 A primeira versao deste teste era `parametrize(sorted(TABELAS_ESPINHA))` —
#: parametrizada SOBRE a propria lista, o que parece elegante e nao mede NADA:
#: tirar uma tabela tira junto o caso de teste dela, e a suite fica verde. Medido
#: com `scripts/mutantes.py`: comentar `telemetria.capa_parqueados_compras` e
#: `app.merito_audit_log` deixava 53 testes passando. So `leads.meritos`
#: reprovava, e por acidente — porque OUTROS testes a citam literalmente.
#: ⇒ o teste tem de conhecer a lista por FORA da fonte que ele guarda.
#: ⛔ Mexer aqui e mexer numa lista de seguranca: se este teste ficou vermelho,
#: a pergunta e se a mudanca na `TABELAS_ESPINHA` foi deliberada — nao "como
#: fazer o teste passar".
ESPERADAS = {
    "leads.meritos",
    "leads.merito_membros",
    "leads.processos",
    "app.merito_audit_log",
    "telemetria.provider_cost_ledger",
    "telemetria.autos_tentativas",
    "telemetria.capa_parqueados_compras",
    "leitura_conexos.risk_snapshots_safe_state_prelaunch",
}


def test_a_lista_nao_encolheu_nem_cresceu_sem_review():
    """⭐ O mutante do ACEITE 1: tirar uma tabela da lista => VERMELHO."""
    assert set(qmod.TABELAS_ESPINHA) == ESPERADAS, (
        "TABELAS_ESPINHA mudou. Faltando: {} | Sobrando: {}".format(
            sorted(ESPERADAS - set(qmod.TABELAS_ESPINHA)),
            sorted(set(qmod.TABELAS_ESPINHA) - ESPERADAS),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tabela", sorted(ESPERADAS))
async def test_toda_tabela_da_lista_e_protegida(tabela, espiao):
    """Cada tabela esperada REALMENTE recusa os 3 verbos — nao basta constar."""
    for verbo, sql in (
        ("DELETE", "DELETE FROM {} WHERE id = 1".format(tabela)),
        ("TRUNCATE", "TRUNCATE TABLE {}".format(tabela)),
        ("DROP TABLE", "DROP TABLE {}".format(tabela)),
    ):
        out = await _run(sql)
        assert out["success"] is False, "{} passou".format(sql)
        assert out["espinha_guard"] is True
        assert out["verbo"] == verbo
    assert not espiao


@pytest.mark.asyncio
async def test_drop_schema_leva_a_espinha_junto_sem_nomear_tabela(espiao):
    """`DROP SCHEMA leads CASCADE` leva 3 tabelas da lista sem citar nenhuma."""
    out = await _run("DROP SCHEMA leads CASCADE")
    assert out["success"] is False
    assert out["verbo"] == "DROP SCHEMA"
    assert out["tabela"] == "leads"
    assert not espiao


@pytest.mark.asyncio
async def test_a_recusa_nomeia_a_migration(espiao):
    """⛔ Recusa que nao diz o caminho certo faz a pessoa procurar outra porta."""
    out = await _run("DELETE FROM leads.meritos WHERE id = 1")
    assert "run-migration-internal" in out["error"]
    assert "X-Admin-Secret" in out["error"]
    assert "RAISE EXCEPTION" in out["error"], "a saida de medicao tem de estar na mensagem"


@pytest.mark.asyncio
async def test_a_recusa_e_visivel_no_log(espiao, caplog):
    """⛔ Recusa silenciosa vira 'o comando nao fez nada'."""
    with caplog.at_level(logging.WARNING, logger=qmod.__name__):
        await _run("TRUNCATE leads.merito_membros")
    linha = "\n".join(r.getMessage() for r in caplog.records)
    assert "espinha_guard" in linha
    assert "leads.merito_membros" in linha
    assert "TRUNCATE" in linha


# ---------------------------------------------------------------------------
# 2. FALSO POSITIVO — o que a guarda NAO pode quebrar
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_o_truque_de_medicao_com_do_raise_continua_passando(espiao):
    """🚨 ACEITE do card: ha uso real disto e ele nao pode quebrar.

    O `RAISE EXCEPTION` garante rollback e devolve o numero pelo campo `error` —
    e o unico canal que atravessa a transacao implicita do /api/execute.
    """
    sql = (
        "DO $$ DECLARE n int; BEGIN "
        "DELETE FROM leads.meritos WHERE id = 1480844; "
        "GET DIAGNOSTICS n = ROW_COUNT; "
        "RAISE EXCEPTION 'MEDIDA: % linhas', n; END $$"
    )
    out = await _run(sql)
    assert out["success"] is True, "o truque de medicao foi bloqueado"
    assert espiao, "o DO nem chegou no execute_write"


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    # nome que CONTEM o de uma protegida, mas nao E ela
    "DELETE FROM arquivo.meritos_20260813 WHERE id = 1",
    "DELETE FROM zz_meritos_backup WHERE id = 1",
    "TRUNCATE TABLE leads.meritos_stage",
    "DROP TABLE arquivo.processos_bkp",
    # objeto que nao perde linha: se recriam
    "DROP INDEX leads.ix_meritos_conexo",
    "DROP VIEW leads.v_meritos_ativos",
    # LE a espinha, nao a apaga — o alvo do DELETE e outra tabela
    "DELETE FROM tmp_ids WHERE id IN (SELECT id FROM leads.meritos)",
    # o nome so aparece dentro de string literal
    "INSERT INTO app.log (msg) VALUES ('DELETE FROM leads.meritos rodou')",
    # comentario nao e comando
    "INSERT INTO tmp_ids (id) VALUES (1) -- DELETE FROM leads.meritos",
    # schema parecido, nao protegido
    "DROP SCHEMA arquivo CASCADE",
])
async def test_trabalho_legitimo_continua_passando(sql, espiao):
    out = await _run(sql)
    assert out["success"] is True, "{} foi recusado sem precisar".format(sql)
    assert espiao, "{} nem chegou no execute_write".format(sql)


@pytest.mark.asyncio
async def test_select_continua_recusado_pelo_allowlist(espiao):
    """Sanity: a guarda nova nao virou a unica porta — o allowlist segue de pe."""
    out = await _run("SELECT 1")
    assert out["success"] is False
    assert "espinha_guard" not in out
    assert not espiao


@pytest.mark.asyncio
async def test_manutencao_na_espinha_continua_liberada(espiao):
    """VACUUM/ANALYZE/REINDEX entraram em 2026-08-15 e nao perdem linha."""
    for sql in ("VACUUM (FULL, ANALYZE) leads.meritos", "REINDEX TABLE leads.meritos"):
        assert (await _run(sql))["success"] is True, sql


# ---------------------------------------------------------------------------
# 3. BYPASS — o MESMO delete, escrito de um jeito que engana checagem de prefixo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    # ⭐ o que quebra uma checagem de prefixo: o verbo lider do CORPO e CREATE.
    # O /api/execute aceita multi-statement em transacao implicita.
    "CREATE TEMP TABLE t (x int); DELETE FROM leads.meritos WHERE id = 1",
    # identificador entre aspas
    'DELETE FROM "leads"."meritos" WHERE id = 1',
    'DELETE FROM "leads" . "Meritos" WHERE id = 1',
    # case e espaco em branco
    "delete\n\tfrom\n  leads.meritos\nwhere id = 1",
    # comentario no meio do comando
    "DELETE /* nada pra ver aqui */ FROM leads.meritos WHERE id = 1",
    "DELETE --\nFROM leads.meritos WHERE id = 1",
    # nome NU: `SET search_path TO leads` alcanca o mesmo alvo
    "DELETE FROM meritos WHERE id = 1",
    "TRUNCATE meritos",
    # alvo no meio de uma lista
    "TRUNCATE TABLE tmp_a, leads.merito_membros, tmp_b",
    "DROP TABLE IF EXISTS tmp_a, leads.processos",
    # ONLY / alias
    "DELETE FROM ONLY leads.meritos WHERE id = 1",
    "DELETE FROM leads.meritos m WHERE m.id = 1",
    # dollar-quoting com tag nao esconde o statement de FORA do bloco
    "INSERT INTO app.log (msg) VALUES ($tag$ oi $tag$); DELETE FROM leads.meritos",
])
async def test_desvio_conhecido_nao_passa(sql, espiao):
    out = await _run(sql)
    assert out["success"] is False, "PASSOU: {}".format(sql)
    assert out["espinha_guard"] is True
    assert not espiao, "chegou no execute_write: {}".format(sql)


@pytest.mark.asyncio
async def test_apostrofo_em_comentario_nao_desliga_a_guarda(espiao):
    """🚨 O furo ACIDENTAL mais grave que o red-team achou, e o mais provavel.

    Um scanner que respeita string literal mas NAO tira comentario ANTES ve o
    apostrofo de "p'ra" como abertura de literal, passa a achar que todo o resto
    esta dentro de string, deixa de quebrar no `;` e cola o DELETE no statement
    liderado por INSERT. Qualquer comentario em portugues com apostrofo
    ("nao ha", "d'agua", "p'ra") desligaria a guarda em SILENCIO.

    `_mascara` varre da esquerda pra direita e testa `--` ANTES de `'`, entao o
    apostrofo ja esta dentro do comentario mascarado quando chega a vez da aspa.
    """
    sql = (
        "INSERT INTO zz_log (t) VALUES ('x'); -- nao e p'ra apagar nada\n"
        "DELETE FROM leads.meritos"
    )
    out = await _run(sql)
    assert out["success"] is False, "o comentario com apostrofo desligou a guarda"
    assert out["tabela"] == "leads.meritos"
    assert not espiao


@pytest.mark.asyncio
async def test_e_string_com_barra_nao_engole_o_statement_seguinte(espiao):
    """🚨 Em `E'a\\'b'` a BARRA escapa a aspa — o PG entende, lexer ingenuo nao.

    Sem tratar E-string, o lexer fecha a string uma aspa cedo, REABRE na aspa
    seguinte e nunca mais fecha: engole `); DELETE FROM leads.meritos` inteiro e
    a guarda passa verde num statement que o Postgres EXECUTA. Direcao errada de
    errar. (Medido: era exatamente o que esta implementacao fazia antes.)
    """
    out = await _run("INSERT INTO zz_log (t) VALUES (E'a\\'b'); DELETE FROM leads.meritos")
    assert out["success"] is False, "a E-string engoliu o DELETE"
    assert out["tabela"] == "leads.meritos"
    assert not espiao


@pytest.mark.asyncio
async def test_literal_aberto_recusa_em_vez_de_adivinhar(espiao):
    """Rede geral: lexer que termina aberto pode ter mascarado o que o PG roda.

    Aqui a decisao volta pro texto CRU — espinha + verbo destrutivo => recusa.
    """
    out = await _run("INSERT INTO zz_log (t) VALUES ('aberto); DELETE FROM leads.meritos")
    assert out["success"] is False
    assert "nao parseavel" in out["verbo"]
    assert not espiao


@pytest.mark.asyncio
async def test_literal_aberto_sem_espinha_nao_e_recusado(espiao):
    """A rede acima e NARROW: SQL malformado sem espinha segue pro Postgres,
    que e quem tem autoridade pra reclamar de sintaxe."""
    out = await _run("INSERT INTO zz_log (t) VALUES ('aberto); DELETE FROM zz_tmp")
    assert out["success"] is True


@pytest.mark.asyncio
async def test_cte_que_apaga_nao_passa_pelo_lider_WITH(espiao):
    """O verbo lider e `WITH`, entao nenhum padrao de alvo casa.

    E JA e alcancavel hoje: o allowlist so olha o 1o verbo do CORPO, entao um
    INSERT na frente carrega o CTE junto. ⛔ Nao conte com o allowlist pra isto.
    """
    sql = (
        "INSERT INTO zz_log (t) VALUES ('x'); "
        "WITH d AS (DELETE FROM leads.meritos RETURNING id) SELECT count(*) FROM d"
    )
    out = await _run(sql)
    assert out["success"] is False, "CTE que apaga passou"
    assert out["verbo"] == "DELETE"
    assert out["tabela"] == "leads.meritos"
    assert not espiao


@pytest.mark.asyncio
async def test_do_com_TAG_tambem_preserva_a_medicao(espiao):
    """⚠️ FP grave se o lexer so conhecer `$$`: com `$m$` ele quebra no `;` de
    dentro do corpo e produz um fragmento liderado por DELETE => recusa.

    Quem escreve a guarda testa com `$$`, ve verde, e o uso real com tag quebra.
    """
    sql = (
        "DO $m$ BEGIN RAISE NOTICE 'inicio'; DELETE FROM leads.meritos; "
        "RAISE EXCEPTION 'MEDIDA'; END $m$"
    )
    assert (await _run(sql))["success"] is True, "DO com tag foi recusado"


@pytest.mark.asyncio
async def test_create_function_com_delete_no_corpo_nao_e_recusado(espiao):
    """Define uma funcao; nao apaga nada agora. O lider e CREATE.

    Mesma familia do DO com tag: quem nao entende `$tag$` quebra no `;` interno.
    """
    sql = (
        "CREATE FUNCTION zz_f() RETURNS void AS $body$ BEGIN "
        "DELETE FROM leads.meritos WHERE id = 1; END $body$ LANGUAGE plpgsql"
    )
    assert (await _run(sql))["success"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    # --- involucros que empurram o verbo lider pra outra palavra --------------
    # (todos verificados contra o parser real do PG via pglast)
    "CREATE TEMP TABLE t (x int); WITH ids AS (SELECT 1 AS id) "
    "DELETE FROM leads.meritos WHERE id IN (SELECT id FROM ids)",
    "INSERT INTO zz (t) VALUES (1); "
    "WITH d AS (DELETE FROM leads.meritos RETURNING id) SELECT count(*) FROM d",
    # 🚨 EXPLAIN ANALYZE EXECUTA — e e o comando que se digita por achar que nao
    "CREATE TEMP TABLE t (x int); EXPLAIN ANALYZE DELETE FROM leads.meritos WHERE id=1",
    "CREATE TEMP TABLE t (x int); PREPARE p AS DELETE FROM leads.meritos WHERE id=1",
    # --- o PG nao exige separador antes de identificador citado ---------------
    'DELETE FROM"leads"."meritos" WHERE id=1',
    'TRUNCATE"leads"."meritos"',
    'DROP SCHEMA"leads"CASCADE',
    'DELETE FROM"meritos"',
    # --- ONLY / * sao POR ELEMENTO da lista ----------------------------------
    "TRUNCATE tmp_a, ONLY leads.meritos",
    "TRUNCATE tmp_a *, leads.meritos RESTART IDENTITY CASCADE",
    # --- identificador citado engolindo o mascarador -------------------------
    'CREATE TABLE "a--b" (x int); DELETE FROM leads.meritos WHERE id = 1',
    'CREATE TABLE "a/*b" (x int); DELETE FROM leads.meritos WHERE id = 1',
    'CREATE TABLE "it\'s" (x int); DELETE FROM leads.meritos',
    # --- `$` e ident_cont: `a$$b` NAO abre dollar-quote ----------------------
    "CREATE TABLE a$$b (x int); DELETE FROM leads.meritos; CREATE TABLE c$$d (y int)",
    # --- CR sozinho TERMINA comentario no lexer do PG ------------------------
    "INSERT INTO zz (t) VALUES (1); -- x\rDELETE FROM leads.meritos",
    # --- `E` final de palavra nao liga o modo escape -------------------------
    "UPDATE zz_t SET x=1 WHERE nome LIKE'a\\'; DELETE FROM leads.meritos; --'",
])
async def test_desvio_medido_contra_o_parser_real_nao_passa(sql, espiao):
    """⭐⭐ Achados da verificacao adversarial de 2026-09-07.

    Cada um destes PASSAVA na 1a versao da guarda e foi confirmado contra o
    parser real do Postgres (pglast/libpg_query) — nao sao hipoteses.
    """
    out = await _run(sql)
    assert out["success"] is False, "PASSOU: {}".format(sql)
    assert out["espinha_guard"] is True
    assert not espiao, "chegou no execute_write: {}".format(sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("sql,nome", [
    ("INSERT INTO zz (t) VALUES ('aberto); DELETE FROM meritos", "meritos"),
    ("INSERT INTO zz (t) VALUES ('aberto); DROP SCHEMA leads CASCADE", "leads"),
])
async def test_rede_de_literal_aberto_ve_nome_nu_e_schema(sql, nome, espiao):
    """A rede varria so os nomes QUALIFICADOS — justamente no ramo onde o parse
    ja e indigno de confianca. Nome nu e schema escapavam por ali."""
    out = await _run(sql)
    assert out["success"] is False
    assert out["tabela"] == nome
    assert not espiao


@pytest.mark.asyncio
@pytest.mark.parametrize("sql", [
    # o miolo do identificador citado nao e comando: 1 CreateStmt inofensivo
    'CREATE TABLE "x; DELETE FROM leads.meritos" (a int)',
    # tag de dollar-quote com byte alto e valida no PG (dolq_start inclui \\200-\\377)
    "DO $é$ BEGIN DELETE FROM leads.meritos; RAISE EXCEPTION 'MEDIDA'; END $é$",
])
async def test_falso_positivo_do_lexer_foi_eliminado(sql, espiao):
    out = await _run(sql)
    assert out["success"] is True, "recusado sem precisar: {}".format(sql)


# ---------------------------------------------------------------------------
# 4. AS OUTRAS PORTAS — mesmo servico, mesmo token, mesma tabela
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_query_nao_e_porta_de_escrita(monkeypatch):
    """🚨 `startswith("SELECT")` nao faz a rota read-only: o psycopg2 executa
    multi-statement, e o `LIMIT` nem chega a ser anexado porque a palavra ja esta
    no corpo. Guarda so no /api/execute seria teatro."""
    vistos = []
    monkeypatch.setattr(qmod, "execute_query", lambda sql, *a, **k: vistos.append(sql) or [])
    out = json.loads(await qmod.query("SELECT 1 LIMIT 1; DELETE FROM leads.meritos"))
    assert out["success"] is False
    assert out["espinha_guard"] is True
    assert out["rota"] == "/api/query"
    assert not vistos, "o SQL chegou no cursor"


@pytest.mark.asyncio
async def test_api_query_continua_livre_pra_ler(monkeypatch):
    """⛔ Controle: SELECT sobre a espinha e LEITURA e tem de seguir livre."""
    monkeypatch.setattr(qmod, "execute_query", lambda sql, *a, **k: [{"n": 41}])
    out = json.loads(await qmod.query("SELECT count(*) AS n FROM leads.meritos"))
    assert out["success"] is True
    assert out["data"] == [{"n": 41}]


@pytest.mark.asyncio
async def test_api_count_guarda_o_where_concatenado(monkeypatch):
    vistos = []
    monkeypatch.setattr(qmod, "execute_query", lambda sql, *a, **k: vistos.append(sql) or [])
    out = json.loads(await qmod.count("zz_t", where="1=1; DELETE FROM leads.meritos"))
    assert out["success"] is False
    assert out["espinha_guard"] is True
    assert not vistos


@pytest.mark.asyncio
async def test_api_explain_analyze_executa_e_por_isso_e_guardado(monkeypatch):
    """`EXPLAIN ANALYZE <dml>` EXECUTA, e `analyze=True` e o default."""
    smod = import_module("src.tools.stats")

    def boom(*a, **k):
        raise AssertionError("chegou no banco")

    monkeypatch.setattr(smod, "get_connection", boom)
    out = json.loads(await smod.explain_query("DELETE FROM leads.meritos WHERE id=1"))
    assert out["success"] is False
    assert out["espinha_guard"] is True
    assert out["rota"] == "/api/explain"


@pytest.mark.asyncio
async def test_bypass_por_do_block_e_LOGADO(espiao, caplog):
    """⚠️ O bloco DO e um buraco CONHECIDO e nao fechavel sem matar a medicao.

    Nao da pra distinguir a medicao (com `RAISE EXCEPTION`) do desvio de verdade
    — um `RAISE` dentro de um `IF` que nunca roda derrota qualquer heuristica.
    Entao o que se compra e VISIBILIDADE: passa, mas fica no log.
    """
    with caplog.at_level(logging.WARNING, logger=qmod.__name__):
        out = await _run("DO $$ BEGIN DELETE FROM leads.meritos; END $$")
    assert out["success"] is True, "o DO deixou de passar — a medicao quebrou junto"
    assert "BURACO CONHECIDO" in "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("sql,alvo", [
    # ⛔ nome NU: e o motivo de ESPINHA_SEM_SCHEMA existir, e o log nao via
    ("DO $$ BEGIN DELETE FROM meritos; END $$", "meritos"),
    # ⛔ multi-statement: e LITERALMENTE a tecnica que esta guarda existe pra
    # derrotar, e o log dela era mudo
    ("INSERT INTO zz (t) VALUES (1); DO $$ BEGIN DELETE FROM leads.meritos; END $$",
     "leads.meritos"),
])
async def test_o_log_do_buraco_ve_as_formas_que_importam(sql, alvo, espiao, caplog):
    """O predicado do log era `startswith("DO")` + nome qualificado — mudo nas
    duas formas mais provaveis. Hoje ele e a PROPRIA guarda com o corpo visivel."""
    with caplog.at_level(logging.WARNING, logger=qmod.__name__):
        assert (await _run(sql))["success"] is True
    linha = "\n".join(r.getMessage() for r in caplog.records)
    assert "BURACO CONHECIDO" in linha
    assert alvo in linha, "o log do desvio nao nomeia a tabela"


@pytest.mark.asyncio
async def test_medicao_legitima_tambem_e_logada_e_isso_e_esperado(espiao, caplog):
    """⚠️ O log NAO distingue medicao de desvio — nao ha como (um `RAISE` dentro
    de um `IF` que nunca roda derrota qualquer heuristica). Ele registra que
    ALGUEM olhou pra espinha por dentro de um bloco; quem le decide."""
    with caplog.at_level(logging.WARNING, logger=qmod.__name__):
        await _run(
            "DO $$ BEGIN DELETE FROM leads.meritos; RAISE EXCEPTION 'MEDIDA'; END $$"
        )
    assert "BURACO CONHECIDO" in "\n".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# O mascarador, direto — os casos onde ele PODE divergir do Postgres
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql,vivo", [
    ("a -- b\nc", "a     \nc"),
    ("a /* b */ c", "a         c"),
    ("a 'b;c' d", "a       d"),
    ("a 'b''c' d", "a        d"),
    ("a $$b;c$$ d", "a         d"),
    ("a $t$b$t$ d", "a         d"),
])
def test_mascara_preserva_posicao(sql, vivo):
    """A saida e espelho posicional da entrada — senao o split por `;` mente."""
    out, aberto = qmod._mascara(sql)
    assert len(out) == len(sql)
    assert out == vivo
    assert aberto is False


def test_mascara_erra_na_direcao_SEGURA():
    """⚠️ Onde este lexer diverge do Postgres, ele deixa MAIS codigo vivo.

    Comentario aninhado: o PG fecha o `/*` externo no `*/` final; este lexer fecha
    no primeiro. Sobra `DELETE ...` vivo => a guarda RECUSA. Errar recusando e o
    lado certo de errar.
    """
    sql = "/* /* */ DELETE FROM leads.meritos */"
    assert "DELETE" in qmod._mascara(sql)[0].upper()
    assert qmod._alvo_de_espinha(sql) == ("DELETE", "leads.meritos")


def test_mascara_entende_E_string():
    """A BARRA escapa a aspa em `E'...'`; sem isso o lexer fecha cedo e desanda.

    🚨 Pinado SEPARADO do teste de ponta a ponta de proposito: la a recusa
    acontece pelas DUAS defesas (E-string + rede de literal aberto), entao
    desligar o tratamento de E-string mantinha o teste verde — mutante VIVO,
    medido. Aqui o alvo e so o lexer.
    """
    out, aberto = qmod._mascara("SELECT E'a\\'b' AS c")
    assert aberto is False, "a E-string dessincronizou o lexer"
    assert "AS c" in out, "o lexer engoliu o resto do statement"


def test_mascara_sinaliza_literal_aberto():
    assert qmod._mascara("SELECT 'a'")[1] is False
    assert qmod._mascara("SELECT 'a")[1] is True
    assert qmod._mascara("DO $$ x")[1] is True
