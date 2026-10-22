"""The Benchmarks page."""

from .... import paths
from ...report.sections.benchmarks import _benchmarks
from ...report.widgets import _more


def page_benchmarks(conn, f):
    head, detail = _benchmarks(conn, paths.tasks())
    return f'<section class="card" id="benchmarks">{head}</section>{_more("Benchmark details", "every run and answer", detail)}'
