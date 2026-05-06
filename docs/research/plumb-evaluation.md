# Plumb evaluation — F-59 / T-472

**Repo:** https://github.com/dbreunig/plumb (commit `a81420a`, last activity early
March 2026)
**Author framing:** "Spec Driven Development Triangle" — proof-of-concept,
explicitly alpha. Released alongside a talk + blog post.
**Evaluator:** wt-t472-plumb-research, 2026-05-06
**Scope:** explore-only. No code, no integration. Sibling `wt-t473` covers
memento; cross-link only.

---

## 1. What plumb does, in cloglog vocabulary

Plumb is a Python CLI + git pre-commit hook that tries to keep three artifacts
mutually consistent across an AI-assisted coding session: a **spec markdown
file**, a **pytest suite**, and the **code**. On `git commit`, it inspects the
staged diff *and* the local Claude Code session transcript, asks an LLM
(Anthropic Claude / DSPy programs) to extract the prescriptive "decisions"
that were implicitly made (caching strategy chosen, API contract changed,
behaviour refined), then **blocks the commit** until the operator approves,
edits, or rejects each decision. Approved decisions are written back into the
spec markdown via search-and-replace edits; rejected decisions trigger an
LLM-driven rewrite of the staged code to undo them. Coverage is reported
along three axes — pytest line coverage, spec→test coverage (which
requirements have a linked test), and spec→code coverage (which requirements
have an implementation, inferred by an LLM).

In cloglog vocabulary: plumb is a **commit-time gate** that synthesises new
"requirements" (think: invariants in `docs/invariants.md`) from session
context, and asks the operator to ratify them before they land. The
"requirements" are LLM-extracted from chat + diff, not hand-authored. The
"pin tests" of cloglog have a loose analogue in plumb's spec→test linker
(`# plumb:req-XXXXXXXX` comments / `def test_req_XXXXXXXX_...` function
names), but plumb does not run the tests as the gate — it gates on LLM
reconciliation of decisions, not on test outcomes. The board, the agent
lifecycle, and worktrees have no analogue in plumb; it is purely a single-repo
single-developer tool.

## 2. Mechanism — how spec, tests, and code are linked

Three different mechanisms, layered:

- **Spec → requirements.** `plumb parse-spec` calls a DSPy `RequirementParser`
  program over the markdown. Output is `.plumb/requirements.json`: a list of
  `{id: req-<sha256(text)[:8]>, source_file, source_section, text, …}`. IDs
  are content-hashed so the same sentence in different specs collides — and
  edits to the sentence change the ID, which means the link to existing tests
  silently breaks.
- **Requirement → test.** Annotation-based, in two flavours: a comment
  marker `# plumb:req-XXXXXXXX` *inside the test function body*, or a
  function-name convention `def test_req_XXXXXXXX_...`. Both parsed by a
  regex in `coverage_reporter.py:16`; both are write-once on test creation
  and have no compiler/runtime check that the referenced ID still exists.
- **Requirement → code.** LLM-inferred, not annotation-based. A DSPy
  `code_coverage_mapper` program reads each source file and the
  requirements list, and emits `.plumb/code_coverage_map.json` entries of the
  form `{"implemented": true, "evidence": "<freeform LLM sentence>",
  "source_files": []}`. Note `source_files` is **empty** for every entry in
  the project's own self-snapshot — the LLM names a file in the evidence
  string but doesn't fill the structured pointer field. This is the weakest
  link in the chain.

There is no AST analysis, no symbol-graph extraction, no runtime trace.
Everything that isn't a regex annotation is an LLM guess cached against a
content hash and re-run when the source hash changes.

## 3. Plugin portability — can a downstream cloglog project adopt plumb?

**The deciding question for F-59.** cloglog's plugin (`plugins/cloglog/`) is
shipped to multiple downstream repos (today: cloglog itself + antisocial).
Anything that ships in that plugin must work in any language and any
build-tool layout, because a downstream Go or TypeScript project gets the
same plugin.

Plumb is **fundamentally not plugin-portable** as it stands:

- **Python-only by construction.** `pyproject.toml` declares `python = ">=3.10"`,
  the test linker assumes pytest discovery (`def test_...`), the coverage
  axis literally shells `pytest --cov`. A TypeScript or Go downstream
  project would need a complete reimplementation of the test linker and
  coverage reporter. Nothing in the design is language-agnostic; the
  spec→test linker is a regex over Python identifiers.
