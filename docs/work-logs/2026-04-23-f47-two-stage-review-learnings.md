# Learnings — F-47 Two-Stage Review (T-261 + T-248)

These are patterns and pitfalls surfaced by the codex + human review cycles on PRs #185 and #187. Consider propagating the `CLAUDE.md`-worthy items to the repo's `CLAUDE.md`.

## Credentials precedent — three different homes for three different kinds of secret

The repo has **three distinct credential paths**, and confusing them is an easy-to-make mistake that codex flagged twice in this wave:

1. **`~/.cloglog/credentials`** — ONLY the backend project API key (`CLOGLOG_API_KEY`). Loaded by `mcp-server/src/credentials.ts`. Mode 0600 recommended. Pinned by `tests/test_mcp_json_no_secret.py` (T-214).
2. **`~/.agent-vm/credentials/<bot>.pem`** — GitHub App private keys. One `.pem` per bot (`github-app.pem` for the code-push claude bot, `codex-reviewer.pem` for codex, `opencode-reviewer.pem` for opencode as of T-248). Minted at runtime via JWT → `POST /app/installations/<id>/access_tokens`.
3. **Backend `.env`** — per-host knobs (database URL, ports, `GITHUB_WEBHOOK_SECRET`, `REVIEW_SOURCE_ROOT`, etc.). **Not** reviewer App IDs — those are public identifiers hard-coded in `src/gateway/github_token.py` (the `_CLAUDE_APP_ID`, `_CODEX_APP_ID`, `_OPENCODE_APP_ID` constants).

**Load-bearing rule:** Reviewer App IDs and installation IDs are **not secrets**. They are public identifiers and belong with the other bot constants in `src/gateway/github_token.py`. Only PEMs go in `~/.agent-vm/credentials/`. When adding a new reviewer bot, follow the `_CLAUDE_*` / `_CODEX_*` shape exactly; don't invent a Settings-based or env-based detour.

## Gateway owns no tables — use an Open Host Service boundary

`docs/ddd-context-map.md:31` says "Gateway owns: no tables" and `docs/contracts/webhook-pipeline-spec.md:29` restates the rule for the review engine specifically. When a new review-pipeline artifact (like `pr_review_turns`) needs persistence, **create a new supporting bounded context** rather than putting the table "under" Gateway or piggybacking on Board/Agent:

1. `src/<context>/models.py` + `interfaces.py` (Protocol) + `repository.py` + `services.py`.
2. Gateway imports **only** `src.<context>.interfaces` (and optionally `services` for factory functions). NEVER `models.py` or `repository.py` — that's a priority-3 DDD violation.
3. The factory (`make_review_turn_registry(session)` in our case) is the Open Host Service entry point. Its return type is the Protocol; the concrete class is hidden inside the function body.

**Regression guard:** write a grep-based test that scans every file under `src/<other-context>/` for `from src.<new-context>.models` / `from src.<new-context>.repository`. Pin it at zero. Lazy imports inside functions count — reviewers will flag them.

## Webhook redelivery — persistent state alone isn't idempotent

`webhook_dispatcher` deduplicates by `delivery_id`, but GitHub sends different delivery IDs for the same logical event (retries, `synchronize` on the same SHA, etc.). The `pr_review_turns` unique constraint is *necessary* but not *sufficient* for idempotency:

1. **Claim-before-run** via `INSERT ... ON CONFLICT DO NOTHING` — if the INSERT touches zero rows, abort.
2. **Short-circuit on persisted consensus** — if any prior turn on `(pr_url, head_sha, stage)` has `consensus_reached=True`, the stage is done; return immediately without running the reviewer.
3. **Failed-turn retry** — a terminal `status='failed'` row must allow a later delivery to re-run that turn number. Implement via `reset_to_running` (flip `failed` → `running`) so the failed row isn't blocking re-claim forever.
4. **Next-turn computation** — when resuming, pick the **lowest `failed`** turn (if any) before falling back to `max(turn_number) + 1`. Without this, a post-failed turn 1 is skipped and its findings are permanently lost.

All four rules are load-bearing. Dropping any one silently breaks redelivery.

## `post_review` failure is not rare — handle it explicitly

