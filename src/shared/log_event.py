"""Structured-event logging helper (T-408).

Format: ``<event_name> key1=value1 key2=value2 ...``

Stable event names are treated as schema — adding fields is fine, renaming is breaking.
"""

from __future__ import annotations

import logging


def log_event(logger: logging.Logger, name: str, /, **fields: object) -> None:
    """Emit one structured log line: ``<name> key1=v1 key2=v2 ...``

    None-valued fields are omitted so optional correlation keys don't pad
    lines with ``key=None`` noise.
    """
    parts = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    logger.info("%s %s", name, parts)