- **Per-project ritual at install time.** `plumb init` is *interactive* — it
  asks for spec path and test directory, writes `.plumb/config.json`,
  installs a pre-commit hook into `.git/hooks/pre-commit`, drops a
  `.claude/skills/plumb/SKILL.md`, and patches `CLAUDE.md`. Every downstream
  repo adopting plumb has to run that ritual locally, with an
  `ANTHROPIC_API_KEY` already exported. This is incompatible with cloglog's
  plugin model where install is "the plugin appears in the agent's
  `.claude/plugins/` and works."
- **State in `.plumb/` must be committed.** README is explicit: commit the
  `.plumb/` directory. That includes `requirements.json`, `coverage.json`,
  `code_coverage_map.json`, `decisions/*.jsonl`. For cloglog this is
  manageable; for downstream repos with many contributors it becomes a
  high-conflict directory (every branch generates new decisions; merge
  conflicts on append-only JSONL are routine but every reconciliation costs
  operator attention).
- **API key + commit-time latency.** Every commit invokes Claude over the
  diff *and* the conversation log. Even with caching, a non-trivial commit
  is several seconds of network round-trip before the hook returns. cloglog's
  pre-commit gate (`make quality`) is already slow enough that we work to
  keep it under a minute; layering an LLM call on top is a meaningful UX
  regression for the marginal case.

**Verdict for portability:** to ship inside the cloglog plugin, plumb would
have to be (a) generalised across languages, (b) made non-interactive at
install time, (c) made offline-capable for the common path, and (d) have its
state moved out of the repo or made conflict-free. That is essentially a
rewrite, not an adoption.

## 4. Cost to adopt — concrete

If we hypothetically adopted plumb just inside cloglog (not for downstream
plugin consumers):

- New runtime dep: `plumb-dev` (~1.5k LOC Python, pulls `dspy`, `anthropic`,
  `gitpython`, `click`, `rich`, `jsonlines`).
- New env var: `ANTHROPIC_API_KEY` mandatory at commit time. Currently agents
  authenticate to Claude via Claude Code's own credentials; introducing a raw
  Anthropic key in the dev path is a credential-sprawl regression.
- New committed directory: `.plumb/` (~10s of MB after a few months of
  decision logs).
- New pre-commit hook layered on top of `scripts/install-dev-hooks.sh`'s
  existing `ALLOW_MAIN_COMMIT` guard. The interaction is non-trivial —
  plumb wants to abort the commit and re-run it after sync, our hook wants
  to abort commits to `main`. Order-of-fire matters.
- New spec file: today cloglog's "spec" is distributed across `docs/design/`,
  `docs/invariants.md`, per-context CLAUDE.md sections, and the README.
  Plumb wants a single (or list of) markdown files declared in
  `.plumb/config.json`. We would need to either nominate one of the existing
  docs as the canonical spec, or write a new one — and accept that plumb
  will rewrite it via search-and-replace on every approved decision.
- New manual ritual per commit: review extracted decisions,
  approve/edit/reject, run `plumb sync`, re-stage, re-commit. For agent
  commits this becomes "the agent must drive the plumb skill," which adds
  another required skill to every worktree-agent prompt and another set of
  failure modes to debug.

## 5. Failure modes

Where plumb lies:

- **Green when drift exists** — the LLM `code_coverage_mapper` returns
  `implemented: true` with an evidence sentence and no `source_files`
  pointer. Renaming the implementing function or moving it to a different
  module produces no signal until the source hash changes *and* the LLM
  happens to re-evaluate with different output. The "evidence" field is not
  verified against the code.
- **Green when the requirement was deleted from the spec** — requirement IDs
  are content hashes. Edit a sentence in `plumb_spec.md`, the ID changes, and
  every test annotated with the old ID is now linking to a non-existent
  requirement. `plumb coverage` will report the requirement as having no
  test, but won't report the test as orphaned.
- **Green when the AI lies about its own session** — the decision-extraction
  step reads the Claude Code session transcript. A model that fabricated a
  rationale earlier in the conversation will get that rationale promoted to
  a "decision" the operator is asked to ratify, with the model's own framing.
- **Red when the diff is mechanically refactor-only** — plumb does not
  distinguish "behaviour change" from "rename." A rename touches every line
  in the file, the diff_analyzer extracts decisions about the new naming,
  the operator has to clear them every commit. The `.plumbignore` mechanism
  helps, but is opt-in per-pattern.
