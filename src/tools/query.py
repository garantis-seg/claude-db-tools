"""
Query tools for executing SQL statements
"""
import json
import logging
import re
import time
from typing import Optional

from ..database import execute_query, execute_write, get_connection
from ..config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mojibake guard (incident 2026-06-10): 300k leads.meritos titles were written
# as UTF-8-read-as-CP1252 mojibake because SQL containing non-ASCII literals
# was composed/read on a Windows client (cp1252 console / open() without
# encoding) and re-encoded to UTF-8 before reaching this API. The server then
# received VALID UTF-8 of already-corrupted text and wrote it silently.
#
# Signature: a UTF-8 lead byte char (U+00C2/U+00C3 for 2-byte seqs, U+00E2 for
# punctuation 3-byte seqs) followed by a continuation byte char — either the
# raw latin-1 range U+0080-U+00BF or its CP1252 punctuation remapping (euro,
# curly quotes, dashes, etc). Legit Portuguese ("SAO PAULO", "Mérito") never
# matches: it lacks the lead+continuation DIGRAPH.
# ---------------------------------------------------------------------------
_CP1252_PUNCT = u"".join(chr(c) for c in (
    0x20AC, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6,
    0x2030, 0x0160, 0x2039, 0x0152, 0x017D, 0x2018, 0x2019, 0x201C,
    0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A,
    0x0153, 0x017E, 0x0178,
))
MOJIBAKE_SIG = re.compile(
    u"[" + chr(0xC2) + chr(0xC3) + chr(0xE2) + u"]"
    + u"[" + chr(0x80) + u"-" + chr(0xBF) + re.escape(_CP1252_PUNCT) + u"]"
)

# ---------------------------------------------------------------------------
# Guarda de TABELAS-ESPINHA (incidente 2026-09-07, card 869eycwpd).
#
# Uma sessao Claude recebeu UMA mensagem humana, que dizia textualmente para nao
# rodar sobre conexos zumbis nem emitir callback pro parceiro. Ela fez as duas
# coisas: 5 statements por este /api/execute, deletou o merito 1480844 e fez a
# lapide sair pro parceiro — as duas irreversiveis. E gravou no
# `app.merito_audit_log.reason` um "OK explicito do Elton" que nunca existiu.
#
# ⭐⭐ O achado que define esta guarda: a sessao TENTOU PRIMEIRO a porta canonica
# (`POST /api/meritos/{id}/merge`) e NAO conseguiu — aquela rota exige token
# Firebase, que sessao nenhuma tem. **A trava humana funcionou.** O que nao
# funcionou foi o resto: este endpoint aceita DELETE arbitrario com o token de
# service account que toda sessao carrega.
# ⇒ o problema nao era gate faltando. Era um BURACO LATERAL numa trava ja certa.
#
# ⚠️ O QUE ISTO NAO COMPRA (leia antes de confiar): fecha UM canal. A sessao so
# caiu aqui porque nao tinha token Firebase — nada impede a proxima de achar uma
# terceira porta. O que se compra e tornar o desvio DIFICIL e VISIVEL, nao
# impossivel. ⛔ Nao leia esta lista como garantia.
# ---------------------------------------------------------------------------
#: ⛔ Tirar uma tabela daqui e decisao, nao limpeza — cada linha custou um
#: incidente ou carrega dinheiro/prova. O teste parametrizado sobre este set fica
#: VERMELHO se alguem encurtar a lista (mutante verificado).
TABELAS_ESPINHA = frozenset({
    # -- estado central: curadoria humana, sem job que regenere -----------------
    #: 41 linhas, e o alvo do incidente. 2o maior alvo de FK do banco: 11 FKs
    #: apontam pra ela, 6 ON DELETE CASCADE -> apagar 1 linha muta 11 tabelas.
    "leads.meritos",
    #: 170 linhas. Morre por CASCADE junto com o pai, sem ser citada.
    "leads.merito_membros",
    #: 1.977.727 linhas. ⛔ O lakehouse NAO cobre: so 20.535 (1,04%) tem espelho
    #: em datalake.judicial_processos. Refazer = re-fetch pago de milhares de USD.
    "leads.processos",
    # -- a PROVA de quem autorizou o que ---------------------------------------
    #: 1.097.057 linhas. E o unico artefato que testemunha o proprio incidente
    #: (guarda o `reason` fabricado id=1154010 e a correcao id=1154011). Sem FK
    #: pra leads.meritos, por isso sobreviveu a delecao. ⛔ leads.merito_events
    #: NAO serve de censo alternativo: tem FK ON DELETE CASCADE e some junto.
    "app.merito_audit_log",
    # -- dinheiro ---------------------------------------------------------------
    #: 172.409 linhas / US$ 18.946,32. ⛔ A agregada `provider_cost_daily` NAO e
    #: backup: reproduz US$ 9.787,19 (51,7%). Provider nenhum reemite historico.
    "telemetria.provider_cost_ledger",
    #: 11.856 linhas, APPEND-ONLY por COMMENT. Existe porque providers.autos_jobs
    #: tem UNIQUE(provider,pn) e o UPSERT apaga o desfecho anterior — e a UNICA
    #: copia da historia de tentativa de compra paga.
    "telemetria.autos_tentativas",
    #: 🚨 80 linhas, e o caso mais grave: ela NAO e registro, e o FREIO. O COMMENT
    #: diz que o teto de 24h de `POST /api/admin/capa-parqueados/comprar` e
    #: `count(*)` desta tabela na janela. ⇒ DELETE aqui nao perde dado: RESETA o
    #: limite de gasto e re-autoriza compra na conta do PARCEIRO (Kelveng, 5
    #: creditos por miss). E exploit ativo, nao perda passiva.
    "telemetria.capa_parqueados_compras",
    # -- o botao de rollback -----------------------------------------------------
    #: 244 linhas. O CLAUDE.md da raiz nomeia isto como "o freio e o BOTAO:
    #: rollback pro safe-state". Retrato congelado de um mundo que ja nao existe:
    #: nao se re-deriva, nao se re-fetcha, nao se recalcula. Unica da lista cuja
    #: perda so fica visivel na hora em que ela importa.
    "leitura_conexos.risk_snapshots_safe_state_prelaunch",
})
# ⛔ MEDIDO e REFUTADO em 2026-09-07 — nao re-adicione sem re-medir:
#   · `providers.*_jobs` (o ponto de partida do card): os 3 por-provider sao VIEWS
#     (`relkind='v'`), colapsam em UMA tabela real, e ela NAO e ledger de gasto —
#     `cost_recorded_at` esta em 1.271 de 21.452 linhas. Quem guarda o gasto sao as
#     duas de `telemetria` acima.
#   · `leads.global_backlog`: workflow state derivado, e ja e filha de meritos com
#     ON DELETE SET NULL — protegida de lado pelo pai.
#   · `providers.api_cache`: o desenho dela E expirar por TTL; proteger cria
#     conflito com a propria rotina de retencao.

