"""A conexao volta pro pool no modo em que saiu (2026-09-08).

O DEFEITO: `execute_write(autocommit=True)` chamava `conn.set_isolation_level(0)`
e o `putconn` do psycopg2 nao desfazia — ele so chama `rollback()` quando a
transacao NAO esta IDLE, e em AUTOCOMMIT ela ESTA idle. A conexao voltava ligada
e o proximo caller herdava o modo.

⭐⭐ Por que isso e o MULTIPLICADOR e nao um bug isolado: as portas laterais
(`/api/query`, `/api/count`, `/api/explain`) aceitam multi-statement e so nao
PERSISTIAM porque o `putconn` dava rollback numa transacao aberta. Em autocommit
nao ha transacao aberta, logo nao ha rollback — e o DML passa a gravar de
verdade, para tudo que a guarda de tabelas-espinha nao cobre (UPDATE, MERGE,
ALTER ... DROP COLUMN). E o gatilho e rotina: `VACUUM` liga o modo, e a docstring
do `execute` encoraja VACUUM sobre a espinha.

⚠️ COMO ESTE ARQUIVO E CONSTRUIDO, e o que ele NAO prova:
O pool aqui e o `psycopg2.pool.ThreadedConnectionPool` DE VERDADE — so o
`_connect` e trocado. Ou seja: o `_putconn` sob teste e o codigo real do
psycopg2, que e exatamente onde o defeito mora. O que e falso e a CONEXAO, e
ela modela SO os comportamentos medidos em 2026-09-08 contra um PostgreSQL
17.4 real com psycopg2 2.9.11 — cada um citado na linha que o implementa.
⛔ Um fake modela a MINHA crença sobre o psycopg2. O controle contra isso e o
`test_efeito_ponta_a_ponta_com_postgres_de_verdade` no fim do arquivo, que roda
contra um Postgres real (opt-in por `PG_DSN_TESTE`) e mede o EFEITO — DML por
porta lateral persistindo — em vez do flag. Ele PULA no CI de proposito: um
teste que precisa de banco nasceria morto no `gate-testes` do cloudbuild, que
roda sem rede pro banco.
"""
import os
import asyncio
from importlib import import_module

import psycopg2
import pytest
from psycopg2 import extensions as ext

from src import database as db

qmod = import_module("src.tools.query")


# ---------------------------------------------------------------------------
# A conexao falsa. Cada comportamento abaixo foi MEDIDO, nao suposto.
# ---------------------------------------------------------------------------
class CursorFalso:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.conn.executados.append(sql)
        if self.conn.autocommit:
            #: MEDIDO: em autocommit o psycopg2 nao manda BEGIN, entao o backend
            #: fica IDLE — inclusive DEPOIS de um statement que FALHOU (nunca
            #: INERROR). Excecao: um BEGIN vindo do proprio SQL do usuario abre
            #: transacao de verdade e o psycopg2 nao fica sabendo.
            if "BEGIN" in sql.upper():
                self.conn._tx = ext.TRANSACTION_STATUS_INTRANS
                self.conn._tx_do_usuario = True
        else:
            #: MEDIDO: fora do autocommit, o 1o statement abre transacao
            #: implicita (e por isso que toda conexao entregue por
            #: `get_connection` ja sai INTRANS: o `SELECT 1` de
            #: `_is_connection_valid` abriu uma).
            self.conn._tx = ext.TRANSACTION_STATUS_INTRANS
        return None

    def fetchone(self):
        return (1,)

    def close(self):
        pass


class InfoFalsa:
    def __init__(self, conn):
        self.conn = conn

    @property
    def transaction_status(self):
        return self.conn._tx


class ConexaoFalsa:
    def __init__(self):
        self.closed = 0
        self.autocommit = False
        self.isolation_level = ext.ISOLATION_LEVEL_DEFAULT
        self._tx = ext.TRANSACTION_STATUS_IDLE
        self._tx_do_usuario = False
        self.executados = []
        self.info = InfoFalsa(self)

    def cursor(self, cursor_factory=None):
        return CursorFalso(self)

    def get_transaction_status(self):
        return self._tx

    def set_isolation_level(self, level):
        #: MEDIDO: `set_isolation_level` NAO levanta com transacao aberta (nem
        #: INTRANS nem INERROR) — ele encerra a transacao do psycopg2 por
        #: ROLLBACK, nunca por commit. E `set_isolation_level(0)` mexe SO no eixo
        #: `autocommit`: o `isolation_level` fica onde estava (None por default),
        #: o que torna `conn.isolation_level` um observador CEGO pra este
        #: vazamento.
        if not self._tx_do_usuario:
            self._tx = ext.TRANSACTION_STATUS_IDLE
        if level == ext.ISOLATION_LEVEL_AUTOCOMMIT:
            self.autocommit = True
        else:
            self.autocommit = False
            self.isolation_level = level

    def commit(self):
        if not self._tx_do_usuario:
            self._tx = ext.TRANSACTION_STATUS_IDLE

    def rollback(self):
        #: MEDIDO: em autocommit, `conn.rollback()` e NO-OP — o psycopg2 olha o
        #: proprio estado interno, e um BEGIN mandado pelo usuario nao esta la.
        #: O backend fica `idle in transaction` mesmo depois do rollback.
        if self.autocommit or self._tx_do_usuario:
            return
        self._tx = ext.TRANSACTION_STATUS_IDLE

    def close(self):
        self.closed = 1


