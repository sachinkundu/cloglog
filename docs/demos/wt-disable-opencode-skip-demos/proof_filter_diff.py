"""T-275 verify-safe proof: filter_diff strips docs/demos/ sections.

Constructs a two-section unified diff — one ``docs/demos/...`` section and one
``src/gateway/review_engine.py`` section — runs the real ``filter_diff``, and
asserts the demo section is gone while the code section survives.

Verify-safe — pure function call, no I/O.
"""

from __future__ import annotations

from src.gateway.review_engine import filter_diff


def _section(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1 +1 @@\n"
        f"-a\n"
        f"+b"
    )


def main() -> None:
    demo_path = "docs/demos/wt-disable-opencode-skip-demos/demo.md"
    code_path = "src/gateway/review_engine.py"
    diff = _section(demo_path) + "\n" + _section(code_path)
    out = filter_diff(diff)
    demo_dropped = "docs/demos/" not in out
    code_kept = code_path in out
    print(f"filter_diff_dropped_demo_section={demo_dropped}")
    print(f"filter_diff_kept_src_section={code_kept}")
    assert demo_dropped, "filter_diff must drop the docs/demos/ section"
    assert code_kept, "filter_diff must keep the src/gateway/ section"
    print("filter_diff_proof=PASS")


if __name__ == "__main__":
    main()
