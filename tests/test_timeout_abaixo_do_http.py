"""O statement_timeout do banco tem que morrer ANTES do request HTTP.

Incidente 2026-07-31 (21:24 -> 21:54, ~30min de 504 contigo): query_timeout era
300s e o `--timeout` do Cloud Run 110s. O cliente levava 504 aos 110s e a query
seguia rodando por mais ~190s, segurando o slot de concorrencia (8) e a conexao
do pool. Uma rajada de queries analiticas de UMA sessao starvava todas as outras
— ate `SELECT 1` estourava.

Este teste le os DOIS lados (config.py e cloudbuild.yaml) e falha se a ordem se
inverter de novo. Sem framework, sem fixture: le arquivo e compara numero.
"""
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]


def _query_timeout() -> int:
    txt = (_RAIZ / "src" / "config.py").read_text(encoding="utf-8")
    m = re.search(r"^\s*query_timeout:\s*int\s*=\s*(\d+)", txt, re.M)
    assert m, "query_timeout sumiu do config.py"
    return int(m.group(1))


def _http_timeout() -> int:
    """Lê o par posicional ['--timeout', 'N'] do step de deploy do cloudbuild."""
    txt = (_RAIZ / "cloudbuild.yaml").read_text(encoding="utf-8")
    m = re.search(r"-\s*'--timeout'\s*\n\s*-\s*'(\d+)'", txt)
    assert m, "o par --timeout/<N> sumiu do cloudbuild.yaml"
    return int(m.group(1))


def test_statement_timeout_morre_antes_do_request_http():
    q, h = _query_timeout(), _http_timeout()
    assert q < h, (
        f"query_timeout={q}s >= --timeout={h}s do Cloud Run. Query abandonada "
        f"sobrevive ao request e segura o slot de concorrencia — foi exatamente "
        f"o incidente de 2026-07-31."
    )


def test_dockerfile_nao_sobrepoe_query_timeout():
    """ENV QUERY_TIMEOUT no Dockerfile GANHA do default do config.py.

    Ela valia 300 e tornava qualquer mudanca no config.py um NO-OP silencioso —
    o statement_timeout seguia 300s, acima do timeout HTTP. Fonte unica = config.py.
    """
    txt = (_RAIZ / "Dockerfile").read_text(encoding="utf-8")
    ativo = [
        l for l in txt.splitlines()
        if "QUERY_TIMEOUT=" in l and not l.lstrip().startswith("#")
    ]
    assert not ativo, f"QUERY_TIMEOUT voltou pro Dockerfile e anula o config.py: {ativo}"


def test_concurrency_declarada_no_cloudbuild():
    """Sem --concurrency o deploy volta pro default 80 e o tuning vivo (8) some."""
    txt = (_RAIZ / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert re.search(r"-\s*'--concurrency'\s*\n\s*-\s*'\d+'", txt), (
        "--concurrency nao declarado: o proximo deploy reverteria pro default 80"
    )


if __name__ == "__main__":
    test_statement_timeout_morre_antes_do_request_http()
    test_dockerfile_nao_sobrepoe_query_timeout()
    test_concurrency_declarada_no_cloudbuild()
    print(f"ok — query_timeout={_query_timeout()}s < http={_http_timeout()}s")