class PoolFalso(psycopg2.pool.ThreadedConnectionPool):
    """O pool DE VERDADE do psycopg2; so o `_connect` e trocado."""

    def __init__(self, minconn, maxconn):
        self.criadas = []
        super().__init__(minconn, maxconn)

    def _connect(self, key=None):
        conn = ConexaoFalsa()
        self.criadas.append(conn)
        if key is not None:
            self._used[key] = conn
            self._rused[id(conn)] = key
        else:
            self._pool.append(conn)
        return conn


@pytest.fixture
def pool_falso(monkeypatch):
    p = PoolFalso(db.settings.pool_min, db.settings.pool_max)
    monkeypatch.setattr(db, "_connection_pool", p)
    yield p


def _pega_uma():
    """Pega uma conexao do pool e devolve, como qualquer caller faria."""
    with db.get_connection() as c:
        return c


# ---------------------------------------------------------------------------
# O defeito
# ---------------------------------------------------------------------------
def test_conexao_volta_do_vacuum_sem_autocommit(pool_falso):
    """O aceite #1/#2: rodar VACUUM, devolver, pegar de novo — e estar limpo.

    ⛔ MUTANTE: apagar a chamada a `set_isolation_level(DEFAULT)` de
    `_devolve_no_estado_em_que_saiu` deixa este teste VERMELHO.
    ⛔ MUTANTE: trocar o predicado por `conn.isolation_level` tambem — depois do
    `set_isolation_level(0)` ele continua lendo None, entao o reset nunca roda.
    """
    antes = _pega_uma()
    assert antes.autocommit is False, "a conexao ja saiu suja do pool"

    db.execute_write("VACUUM leads.meritos", autocommit=True)

    depois = _pega_uma()
    assert depois is antes, "o pool nao devolveu a mesma conexao (o teste perdeu o alvo)"
    assert depois.autocommit is False, (
        "AUTOCOMMIT VAZOU: a conexao voltou pro pool ligada e o proximo caller "
        "herda o modo. Nesse estado, DML por porta lateral (/api/query, "
        "/api/count) PERSISTE, porque nao ha transacao aberta pra o putconn "
        "dar rollback."
    )