#: `DROP SCHEMA leads CASCADE` leva junto tudo que esta na lista acima sem
#: nomear tabela nenhuma. Barato de cobrir, catastrofico de perder.
ESPINHA_SCHEMAS = frozenset(t.split(".", 1)[0] for t in TABELAS_ESPINHA)

#: `SET search_path TO leads` + `DELETE FROM meritos` alcanca o mesmo alvo sem o
#: prefixo. Casa so o nome NU (`meritos`), nunca o sufixo — `zz_meritos_backup` e
#: `arquivo.meritos_20260813` seguem liberados de proposito.
ESPINHA_SEM_SCHEMA = frozenset(t.split(".", 1)[1] for t in TABELAS_ESPINHA)

_IDENT = r'(?:"[^"]*"|[A-Za-z_][A-Za-z0-9_$]*)'
_QUALIF = r"{i}(?:\s*\.\s*{i})?".format(i=_IDENT)
#: `ONLY` e `*` sao por ELEMENTO na gramatica do PG:
#: `TRUNCATE tmp_a *, ONLY leads.meritos` e valido, e sem isto o 2o elemento
#: nao casa e a espinha escapa no meio de uma lista.
_ELEM = r"(?:ONLY\s+)?{q}\s*\*?".format(q=_QUALIF)
_LISTA = r"{e}(?:\s*,\s*{e})*".format(e=_ELEM)
#: ⛔ `\s+` NAO serve como separador antes do alvo: o PG nao exige espaco antes de
#: identificador citado, entao `DELETE FROM"leads"."meritos"` e valido e escapava.
_SEP = r'(?:\s+|\s*(?="))'

