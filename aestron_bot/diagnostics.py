"""Exception formatting helpers shared by command and event diagnostics."""

from __future__ import annotations

import traceback


def format_exception(error: BaseException) -> str:
    """Format an exception with its chained traceback and without local secrets."""
    exception = traceback.TracebackException.from_exception(
        error, capture_locals=False, compact=True
    )
    return "".join(exception.format(chain=True))
