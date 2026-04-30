"""Pin tests: T-363.

`git remote set-url origin "https://x-access-token:…"` mutates `.git/config`
persistently. After any close-wave / reconcile / github-bot push runs, every
subsequent `git push` from that clone inherits the bot identity — including
`make promote`, which targets `prod`. `prod`'s ruleset only allows operator
pushes, so promote fails until the operator manually resets origin URL.

The right shape is `git push "<inline-bot-url>" HEAD:<branch>` — bot identity
for one push, no config mutation. Set upstream after via
`git branch --set-upstream-to=origin/<branch>` so future operator-side
`git pull` works without re-auth.

These pins assert:
1. None of the three target SKILLs contain the antipattern inside an executable
   ```bash code fence. (Prose discussion of the antipattern is allowed — see
   the CLAUDE.md learning "Absence-pins on antipattern substrings collide
   with documentation that names the antipattern".)
2. Each target SKILL contains the inline-URL push pattern inside a ```bash
   code fence.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TARGET_SKILLS = [
    REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md",
    REPO_ROOT / "plugins/cloglog/skills/reconcile/SKILL.md",
    REPO_ROOT / "plugins/cloglog/skills/github-bot/SKILL.md",
]

_BASH_FENCE_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _bash_blocks(body: str) -> list[str]:
    return _BASH_FENCE_RE.findall(body)


def test_target_skills_exist() -> None:
    for path in TARGET_SKILLS:
        assert path.exists(), f"target SKILL missing: {path}"


def test_no_remote_set_url_with_bot_token_in_bash_blocks() -> None:
    """No bash fence in the target SKILLs may mutate origin URL with the bot token.

    Matches the executable form `git remote set-url origin "https://x-access-token:`
    only — prose mentioning the antipattern in surrounding paragraphs is fine.
    """
    forbidden = re.compile(r'git\s+remote\s+set-url\s+origin\s+"https://x-access-token:')
    violations: list[str] = []
    for path in TARGET_SKILLS:
        body = path.read_text(encoding="utf-8")
        for block in _bash_blocks(body):
            if forbidden.search(block):
                violations.append(
                    f"  {path.relative_to(REPO_ROOT)}: bash block contains "
                    f'`git remote set-url origin "https://x-access-token:…"` — '
                    f'replace with `git push "<inline-url>" HEAD:<branch>`'
                )
    assert not violations, (
        "Found persistent bot-URL mutation in SKILL bash blocks. This breaks "
        "`make promote` (`prod`'s ruleset rejects bot pushes), strands expired "
        "tokens in `.git/config`, and leaks the credential through "
        "`git remote -v`. Use the inline-URL push form instead:\n" + "\n".join(violations)
    )


def test_inline_url_push_pattern_present_in_each_target_skill() -> None:
    """Each target SKILL must document the inline-URL push form inside a bash fence."""
    required = re.compile(r'git\s+push\s+"https://x-access-token:\$\{BOT_TOKEN\}@github\.com/')
    missing: list[str] = []
    for path in TARGET_SKILLS:
        body = path.read_text(encoding="utf-8")
        if not any(required.search(block) for block in _bash_blocks(body)):
            missing.append(f"  {path.relative_to(REPO_ROOT)}")
    assert not missing, (
        "These SKILLs are missing the inline-URL bot push pattern in any bash "
        "fence. Add a block of the shape:\n"
        '  git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" "HEAD:${BRANCH}"\n'
        "to each:\n" + "\n".join(missing)
    )