def test_conexao_com_transacao_aberta_em_autocommit_vai_fechada(pool_falso):
    """O caso que reset NENHUM resolve: BEGIN mandado pelo usuario em autocommit.

    Alcancavel hoje pela rota real, porque `needs_autocommit` procura
    "CONCURRENTLY" em QUALQUER posicao do SQL:
        execute("INSERT INTO t VALUES (1); BEGIN /* CONCURRENTLY */")
    O psycopg2 nao sabe dessa transacao, entao nem o reset nem o `rollback()` do
    putconn a fecham — o backend fica `idle in transaction` para sempre,
    segurando lock e snapshot. A unica saida honesta e nao devolver a conexao.

    ⛔ MUTANTE: remover a checagem de `get_transaction_status()` (devolver
    sempre True) deixa este teste VERMELHO.
    """
    with db.get_connection() as c:
        c.set_isolation_level(ext.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = c.cursor()
        cur.execute("INSERT INTO t VALUES (1); BEGIN")
        assert c.get_transaction_status() == ext.TRANSACTION_STATUS_INTRANS

    assert c.closed, (
        "conexao com transacao aberta EM AUTOCOMMIT voltou pro pool. Ela nao "
        "pode ser limpa por reset nem por rollback — tem que ser fechada."
    )
    assert _pega_uma() is not c


# ---------------------------------------------------------------------------
# Controles NEGATIVOS: o conserto nao pode trocar um defeito por outro
# ---------------------------------------------------------------------------
def test_vacuum_ainda_roda_em_autocommit(pool_falso):
    """⛔ O caminho legitimo PRECISA de autocommit e tem que continuar tendo.

    Medido contra Postgres real: `execute_write("VACUUM t", autocommit=False)` e
    `execute_write("CREATE INDEX CONCURRENTLY ...", autocommit=False)` levantam
    `ActiveSqlTransaction: ... cannot run inside a transaction block`. "Consertar"
    o vazamento desligando o modo trocaria um defeito por outro.

    ⛔ MUTANTE: mover o reset pra ANTES do `cursor.execute` (ou simplesmente
    nunca ligar o modo) deixa este teste VERMELHO.
    """
    visto = {}
    original = ConexaoFalsa.cursor

    def espia(self, cursor_factory=None):
        visto["autocommit_no_execute"] = self.autocommit
        return original(self, cursor_factory)

    ConexaoFalsa.cursor = espia
    try:
        db.execute_write("VACUUM leads.meritos", autocommit=True)
    finally:
        ConexaoFalsa.cursor = original

    assert visto["autocommit_no_execute"] is True, (
        "o VACUUM rodou FORA do autocommit — no Postgres de verdade isso levanta "
        "'VACUUM cannot run inside a transaction block'"
    )


def test_conexao_normal_nao_e_fechada(pool_falso):
    """⛔ O reset nao pode virar 'fecha tudo': isso trocaria o vazamento por um
    connect novo a cada request.

    A conexao normal sai do `get_connection` INTRANS (o `SELECT 1` de
    `_is_connection_valid` abriu transacao) — e esse estado NAO pode cair no
    ramo de descarte.

    ⛔ MUTANTE: fazer `_devolve_no_estado_em_que_saiu` devolver False sempre, ou
    tirar o atalho `if not conn.autocommit and ...`, deixa este teste VERMELHO.
    """
    c = _pega_uma()
    for _ in range(5):
        assert _pega_uma() is c, "conexao limpa foi descartada e o pool abriu outra"
    assert not c.closed
    assert len(pool_falso.criadas) == db.settings.pool_min


def test_execute_write_normal_segue_commitando(pool_falso):
    """Controle negativo do outro lado: o caminho SEM autocommit nao mudou."""
    c = _pega_uma()
    db.execute_write("INSERT INTO zz_t VALUES (1)")
    assert "INSERT INTO zz_t VALUES (1)" in c.executados
    assert c.autocommit is False
    assert not c.closed


# ---------------------------------------------------------------------------
# O controle contra o proprio fake: Postgres de verdade, medindo o EFEITO
# ---------------------------------------------------------------------------
#: ⛔ Opt-in por env DEDICADA, nao por `DB_PASSWORD`: quem tem DB_PASSWORD tem o
#: banco de PRODUCAO, e este teste ESCREVE. Rode contra um cluster descartavel:
#:   PG_DSN_TESTE="host=127.0.0.1 port=6789 dbname=postgres user=postgres" pytest tests/
@pytest.mark.skipif(
    not os.environ.get("PG_DSN_TESTE"),
    reason="PG_DSN_TESTE nao definida - o teste de efeito precisa de um Postgres descartavel",
)
def test_efeito_ponta_a_ponta_com_postgres_de_verdade(monkeypatch):
    """O que o fake nao pode provar: que o DML da porta lateral PERSISTE.

    Controle NEGATIVO (conexao limpa) e POSITIVO (apos VACUUM) no mesmo teste —
    sem o negativo, um bug que impedisse qualquer escrita passaria verde.
    """
    dsn = dict(p.split("=", 1) for p in os.environ["PG_DSN_TESTE"].split())
    for chave, env in (("host", "DB_HOST"), ("port", "DB_PORT"),
                       ("dbname", "DB_NAME"), ("user", "DB_USER")):
        monkeypatch.setattr(db.settings, env.lower(), dsn[chave])
    monkeypatch.setattr(db.settings, "db_password", dsn.get("password", "x"))
    monkeypatch.setattr(db, "_connection_pool", None)
    db.init_pool()

    obs = psycopg2.connect(**dsn)
    obs.autocommit = True
    cur = obs.cursor()
    try:
        cur.execute("DROP TABLE IF EXISTS zz_teste_vazamento; "
                    "CREATE TABLE zz_teste_vazamento(id int)")

        def linhas():
            cur.execute("SELECT count(*) FROM zz_teste_vazamento")
            return cur.fetchone()[0]

        # NEGATIVO: conexao limpa -> o putconn da rollback -> nao persiste
        asyncio.run(qmod.query("SELECT 1; INSERT INTO zz_teste_vazamento VALUES (1) -- LIMIT"))
        assert linhas() == 0, "controle negativo falhou: gravou sem vazamento nenhum"

        # POSITIVO: um VACUUM pela rota real e o mesmo DML volta a gravar
        asyncio.run(qmod.execute("VACUUM zz_teste_vazamento"))
        asyncio.run(qmod.query("SELECT 1; INSERT INTO zz_teste_vazamento VALUES (2) -- LIMIT"))
        assert linhas() == 0, (
            "DML por porta lateral PERSISTIU depois de um VACUUM: o autocommit "
            "vazou pelo pool"
        )
    finally:
        cur.execute("DROP TABLE IF EXISTS zz_teste_vazamento")
        obs.close()
        db.close_pool()
        monkeypatch.setattr(db, "_connection_pool", None)
