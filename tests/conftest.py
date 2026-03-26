"""Pytest configuration for repo-root tests."""

# P2 (IMPLEMENTATION_PHASES.md) — ingest/journal modules not present yet; tests live
# ahead of implementation and would break collection. Remove these ignores when
# `src/inspectio/ingest/` and `src/inspectio/journal/` land.
collect_ignore = [
    "unit/ingest",
    "unit/journal",
]
