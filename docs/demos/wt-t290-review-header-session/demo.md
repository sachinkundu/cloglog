# T-290: GitHub PR reviewers can now tell which of the five per-PR codex sessions they are looking at — the review body header renders cross-session 'session N/5' instead of the ambiguous per-session 'turn 1/2' that looked identical on every webhook firing.

*2026-04-24T16:22:31Z by Showboat 0.6.1*
<!-- showboat-id: 8e772b22-4b69-4085-84be-8ec2aae47d57 -->

Context — the bug (PR #209, 2026-04-23): two codex reviews on the same PR were both labelled 'codex (Claude 4.x) — turn 1/2'. A reader could not distinguish session 1 from session 2. Root cause: _build_body_header used the PER-SESSION turn counter (capped by codex_max_turns=2 / opencode_max_turns=5) and every session starts fresh at turn 1.

Proof 1 — the new _build_body_header renders 'session N/M' for real inputs. We invoke the function directly with session_index=1,2,3 and a max_sessions=5 cap. No webhook needed; this is the exact string the review body prepends on the GitHub side.

```bash

uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")
from src.gateway.review_loop import ReviewLoop

class _Stub:
    display_label = "codex (Claude 4.x)"

for session_index in (1, 2, 3):
    header = ReviewLoop._build_body_header(
        _Stub(), session_index=session_index, max_sessions=5
    )
    assert header == f"**codex (Claude 4.x) — session {session_index}/5**", header
    print(header)
PY

```

```output
**codex (Claude 4.x) — session 1/5**
**codex (Claude 4.x) — session 2/5**
**codex (Claude 4.x) — session 3/5**
```

Proof 2 — the function signature no longer accepts the intra-session turn parameters. AST inspection confirms the kwargs on _build_body_header are (reviewer, session_index, max_sessions) — the old (turn, max_turns) names are gone, so no caller can silently pass the wrong counter.

```bash

python3 - <<PY
import ast, pathlib
src = pathlib.Path("src/gateway/review_loop.py").read_text()
tree = ast.parse(src)

loop_cls = next(
    n for n in ast.walk(tree)
    if isinstance(n, ast.ClassDef) and n.name == "ReviewLoop"
)
fn = next(
    n for n in loop_cls.body
    if isinstance(n, ast.FunctionDef) and n.name == "_build_body_header"
)
arg_names = [a.arg for a in fn.args.args]
assert arg_names == ["reviewer", "session_index", "max_sessions"], arg_names
print("OK _build_body_header signature: " + ", ".join(arg_names))

# Inspect the return expression VALUE (unparse only the value, not the
# "return" keyword that would itself contain the substring "turn").
ret = next(n for n in fn.body if isinstance(n, ast.Return))
ret_value = ast.unparse(ret.value)
assert "session_index" in ret_value, ret_value
assert "max_sessions" in ret_value, ret_value
assert "turn" not in ret_value, ret_value
assert "session " in ret_value, ret_value
print("OK header return value renders session_index / max_sessions (no turn)")
PY

```

```output
OK _build_body_header signature: reviewer, session_index, max_sessions
OK header return value renders session_index / max_sessions (no turn)
```

Proof 3 — the ReviewLoop constructor accepts session_index and max_sessions, so the caller (review_engine._review_pr) must pass them. Both kwargs are required (no defaults), which guarantees the caller cannot forget.

```bash

python3 - <<PY
import ast, pathlib
src = pathlib.Path("src/gateway/review_loop.py").read_text()
tree = ast.parse(src)

loop_cls = next(
    n for n in ast.walk(tree)
    if isinstance(n, ast.ClassDef) and n.name == "ReviewLoop"
)
init = next(
    n for n in loop_cls.body
    if isinstance(n, ast.FunctionDef) and n.name == "__init__"
)
# keyword-only args live under fn.args.kwonlyargs
kwonly = [a.arg for a in init.args.kwonlyargs]
assert "session_index" in kwonly, kwonly
assert "max_sessions" in kwonly, kwonly
# Defaults for keyword-only args line up 1:1 with kwonlyargs; required kwargs
# carry a None sentinel in kw_defaults.
defaults = dict(zip(kwonly, init.args.kw_defaults))
assert defaults["session_index"] is None, "session_index must be required (no default)"
assert defaults["max_sessions"] is None, "max_sessions must be required (no default)"
print("OK ReviewLoop.__init__ requires session_index + max_sessions (no defaults)")
PY

```

```output
OK ReviewLoop.__init__ requires session_index + max_sessions (no defaults)
```

Proof 4 — review_engine._review_pr plumbs prior + 1 as session_index into BOTH ReviewLoop constructors (opencode stage A and codex stage B) and uses MAX_REVIEWS_PER_PR as max_sessions. prior is the count of already-posted codex sessions on this PR; this firing becomes session prior + 1.

```bash

python3 - <<PY
import pathlib, re
src = pathlib.Path("src/gateway/review_engine.py").read_text()

# The hoisted session counter must initialise prior = 0 before the
# codex-gated cap check, so opencode-only hosts do not crash.
assert re.search(r"\bprior\s*=\s*0\b", src), "prior must be pre-seeded to 0 for opencode-only hosts"

# session_index = prior + 1 must appear exactly once, outside the
# codex-only gate.
assert re.search(r"\bsession_index\s*=\s*prior\s*\+\s*1\b", src), "session_index = prior + 1 missing"

# Both ReviewLoop constructors must pass session_index + MAX_REVIEWS_PER_PR.
matches = re.findall(
    r"session_index\s*=\s*session_index\s*,\s*max_sessions\s*=\s*MAX_REVIEWS_PER_PR",
    src,
)
assert len(matches) == 2, f"expected 2 ReviewLoop call sites passing session counter, found {len(matches)}"
print(f"OK review_engine threads session_index to {len(matches)} ReviewLoop call sites (stage A + stage B)")
PY

```

```output
OK review_engine threads session_index to 2 ReviewLoop call sites (stage A + stage B)
```

Proof 5 — the full two-stage review sequencer (webhook firing) now posts reviews whose first line is the session header. This test asserts the header string exactly matches "**codex — session 2/5**" when the loop is constructed with session_index=2.

```bash

uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")

# Import the loop test helpers and run the T-290 pin directly — without
# invoking pytest, so the session-autouse Postgres fixture in
# tests/conftest.py does NOT fire on verify (conftest.py is pytest-only;
# plain Python import does not trigger it). Same pattern as
# docs/demos/fix-codex-review-schema/demo-script.sh.
from tests.gateway import test_review_loop as T
import asyncio

fmt = T.TestBuildBodyHeader()
fmt.test_format()
fmt.test_format_with_model_suffix()
print("OK _build_body_header format tests passed (session 2/5 + session 1/5)")

posted = T.TestSessionHeaderInPostedBody()
asyncio.run(posted.test_posted_body_uses_session_counter())
print("OK posted review body first-line is session header (not turn header)")
PY

```

```output
OK _build_body_header format tests passed (session 2/5 + session 1/5)
OK posted review body first-line is session header (not turn header)
```
