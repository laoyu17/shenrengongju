"""Analysis utilities for post-run auditing."""

from .audit import build_audit_report
from .compare import (
    build_compare_report,
    build_multi_compare_report,
    compare_report_to_rows,
    render_compare_report_markdown,
)
from .model_relations import (
    build_model_relations_checks,
    build_model_relations_report,
    model_relations_report_to_rows,
)
from .research_report import (
    build_research_report_payload,
    render_research_report_markdown,
    research_report_to_rows,
)

__all__ = [
    "build_audit_report",
    "build_compare_report",
    "build_multi_compare_report",
    "compare_report_to_rows",
    "render_compare_report_markdown",
    "build_model_relations_checks",
    "build_model_relations_report",
    "model_relations_report_to_rows",
    "build_research_report_payload",
    "render_research_report_markdown",
    "research_report_to_rows",
]