The existing `post_review` in `review_engine.py` retries once with a 5 s backoff. After both attempts fail, it returns `False`. The two-stage loop originally logged that and advanced `turn` counting as if the turn had completed. Under a genuine GitHub outage, the author would never see the findings AND the registry would look complete, so webhook redelivery wouldn't help.

**Pattern:** when `post_review` returns `False`, call `complete_turn(status="failed", ...)` and **break** the loop. Combined with the "resume at lowest failed turn" rule above, redelivery retries the post correctly.

## Parser normalization silently drops unknown fields

`_parse_output` rewrites Codex-schema JSON into a narrow `{verdict, summary, findings}` dict before validating against `ReviewResult`. A new top-level field (like `status` for consensus) disappears at this step unless you explicitly copy it through.

**Pattern:** when extending a structured-output contract, all three layers need the change:

1. The JSON schema file (`.github/codex/review-schema.json`).
2. The Pydantic model (`ReviewResult`) — make the field optional with a default.
3. The normalization path inside `_parse_output` — explicitly `data.get("<field>")` and copy it into the rewritten dict.

A pin test that constructs a Codex-schema payload WITH the field, parses it, and asserts the field survives is the minimum regression guard.

## opencode CLI — model names are host-specific

`opencode run --model ollama/gemma4:e4b` looks right but fails with `ProviderModelNotFoundError` on a host whose `~/.config/opencode/opencode.json` names the variant differently (e.g., `gemma4-e4b-128k`). There's no universal "use this ollama model" name — opencode resolves against the host's config.

**Implications for code:**

- Don't hardcode ollama names that assume a specific opencode config. Make them overridable (we use `Settings.opencode_model`).
- Default to a **32K-context** ollama variant, not the stock 128K model. The 128K KV cache is ~16 GB and forces CPU offload on a 24 GB GPU with any competing tenant (ComfyUI, stable-diffusion-webui, etc.), which makes one review turn take 10+ minutes. A 32K variant keeps the whole model + KV cache under 12 GB and runs 100% on GPU (~15 s/turn on a 4090).
- The 32K variant is host setup, not repo content: document the one-liner `ollama create` + opencode.json entry, do not commit a Modelfile to the repo.

## VRAM pressure diagnosis

When an ollama model reports `CPU/GPU` split instead of `100% GPU` in `ollama ps`, the cause is almost always a competing VRAM tenant, not a model-size problem. Identify via:

```bash
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

On this dev host, `ComfyUI` was holding 15.9 GB continuously for 3+ days between workflows. The review host is **not** the right place for ComfyUI — either (a) stop competing tenants before running reviews, or (b) move the reviewer to a dedicated host.

## Test flakes that vary by UUID hex

An earlier test built `sha_b = "b" + sha_a[1:]` from a uuid-derived `sha_a`. When `uuid.uuid4().hex[0]` happened to be `"b"`, `sha_b == sha_a` and the "different SHA" claim correctly returned False, failing the test. The bug is ~1/16 probability — passed in dev, failed in CI.

**Pattern:** generate uniquely-different values from independent uuids, not by string-splicing one uuid. Add a defensive `assert a != b` to catch regressions loudly instead of intermittently.

## Demo rules learned the hard way

- `uvx showboat verify` is byte-exact. Every `exec` block must produce deterministic output across runs — use OK/FAIL booleans, not raw counts or timestamps.
- For a backend PR where the happy path runs behind GitHub webhooks (can't curl it inline), the demo proves each acceptance-criterion at the file + function level via `grep` + `python -c 'import'` snippets. That's lighter-weight than end-to-end and survives CI without a live DB.
- Separate subdirectory per task's demo (`docs/demos/<branch>/<task>/`) so later PRs on the same branch don't overwrite earlier-merged demo evidence.

## Codex review cap is per-PR and silent-after-2

`MAX_REVIEWS_PER_PR = 2` in `review_engine.py` means after the 2nd codex review, every subsequent PR push gets a terse skip comment (`Codex review skipped: this PR already has the maximum of 2 bot reviews`). For large PRs with many review rounds, expect human review to drive the last few iterations. Factor this into PR sizing — ship in smaller increments if you can.
