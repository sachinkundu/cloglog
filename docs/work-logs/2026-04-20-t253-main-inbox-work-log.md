# Work Log: wt-main-inbox (T-253)

**Date:** 2026-04-20
**PR:** https://github.com/sachinkundu/cloglog/pull/164 (merged)
**Task:** T-253

## Commits
```
40d9f05 fix(gateway): T-253 gate main-agent fallback on project match
e903a91 fix(demo): T-253 normalize slashes in demo branch path
d309950 fix(gateway): T-253 main-agent inbox fallback for unrouted webhook events
```

## Files Changed
```
 .env.example                            |   7 +
 docs/demos/wt-main-inbox/demo-script.sh |  72 ++++++++++
 docs/demos/wt-main-inbox/demo.md        |  83 +++++++++++
 src/gateway/webhook_consumers.py        |  84 ++++++++---
 src/shared/config.py                    |   8 ++
 tests/gateway/test_webhook_consumers.py | 239 +++++++++++++++++++++++++++++++-
 6 files changed, 466 insertions(+), 27 deletions(-)
```
