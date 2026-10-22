"""The Benchmarks page."""

from .... import paths
from ...report import _benchmarks, _more


def page_benchmarks(conn, f):
    head, detail = _benchmarks(conn, paths.tasks())
    return f'<section class="card" id="benchmarks">{head}</section>{_more("Benchmark details", "every run and answer", detail)}'