- **Silent partial failure on multi-session work** — the conversation reader
  merges multiple session files chronologically. If a session crashed or was
  garbage-collected, the rationale for a staged change is invisible and the
  decision extractor falls back to diff-only inference, which is materially
  weaker.

## 6. Interaction with cloglog's existing demo / proof-of-work surfaces

Cloglog already runs a proof-of-work gate (`Skill({skill: "cloglog:demo"})`
plus `scripts/check-demo.sh` inside `make quality`). Showboat verifies static
demo documents against frontmatter hashes; Rodney captures headless browser
screenshots for frontend PRs. The demo gate operates at the **PR boundary**
and asserts "user-observable behaviour was demonstrated."

Plumb operates at the **commit boundary** and asserts "the spec text agrees
with the diff text." Different domain, different artifact, different gate
point. They do not directly contradict.

But they **do interact unhelpfully**:

- A PR-prep commit that updates a screenshot or a demo markdown would, under
  plumb, trigger an LLM diff analysis and possibly extract a "decision" out
  of the demo prose — because plumb does not know that
  `docs/demos/wt-*/demo.md` is artifact, not source. We'd have to add every
  demo path to `.plumbignore`, and the same for every artifact path the
  showboat / rodney pipeline writes.
- A spec change driven by plumb (e.g. "approved decision: in-memory cache")
  that lands in the canonical spec markdown does **not** automatically update
  the demo. The PR can have a synced spec, a green plumb gate, and a stale
  demo — and the demo gate doesn't check the spec.
- The **inverse failure** is the load-bearing one for cloglog: a PR can pass
  plumb (spec/test/code agree) and fail demo (no observable behaviour
  shown), or pass demo (screenshot recorded) and fail plumb (LLM extracted a
  decision the operator hasn't ratified). The two gates are **orthogonal**;
  layering them doubles the gate-failure surface without composing.

So: plumb does not conflict with the demo surface, but it does not
complement it either. They live in disjoint domains and would have to be
debugged separately.

## 7. Verdict

**No-fit, with one narrow idea worth keeping.**

The ratio of cost (Python-only, interactive install, committed state,
mandatory API key, per-commit LLM latency, new spec ritual, new agent skill,
new gate-failure surface) to benefit (an LLM-mediated check that a human
might forget to update the spec) is unfavourable for cloglog and structurally
incompatible with cloglog's plugin shipping model. The plugin must work in
downstream Go/TS repos; plumb cannot.

The narrow idea worth keeping: **annotation-based test ↔ requirement
linking**. The `# plumb:req-XXXXXXXX` comment convention is a small, useful
piece of design — it costs nothing to add to a test file, it survives
refactors, and it can be checked by a 50-line script with no LLM. cloglog's
`docs/invariants.md` already names a "pin test" per invariant in prose. A
formalised annotation that the pin-test mechanism could *grep* for would
strengthen `make invariants` without any of plumb's heavyweight machinery.

**Self-defense check on follow-ups.** Per the operator's 2026-05-05 rule
(don't fill the queue back up), what *ships broken* if we drop each
candidate follow-up?

- "Adopt plumb" — nothing ships broken. Drop.
- "Reimplement plumb's portable subset for the cloglog plugin" — nothing
  ships broken; cloglog already has demo + invariants + ddd-reviewer covering
  the failure modes plumb addresses. Drop.
- "Add `# inv:NN` annotation to invariant pin tests, gated by `make
  invariants`" — *something* potentially ships broken: today the link
  between `docs/invariants.md` entries and their pin tests is by
  prose-naming only, so a renamed pin test silently delinks. The risk is
  small (entries get re-read on touch), and the fix is small (a 30-line
  grep gate). **Borderline.** Note in this doc and **do not file** —
  filing a "nice-to-have annotation convention" is exactly the queue-padding
  the operator has been deleting. If a real incident shows a delinked pin
  test, file the gap then.

**Net follow-ups filed: zero.** Cross-link to `wt-t473` memento research for
sibling context.

## Cross-links

- Sibling research: `docs/research/` (memento) — **not yet written by
  wt-t473 at the time of this evaluation**; will land separately.
- Existing surface this would interact with: `docs/invariants.md`,
  `scripts/check-demo.sh`, `plugins/cloglog/skills/demo/`,
  `plugins/cloglog/agents/ddd-reviewer.md`.
