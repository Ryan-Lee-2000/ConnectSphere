"""Shared pytest fixtures, re-exported so other test modules can use them by name
without each one redefining `event_app`/`client` as a local parameter (which ruff's
F811 flags as shadowing the import)."""

from test_event_requests import client, event_app  # noqa: F401
