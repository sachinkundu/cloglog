"""T-275 verify-safe proof: ``filter_diff`` drops only the showboat-rendered
``demo.md`` under ``docs/demos/``, and lets sibling helper scripts through.

PR #197 round 2 codex HIGH: a broader ``docs/demos/`` filter would hide real
executable code from stage-B review (`scripts/check-demo.sh` and
`scripts/run-demo.sh` execute `demo-script.sh` + `proof_*.py` from that tree
on every `make quality`). This proof constructs a diff with BOTH file kinds
and asserts only the byte-exact ``demo.md`` is filtered.

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
    rendered_md = "docs/demos/wt-disable-opencode-skip-demos/demo.md"
    nested_md = "docs/demos/wt-foo/T-123/demo.md"
    helper_sh = "docs/demos/wt-disable-opencode-skip-demos/demo-script.sh"
    helper_py = "docs/demos/wt-disable-opencode-skip-demos/proof_filter_diff.py"
    unrelated = "src/gateway/review_engine.py"

    diff = "\n".join(
        _section(p) for p in (rendered_md, nested_md, helper_sh, helper_py, unrelated)
    )
    out = filter_diff(diff)

    demo_md_dropped = rendered_md not in out and nested_md not in out
    helpers_kept = helper_sh in out and helper_py in out
    unrelated_kept = unrelated in out

    print(f"demo_md_dropped={demo_md_dropped}")
    print(f"helper_scripts_kept={helpers_kept}")
    print(f"unrelated_source_kept={unrelated_kept}")

    assert demo_md_dropped, "filter_diff must drop ALL demo.md sections under docs/demos/"
    assert helpers_kept, (
        "filter_diff must keep demo-script.sh / proof_*.py — they are executed "
        "by scripts/check-demo.sh and scripts/run-demo.sh on every make quality."
    )
    assert unrelated_kept, "unrelated source sections must pass through unchanged"
    print("filter_diff_proof=PASS")


if __name__ == "__main__":
    main()