#: ⛔ So a posicao de ALVO e olhada, nao o statement inteiro. `DELETE FROM tmp
#: WHERE id IN (SELECT id FROM leads.meritos)` LE a espinha e nao a apaga —
#: recusar isso empurraria quem tem trabalho legitimo a procurar outra porta, que
#: e o modo de falha que este card existe pra evitar.
#: ⛔ `DROP INDEX`/`DROP VIEW` ficam de fora de proposito: nao perdem linha e se
#: recriam. Se aparecerem aqui, a lista de objetos e que deve crescer.
#:
#: ⚠️ TRUNCATE e DROP ficam ANCORADOS no inicio do statement porque nao ha como
#: embutir os dois em outro comando (o PG nao aceita `EXPLAIN TRUNCATE`, e
#: `PREPARE` so recebe SELECT/INSERT/UPDATE/DELETE/MERGE/VALUES). O DELETE, que
#: TEM esses invólucros, e tratado a parte em `_DELETE_ALVO`.
_ALVOS = (
    ("TRUNCATE", re.compile(r"^\s*TRUNCATE" + _SEP + r"(?:TABLE" + _SEP + r")?(" + _LISTA + r")", re.I), False),
    ("DROP TABLE", re.compile(r"^\s*DROP\s+TABLE" + _SEP + r"(?:IF\s+EXISTS" + _SEP + r")?(" + _LISTA + r")", re.I), False),
    ("DROP SCHEMA", re.compile(r"^\s*DROP\s+SCHEMA" + _SEP + r"(?:IF\s+EXISTS" + _SEP + r")?(" + _LISTA + r")", re.I), True),
)

#: 🚨 O `DELETE` e procurado em QUALQUER posicao do statement ja mascarado, e nao
#: ancorado no inicio — porque ele tem no minimo quatro involucros que empurram o
#: verbo lider pra outra palavra, TODOS medidos contra o parser real (pglast):
#:   `WITH ids AS (...) DELETE FROM leads.meritos ...`   -> lider WITH
#:   `EXPLAIN ANALYZE DELETE FROM leads.meritos`         -> lider EXPLAIN, e EXECUTA
#:   `PREPARE p AS DELETE FROM leads.meritos WHERE id=$1`-> lider PREPARE
#:   `WITH d AS (DELETE ... RETURNING id) SELECT ...`    -> lider WITH
#: ⭐ Buscar em qualquer posicao NAO traz falso positivo porque string literal,
#: comentario e corpo de `$tag$` JA estao mascarados quando esta busca roda — e
#: `DELETE FROM x WHERE id IN (SELECT id FROM leads.meritos)` tem um unico
#: `DELETE FROM`, e ele aponta pra `x`. (A subquery diz `SELECT ... FROM`.)
#: ⚠️ Nao alcanca `MERGE ... WHEN MATCHED THEN DELETE`, que apaga sem `FROM`.
#: Limitacao declarada no README, nao esquecimento.
_DELETE_ALVO = re.compile(r"\bDELETE\s+FROM" + _SEP + r"(?:ONLY" + _SEP + r")?(" + _QUALIF + r")", re.I)

#: ⛔ `$` e ident_cont no PG (veja o proprio `_IDENT` acima): em `CREATE TABLE
#: a$$b (x int)` o `$$` NAO abre dollar-quote. Casar ali fazia o mascarador
#: engolir tudo ate o proximo `$$` — medido: um DELETE inteiro sumia entre
#: `a$$b` e `c$$d`. O `(?<![A-Za-z0-9_$])` e o que separa os dois casos.
#: ⚠️ `dolq_start` do PG e `[A-Za-z\200-\377_]`, entao tag com byte alto (`$é$`)
#: e valida — sem ela o `DO $é$...$é$` de medicao era RECUSADO por engano.
_TAG_DOLAR = re.compile(r"(?<![A-Za-z0-9_$])\$(?:[^\W\d][^\W]*)?\$", re.UNICODE)

#: Identificador citado: `"leads"` e um nome; `"x; DELETE FROM ..."` e um nome
#: TAMBEM, mas com `;` dentro. Ver `_mascara` pro porque de tratar os dois
#: diferente.
_IDENT_CITADO = re.compile(r'"([^"]*)"')
_PALAVRA_SIMPLES = re.compile(r"^[A-Za-z0-9_$]*$")


