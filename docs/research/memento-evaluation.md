---
title: memento (mandel-macaque/memento) — evaluation for cloglog
task: T-473
feature: F-59
status: research
date: 2026-05-06
---

# memento — fit evaluation

Source: <https://github.com/mandel-macaque/memento>. Sibling research on `plumb` (T-472) covers spec↔test↔code separately under PR #336 (different branch — not in this checkout); this memo is **agent-recording only** — no comparison.

## 1. What memento does (in cloglog vocabulary)

`git-memento` is a Git extension (F#, NativeAOT-compiled binary, optional `dotnet` build) that attaches an AI coding session's **conversation transcript** to the commit it produced, as a `git notes` ref. In cloglog terms: every time a worktree agent lands a commit, memento would fetch that agent's Claude Code (or Codex) transcript via the provider CLI and stash the markdown blob in `refs/notes/memento-full-audit` against the commit SHA. A summary lands in the default `refs/notes/commits` ref; the full transcript stays in the audit ref. PR-time GitHub Actions can post notes as PR comments (`comment` mode), gate merges on note coverage (`gate` mode), and carry per-commit notes onto the merge commit (`merge-carry`).

It is not a runtime tracer. It is not a shell hook, LSP listener, or OS audit shim. It is a thin orchestrator that asks the provider's own CLI for an already-recorded transcript and binds it to a commit.

## 2. Mechanism

- **Capture**: provider-specific. For Claude Code, the user supplies the session ID; memento reads the transcript that Claude Code's CLI already persists locally. For Codex, `codex sessions list --json` enumerates sessions and the same fetch-then-attach flow runs. If the session ID is missing, memento prints the available sessions and bails — there is no daemon, no live tap.
- **Bind**: `git notes add` to the new commit. Multi-session commits are supported via explicit delimiters in the note body.
- **Replay vs. snapshot**: snapshot. The note is whatever the provider CLI returns at `git memento commit` time; there is no re-derivation later.
- **Distribution**: notes refs are not pushed by default — memento ships a `notes-sync` command and a `merge-carry` GitHub Action to move them across the remote.

So the recording layer is the provider (Claude Code / Codex). Memento's contribution is the commit-binding, the multi-session note schema, and the CI plumbing (`comment` / `gate` / `merge-carry`).

## 3. Plugin portability

cloglog's plugin ships to `cloglog` itself + `antisocial` today; the constraint is that any new tool has to install via the plugin, not be cloglog-specific.

Memento is a per-host binary plus a Git config + a GitHub Actions workflow file. To install it from the plugin we'd need:

- A bootstrap step in `cloglog:init` (or a new `cloglog:init-memento`) that downloads the NativeAOT binary, drops `git memento` on PATH, and writes the provider config.
- A worktree-agent step that calls `git memento commit <session-id>` instead of (or in addition to) `git commit`. Claude Code's session ID has to be obtainable from the agent's own runtime — feasible, but the plumbing is new.
- A `merge-carry` action installed under `.github/workflows/` of every downstream repo. This is per-project, not plugin-resident — the plugin would need to template it on `init` and assert it from `init-smoke.yml`.

It can bolt onto the existing per-worktree shutdown-artifacts pipeline in the sense that nothing in cloglog conflicts with `git notes`. It does not replace any existing pipeline step. So the answer is: **plugin-installable in principle, but every downstream repo pays a per-project setup cost** (workflow file, binary install, provider config) — that is a real friction point given F-59's "across all cloglog-managed projects" goal.

## 4. Overlap with existing cloglog signals

| cloglog signal | What memento adds | Overlap |
| --- | --- | --- |
| `shutdown-artifacts/work-log-T-*.md` (agent-authored) | Raw, unedited Claude transcript instead of an agent's self-summary | High — same intent (per-task narrative), different fidelity |
| `shutdown-artifacts/work-log.md` (aggregate) | Per-commit notes, not per-task | Partial — memento is finer-grained than the aggregate |
| `docs/work-logs/<date>-<wave>.md` (wave fold) | Nothing wave-level | None |
| Board events (`mark_pr_merged`, `agent_unregistered`) | None | None |
| PR diff + commits | Full conversation that produced the diff | Complementary — diff says *what*, transcript says *how/why* |
| Codex review transcripts | Reviewer transcripts already on PR; memento adds **author** transcripts | Complementary — different actor |

Net: memento mostly competes with the agent-authored work log. It wins on fidelity (no self-editing), loses on signal-to-noise (raw transcripts are long, full of tool calls and dead-ends). It does **not** subsume the work log's load-bearing **Residual TODOs** section — that's interpretation, not transcript.

## 5. Cost to adopt

- **Binary**: NativeAOT F# executable (single file), or `dotnet 10` SDK build. Adds a runtime dependency to every host that runs cloglog agents.
- **Per-worktree config**: `git memento` requires `user.name`/`user.email` (already set) plus provider env vars for which Claude Code / Codex CLI to invoke.
- **CI**: one workflow file per downstream repo (`merge-carry` + optionally `comment`/`gate`). cloglog's `init-smoke.yml` would need to assert it.
- **Note storage**: notes inflate repo size on `git fetch refs/notes/*`. For a chatty Claude session a single note can be hundreds of KB; over a year of agent commits this is non-trivial but not crippling. The full-audit ref can be excluded from the default fetch refspec.
- **Session-ID plumbing**: Claude Code's session ID must reach the worktree agent's commit step. Today the agent doesn't know its own session ID — that's a new wire.

## 6. Failure modes

The 2026-05-05 incident on `wt-t475` (agent crashed mid-task; main agent salvaged the working tree and synthesized the per-task work log from diff + PR) is the load-bearing test case. Would memento have closed the gap?

**Partially.** Memento attaches to a commit. If `wt-t475` crashed *before* committing, there's no anchor and no note — the recording is lost the same way the work log was. If it crashed *after* committing but before `git memento commit` ran, the transcript file Claude Code persisted locally is still on disk and could be retroactively attached (`git notes add` on the existing commit), so a salvage path exists — but it requires the operator to know the session ID, which is exactly what's lost when the agent process dies.

Other failure modes:

- **Silent dropouts**: memento has no liveness check. If the provider CLI returns an empty transcript (session evicted, cache cleared), `git memento commit` succeeds with a near-empty note. The note's existence is verified by `audit`; its substance is not.
- **Crashed subprocess**: same as above — no transcript, no warning unless `audit` is gated.
- **Provider mismatch**: configured-for-Codex but the agent ran on Claude → silent capture of the wrong transcript or none at all.

So memento helps on the *post-merge audit* angle ("what conversation produced this commit?") but does not help on the *crash-recovery* angle ("the agent died; what was it doing?"). The wt-t475 gap was specifically the latter.

## 7. Interaction with proof-of-work surfaces (Showboat / Rodney)

Showboat verifies static demo docs against a frontmatter hash; Rodney runs headless screenshots for frontend demos. These attest to **the artifact**: the demo doc passes a hash check, the screenshot shows the feature working.

Memento attests to **the process**: here is the conversation that produced the diff. They are orthogonal layers — one cannot substitute for the other.

Concretely: a memento note in a frontend PR description cannot replace a Rodney screenshot. A transcript saying "I implemented the dark-mode toggle and it works" is unverifiable; a screenshot of the toggle in dark mode is. The reviewer needs the *output*, not the conversation about producing the output. Memento adds an extra audit trail alongside the demo, not a substitute for it.

The only place a memento note arguably substitutes for anything is the agent-authored work log — and even there, the work log's curated **Residual TODOs** are not in the raw transcript.

## 8. Verdict

**No-fit, with one preserved option for later.**

Reasons:

1. **The motivating gap (wt-t475 mid-task crash) is not closed.** Memento binds to commits; pre-commit crashes leave nothing to bind to. The gap that triggered F-59 is exactly where memento is weakest.
2. **Per-project setup cost contradicts the plugin-portable goal.** Every downstream repo needs a workflow file, a binary install, and provider config. F-59's framing — "across all cloglog-managed projects" — wants the opposite.
3. **High overlap with the agent-authored work log on the substance, low overlap on the load-bearing fields** (Residual TODOs, codex-review findings). The work log already wins on signal-to-noise.
4. **Provenance gap is small.** PR diff + codex review transcript + agent-authored work log already cover "what was done, what the reviewer thought, what the agent decided." The remaining delta — verbatim author conversation — is large in volume and small in marginal evidentiary value.

Preserved option for later: if F-59 evolves to need *legally durable* author-transcript provenance (compliance, not engineering audit), memento's `git notes` binding is the cleanest off-the-shelf primitive and we'd revisit. Today's bar is lower.

## Self-defense — proposed follow-ups

Per the operator rule (2026-05-05): for each follow-up I'd file, defend "what ships broken if dropped?" If the answer is "nothing visible" or "cleaner," drop it.

Candidate follow-ups considered and **dropped**:

- *"Prototype memento install in the plugin's init flow."* Drop. Nothing ships broken if absent — work log + diff already cover the audit need. Verdict above is no-fit; prototyping further is exploratory not load-bearing.
- *"Compare memento against a homegrown 'attach Claude transcript to commit' shim."* Drop. Same reason — without an established need for transcript-bound provenance, building it ourselves is also "cleaner not load-bearing."
- *"Document the wt-t475 crash gap as an F-59 invariant."* Drop. The gap is already captured implicitly in the task description and was the motivating example for this memo; a separate invariant doc adds nothing the next reader can act on.

**No follow-ups filed.** If the verdict is wrong, the next signal will be a *second* mid-task agent crash where the synthesized work log proves insufficient — at that point the gap is concrete and a targeted fix (likely **not** memento) earns a task.

## Cross-link

Sibling task T-472 covers `plumb` (spec↔test↔code), the other half of F-59. The plumb memo lands separately via PR #336 — it is not in this checkout. After both PRs merge, the two memos sit alongside each other in `docs/research/`.
