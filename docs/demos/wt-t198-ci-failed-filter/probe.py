"""Demo helper: call AgentNotifierConsumer._build_message with a given check_run
conclusion and print the resulting inbox message (or the string 'None').

Usage:
    python docs/demos/wt-t198-ci-failed-filter/probe.py <conclusion|null>
"""

from __future__ import annotations

import json
import sys

from src.gateway.webhook_consumers import AgentNotifierConsumer
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType


def main() -> None:
    arg = sys.argv[1]
    conclusion: str | None = None if arg == "null" else arg

    event = WebhookEvent(
        type=WebhookEventType.CHECK_RUN_COMPLETED,
        delivery_id=f"demo-{arg}",
        repo_full_name="sachinkundu/cloglog",
        pr_number=198,
        pr_url="https://github.com/sachinkundu/cloglog/pull/198",
        head_branch="wt-demo",
        base_branch="main",
        sender="github-actions[bot]",
        raw={"check_run": {"name": "quality", "conclusion": conclusion}},
    )
    message = AgentNotifierConsumer()._build_message(event)
    if message is None:
        print("None  # no agent inbox message — event silently ignored")
    else:
        print(json.dumps(message, indent=2))


if __name__ == "__main__":
    main()