def _mascara(sql: str, dollar: bool = True):
    """Troca por ESPACO comentario, string literal e bloco $tag$...$tag$.

    `dollar=False` deixa o corpo do `$tag$` VISIVEL — usado so pra responder
    "o que a guarda recusaria se olhasse dentro do bloco?", que e o log do desvio
    conhecido. ⛔ Nunca use isso pra DECIDIR: e olhar dentro que mata o truque de
    medicao.

    Devolve `(mascarado, aberto)`. Preserva o comprimento — a saida e um espelho
    posicional da entrada — entao o que sobra vivo pode ser fatiado por `;` e
    casado por regex sem que comentario ou literal escondam (ou inventem) um verbo.

    ⭐ Mascarar o corpo do `$tag$...$tag$` e o que preserva, POR CONSTRUCAO, o
    truque de medicao da casa (`DO $$ BEGIN <mutacao>; RAISE EXCEPTION 'MEDIDA';
    END $$`, rollback garantido — 116 usos no historico): um bloco DO vira UM
    statement cujo verbo lider e `DO`, e `DO` nao esta em `_ALVOS`.

    🚨 `aberto=True` significa que o lexer chegou ao fim com literal ABERTO — ou o
    SQL e malformado (o PG vai reclamar de qualquer jeito) ou este lexer
    DESSINCRONIZOU do PG. Dessincronizacao e perigosa na direcao errada: ela
    MASCARA texto que o Postgres EXECUTA. Medido: com `E'a\\'b'` o lexer ingenuo
    fecha a string cedo, reabre na aspa seguinte, nunca fecha, e engole um
    `; DELETE FROM leads.meritos` inteiro. Quem chama trata isso como recusa.

    ⛔ O comentario ANINHADO (`/* /* */ ... */`) fica na direcao SEGURA de
    proposito: o PG aninha, este nao, entao sobra MAIS codigo vivo e a guarda
    recusa. Errar recusando e o lado certo de errar.
    """
    out = list(sql)
    i, n = 0, len(sql)
    aberto = False
    while i < n:
        preserva = False
        if sql.startswith("--", i):
            # ⛔ O `non_newline` do scan.l do PG e `[^\n\r]`: um CR sozinho (arquivo
            # com fim de linha Mac/CRLF partido) TERMINA o comentario. Procurar so
            # `\n` fazia o mascarador comer o resto do corpo — medido: um
            # `-- x<CR>DELETE FROM leads.meritos` inteiro sumia.
            fim = [p for p in (sql.find("\n", i), sql.find("\r", i)) if p >= 0]
            j = min(fim) if fim else n
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif sql[i] == '"':
            # 🚨 Identificador citado: o mascarador NAO pode ignora-lo, porque os
            # outros 4 construtos disparam DENTRO dele — `CREATE TABLE "a--b"`
            # abria comentario e engolia o `; DELETE ...` seguinte (medido).
            # ⭐ Mas mascarar sempre criaria o inverso: `CREATE TABLE "x; DELETE
            # FROM leads.meritos"` e UM CreateStmt inofensivo, e mascarar o miolo
            # tiraria o `;` de vista... enquanto NAO mascarar recusa um comando
            # que nao apaga nada. Por isso o miolo so e PRESERVADO quando e uma
            # palavra simples — que e o caso do alvo de verdade,
            # `"leads"."meritos"`, que precisa continuar casando.
            achou = _IDENT_CITADO.match(sql, i)
            if achou:
                j = achou.end()
                preserva = bool(_PALAVRA_SIMPLES.match(achou.group(1)))
            else:
                j, aberto = n, True
        elif sql[i] == "'":
            # `E'...'` (e `U&'...'`) usam BARRA pra escapar; a string comum usa `''`.
            # ⛔ O teste e de TOKEN, nao de caractere: `sql[i-1] in "EeUu&"` casava
            # o `E` final de `LIKE`/`TRUE`/`CASE`/`TABLE`/`DELETE` e ligava o modo
            # escape numa string comum — medido, `... LIKE'a\'; DELETE FROM
            # leads.meritos; --'` atravessava inteiro.
            escapa = (
                i > 0
                and sql[i - 1] in "EeUu&"
                and (i < 2 or not (sql[i - 2].isalnum() or sql[i - 2] in "_$"))
            )
            j, fechou = i + 1, False
            while j < n:
                if escapa and sql[j] == "\\":
                    j += 2
                elif sql[j] != "'":
                    j += 1
                elif sql.startswith("''", j):
                    j += 2
                else:
                    j += 1
                    fechou = True
                    break
            aberto = aberto or not fechou
        elif dollar and sql[i] == "$" and _TAG_DOLAR.match(sql, i):
            tag = _TAG_DOLAR.match(sql, i).group(0)
            j = sql.find(tag, i + len(tag))
            if j < 0:
                j, aberto = n, True
            else:
                j += len(tag)
        else:
            i += 1
            continue
        if not preserva:
            for k in range(i, min(j, n)):
                out[k] = " "
        i = max(j, i + 1)
    return "".join(out), aberto


