"""Review bounded context — PR review pipeline turn accounting.

Owns the ``pr_review_turns`` table and the ``IReviewTurnRegistry`` interface
consumed by the Gateway's two-stage review sequencer. Gateway imports only
``src.review.interfaces`` — never ``models`` or ``repository`` directly (DDD
cross-context model imports are priority-3 violations).

See ``docs/design/two-stage-pr-review.md`` §3 for the design rationale and
``docs/ddd-context-map.md`` for the context-map position.
"""