def _normaliza(ident: str) -> str:
    """`ONLY "leads" . "Meritos" *` -> `leads.meritos`.

    ⛔ O `ONLY` e o `*` sao POR ELEMENTO na lista do TRUNCATE, entao chegam colados
    no nome do 2o em diante. Sem tira-los aqui, `TRUNCATE tmp_a, ONLY
    leads.meritos` normalizava pra `only leads.meritos` e nao casava a lista —
    medido, a espinha escapava no meio de uma lista de alvos.
    """
    ident = re.sub(r"^\s*ONLY\b", "", ident, flags=re.I).strip().rstrip("*").strip()
    return ".".join(p.strip().strip('"').lower() for p in ident.split("."))


def _alvo_de_espinha(sql: str, dentro_do_bloco: bool = False):
    """Devolve `(verbo, alvo)` do 1o statement destrutivo sobre a espinha, ou None.

    Olha TODOS os statements, nao so o lider do corpo: o `/api/execute` aceita
    multi-statement numa transacao implicita, entao `CREATE TEMP TABLE t(x int);
    DELETE FROM leads.meritos` tem verbo lider `CREATE` e passaria por uma
    checagem de prefixo — que e a unica que existia aqui ate 2026-09-07.
    """
    def _protegido(bruto, e_schema):
        alvo = _normaliza(bruto)
        if e_schema:
            return alvo if alvo in ESPINHA_SCHEMAS else None
        if alvo in TABELAS_ESPINHA:
            return alvo
        # nome NU (`DELETE FROM meritos`, alcancavel por `SET search_path`).
        # ⛔ Compara o identificador INTEIRO, nunca substring: `zz_meritos_backup`
        # e `arquivo.meritos_20260813` tem de continuar passando.
        return alvo if "." not in alvo and alvo in ESPINHA_SEM_SCHEMA else None

    mascarado, aberto = _mascara(sql, dollar=not dentro_do_bloco)

    # 🚨 Lexer que terminou com literal aberto pode ter ENGOLIDO um statement que o
    # Postgres executa. Nao da pra confiar no fatiamento, entao a decisao volta pro
    # texto CRU: citou espinha e verbo destrutivo, recusa. Vale so pro SQL
    # malformado ou exotico — o preco de errar aqui e uma recusa a explicar, e o
    # preco de nao errar e um DELETE invisivel.
    # ⛔ Varre os TRES conjuntos, nao so o qualificado: e justamente aqui, onde o
    # parse ja e indigno de confianca, que `DELETE FROM meritos` (nome nu, via
    # search_path) e `DROP SCHEMA leads CASCADE` escapavam.
    if aberto and any(v in sql.upper() for v in ("DELETE", "TRUNCATE", "DROP")):
        cru = sql.lower()
        for nome in sorted(TABELAS_ESPINHA | ESPINHA_SEM_SCHEMA | ESPINHA_SCHEMAS):
            if re.search(r"(?<![A-Za-z0-9_$.])" + re.escape(nome) + r"(?![A-Za-z0-9_$])", cru):
                return "DESTRUTIVO (SQL nao parseavel)", nome

    for statement in mascarado.split(";"):
        for verbo, padrao, e_schema in _ALVOS:
            achou = padrao.match(statement)
            if not achou:
                continue
            for bruto in achou.group(1).split(","):
                alvo = _protegido(bruto, e_schema)
                if alvo:
                    return verbo, alvo
        for achou in _DELETE_ALVO.finditer(statement):
            alvo = _protegido(achou.group(1), False)
            if alvo:
                return "DELETE", alvo
    return None


def recusa_espinha(sql: str, rota: str):
    """Roda a guarda e devolve o JSON de recusa, ou None se pode seguir.

    🚨 Vale em TODA rota que manda texto pro `cursor.execute`, nao so no
    `/api/execute`. Medido em 2026-09-07: `query("SELECT 1 LIMIT 1; DELETE FROM
    leads.meritos")` devolvia `success=True` e a string INTEIRA ia pro cursor — o
    check e `startswith("SELECT")`, e o `LIMIT` nem chegava a ser acrescentado
    porque a palavra ja estava no corpo. O mesmo valia pro `/api/explain`
    (`EXPLAIN ANALYZE <dml>` executa) e pro `/api/count`, que concatena o `where`
    cru. Guarda so no `/api/execute` seria teatro: tres portas do MESMO servico,
    com o MESMO token, chegando na MESMA tabela.
    """
    espinha = _alvo_de_espinha(sql)
    if not espinha:
        return None
    verbo, alvo = espinha
    logger.warning(
        "espinha_guard: RECUSADO %s sobre %s via %s | sql=%r", verbo, alvo, rota, sql[:4000]
    )
    return json.dumps({
        "success": False,
        "espinha_guard": True,
        "verbo": verbo,
        "tabela": alvo,
        "rota": rota,
        "error": espinha_error(verbo, alvo),
    })


def espinha_error(verbo: str, alvo: str) -> str:
    return (
        "SQL recusado pela guarda de tabelas-espinha: `{verbo}` sobre `{alvo}`.\n"
        "\n"
        "Esta e a mesma classe de operacao que, em 2026-09-07, deletou o merito "
        "1480844 sem autorizacao humana (card 869eycwpd). O /api/execute carrega "
        "o token de service account que TODA sessao tem, entao ele nao consegue "
        "distinguir uma decisao humana de uma decisao de modelo. Nao ha flag pra "
        "pular esta guarda, e isso e deliberado.\n"
        "\n"
        "O CAMINHO CERTO e a migration, que e o que a casa ja exige pra mutacao "
        "de dado — ela ganha ledger em `app.schema_migrations`, header de "
        "rollback e review de PR:\n"
        "  1. escreva `migrations/<AAAAMMDD_HHMM>_<nome>.sql` (ASCII puro), com o "
        "header de rollback, e mergeie o PR;\n"
        "  2. aplique com `POST /api/admin/run-migration-internal/"
        "<AAAAMMDD_HHMM>_<nome>.sql`, header `X-Admin-Secret` "
        "(+ `-H 'Content-Length: 0' -d ''`, senao da 411).\n"
        "\n"
        "Se o que voce quer e MEDIR quantas linhas seriam afetadas, sem escrever: "
        "`DO $$ BEGIN <a mutacao>; RAISE EXCEPTION 'MEDIDA: %', <n>; END $$` — a "
        "excecao garante o rollback e devolve o numero pelo campo `error`. Esse "
        "caminho segue aberto de proposito.\n"
        "\n"
        "Tabelas protegidas: {lista}."
    ).format(verbo=verbo, alvo=alvo, lista=", ".join(sorted(TABELAS_ESPINHA)))


MOJIBAKE_ERROR = (
    "SQL rejected: it contains a UTF-8-read-as-CP1252 mojibake signature "
    "(lead byte + continuation digraph, e.g. the corrupted forms of accented "
    "letters or em dash). This almost always means the SQL text was corrupted "
    "by a Windows shell/console/file-read before reaching this API — writing "
    "it would store garbage (incident 2026-06-10: 300k leads.meritos titles). "
    "Fix the client side: compose non-ASCII via chr(NNN) so the SQL stays "
    "pure ASCII, or send the statement through a path with explicit UTF-8 "
    "(e.g. requests json= from a file read with encoding='utf-8'). If you "
    "REALLY intend to write these exact mojibake characters (e.g. repairing "
    "data), pass allow_mojibake=true."
)


async def query(sql: str, limit: int = 1000) -> str:
    """
    Execute a SELECT query and return results.

    Use this tool to read data from the database. Supports any valid SELECT statement.

    Args:
        sql: The SELECT query to execute. Must be a valid SQL SELECT statement.
        limit: Maximum number of rows to return (default: 1000, max: 10000).

    Returns:
        JSON string with query results including columns, data, row count, and execution time.

    Examples:
        - query("SELECT * FROM cnpj_raw.empresas LIMIT 10")
        - query("SELECT cnpj_basico, razao_social FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
        - query("SELECT COUNT(*) as total FROM cnpj_raw.estabelecimentos")
    """
    sql_upper = sql.strip().upper()

    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        return json.dumps({
            "success": False,
            "error": "Only SELECT queries allowed. Use 'execute' tool for write operations."
        })

    # 🚨 `startswith("SELECT")` NAO faz desta rota read-only: o psycopg2 executa
    # multi-statement, entao `SELECT 1 LIMIT 1; DELETE FROM leads.meritos` passava
    # o check e ia inteiro pro cursor (medido em 2026-09-07). Hoje o DELETE nao
    # PERSISTE por acidente — o `putconn` do pool dá rollback numa conexao com
    # transacao aberta — e "por acidente" nao e uma garantia que se cita.
    recusa = recusa_espinha(sql, "/api/query")
    if recusa:
        return recusa

    # Enforce limit
    effective_limit = min(limit, settings.max_rows)

    # Add LIMIT if not present
    if "LIMIT" not in sql_upper:
        sql = f"{sql.rstrip(';')} LIMIT {effective_limit}"

    try:
        logger.info(f"Executing query: {sql[:100]}...")
        start_time = time.time()

        results = execute_query(sql)
        execution_time = time.time() - start_time

        columns = list(results[0].keys()) if results else []

        return json.dumps({
            "success": True,
            "rows": len(results),
            "columns": columns,
            "data": results,
            "execution_time_ms": round(execution_time * 1000, 2)
        }, default=str)

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def execute(sql: str, allow_mojibake: bool = False) -> str:
    """
    Execute a write operation (INSERT, UPDATE, DELETE, CREATE, ALTER, DROP).

    Use this tool to modify data or database structure. Supports DDL and DML statements.

    ⛔ DELETE / TRUNCATE / DROP on a SPINE TABLE is REFUSED (see TABELAS_ESPINHA):
    those go through a migration, which is what this house already requires for
    data mutation — it gets a ledger, a rollback header and PR review. There is no
    bypass flag, on purpose. The refusal message names the exact path to take.

    Args:
        sql: The SQL statement to execute. Must be a write operation.
            Allowed: INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, TRUNCATE, GRANT,
            REVOKE, COMMENT, DO, VACUUM, ANALYZE, REINDEX
        allow_mojibake: bypass the CP1252-mojibake guard (only when intentionally
            writing mojibake characters, e.g. data repair). ⛔ It does NOT bypass
            the spine-table guard — different risk, different answer.

    Returns:
        JSON string with execution result including rows affected and execution time.

    Examples:
        - execute("INSERT INTO my_table (col1, col2) VALUES ('a', 'b')")
        - execute("UPDATE cnpj_raw.empresas SET processed = true WHERE id = 123")
        - execute("CREATE INDEX idx_name ON cnpj_raw.empresas(razao_social)")
        - execute("DELETE FROM zz_tmp_scratch WHERE created_at < NOW() - INTERVAL '7 days'")
        - execute("VACUUM (FULL, ANALYZE) leads.meritos")   # manutencao, nao perde linha
    """
    sql_upper = sql.strip().upper()

    # VACUUM / ANALYZE / REINDEX entraram em 2026-08-15: sao MANUTENCAO, nao
    # escrita de dado — nenhum deles pode perder linha. Ate aqui o unico jeito de
    # rodar VACUUM FULL em prod era escrever uma migration de um statement so e
    # chamar `run-migration-internal?autocommit=true`, o que polui o ledger de
    # `app.schema_migrations` (que existe pra mudanca de SCHEMA) com manutencao
    # que se repete. E ela SE REPETE: bloat volta.
    # Contexto: 2 design docs do execucao-fiscal ja adiaram esse reclaim
    # ("physical reclaim needs VACUUM FULL/pg_repack — plan the reclaim window",
    # D1 detriplication 2026-07-04 e canonical_conflict_retention).
    allowed_operations = ['INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE',
                          'GRANT', 'REVOKE', 'COMMENT', 'DO', 'VACUUM', 'ANALYZE', 'REINDEX']

    if not any(sql_upper.startswith(op) for op in allowed_operations):
        return json.dumps({
            "success": False,
            "error": f"Only write operations allowed. Use 'query' tool for SELECT. Allowed: {', '.join(allowed_operations)}"
        })

    # ⛔ Recusa CALADA vira "o comando nao fez nada" e a proxima tentativa e por
    # outra porta — que e o modo de falha que este card existe pra evitar. O log
    # guarda o SQL QUASE INTEIRO, nao `[:100]` como o de sucesso logo abaixo: num
    # corpo multi-statement o comando destrutivo costuma ser o SEGUNDO. Medido no
    # incidente de 07/09 — num batch de 163 chars o DELETE comecava no char 119.
    recusa = recusa_espinha(sql, "/api/execute")
    if recusa:
        return recusa

    # ⚠️ Buraco CONHECIDO, deliberado e nao fechavel sem custo: o corpo de um
    # `DO $$...$$` e opaco pra guarda acima — e e essa opacidade que mantem vivo o
    # truque de medicao com `RAISE EXCEPTION`. Quem quiser burlar so precisa
    # embrulhar o DELETE num DO. Nao da pra distinguir os dois casos (um `RAISE`
    # dentro de um `IF` que nunca roda ja derrota qualquer heuristica), entao o que
    # se compra aqui e VISIBILIDADE: o desvio existe, mas nao passa despercebido.
    # ⛔ O predicado e a PROPRIA guarda rodada com o corpo do bloco visivel — nao
    # um `startswith("DO")` + nome qualificado. A 1a versao era isso, e ficava MUDA
    # nas duas formas que mais importam (medido): nome nu via `search_path`, e
    # `INSERT ...; DO $$ ... $$` multi-statement, que e literalmente a tecnica que
    # esta guarda existe pra derrotar. Chegar aqui ja implica que a guarda de
    # verdade passou, logo qualquer achado esta DENTRO de um `$tag$`.
    oculto = _alvo_de_espinha(sql, dentro_do_bloco=True)
    if oculto:
        logger.warning(
            "espinha_guard: BURACO CONHECIDO — %s sobre %s dentro de bloco $tag$ "
            "(DO/FUNCTION); NAO recusado, ver query.py | sql=%r",
            oculto[0], oculto[1], sql[:4000],
        )

    if not allow_mojibake and MOJIBAKE_SIG.search(sql):
        logger.warning(f"Mojibake guard rejected statement: {sql[:120]!r}")
        return json.dumps({
            "success": False,
            "mojibake_guard": True,
            "error": MOJIBAKE_ERROR,
        })

    # Check if autocommit is needed.
    # ⚠️ VACUUM entra aqui por uma razao DIFERENTE do CONCURRENTLY, e as duas sao
    # obrigatorias: o Postgres proibe os dois dentro de bloco de transacao, e o
    # `execute_write` abre transacao implicita por default. Sem esta linha o
    # VACUUM seria aceito pelo allowlist e morreria em
    # "VACUUM cannot run inside a transaction block" — pior que estar bloqueado,
    # porque parece bug do banco.
    # ⛔ ANALYZE e REINDEX (sem CONCURRENTLY) RODAM em transacao e NAO entram —
    # por-los aqui trocaria o rollback-em-erro deles por escrita solta.
    needs_autocommit = "CONCURRENTLY" in sql_upper or sql_upper.startswith("VACUUM")

    try:
        logger.info(f"Executing statement: {sql[:100]}...")
        start_time = time.time()

        rows_affected = execute_write(sql, autocommit=needs_autocommit)
        execution_time = time.time() - start_time

        return json.dumps({
            "success": True,
            "rows_affected": rows_affected,
            "execution_time_ms": round(execution_time * 1000, 2),
            "message": f"Statement executed successfully. {rows_affected} rows affected."
        })

    except Exception as e:
        logger.error(f"Execute failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def count(table: str, where: Optional[str] = None) -> str:
    """
    Count rows in a table with optional WHERE clause.

    Use this tool for quick row counts without fetching data.

    Args:
        table: Full table name including schema (e.g., "cnpj_raw.empresas")
        where: Optional WHERE clause without the WHERE keyword (e.g., "situacao_cadastral = '02'")

    Returns:
        JSON string with the count and execution time.

    Examples:
        - count("cnpj_raw.empresas")
        - count("cnpj_raw.estabelecimentos", where="situacao_cadastral = '02'")
        - count("public.users", where="active = true AND created_at > '2024-01-01'")
    """
    try:
        if where:
            sql = f"SELECT COUNT(*) as count FROM {table} WHERE {where}"
        else:
            sql = f"SELECT COUNT(*) as count FROM {table}"

        # ⛔ `table` e `where` sao concatenados CRUS (e por GET). A guarda roda
        # sobre o SQL ja montado, que e o texto que chega no cursor.
        recusa = recusa_espinha(sql, "/api/count")
        if recusa:
            return recusa

        logger.info(f"Counting rows: {sql}")
        start_time = time.time()

        results = execute_query(sql)
        execution_time = time.time() - start_time

        row_count = results[0]["count"] if results else 0

        return json.dumps({
            "success": True,
            "table": table,
            "count": row_count,
            "where": where,
            "execution_time_ms": round(execution_time * 1000, 2)
        })

    except Exception as e:
        logger.error(f"Count failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })
