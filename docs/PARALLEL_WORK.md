# Parallel Post-P0 Development

## Baseline

- P0 baseline: `2d19a52f2de92175d7a8d2861665723218ffd2ff`
- Tag: `p0-baseline`

## Workstreams

| Stream | Worktree | Branch | Scope |
| --- | --- | --- | --- |
| QA | `.worktrees/qa` | `feat/qa` | Security/reliability hardening |
| Sentry | `.worktrees/sentry` | `feat/sentry` | Observability/sponsor hardening |
| RunPod | `.worktrees/runpod` | `feat/runpod` | Optional heterogeneous replacement model |
| Explain | `.worktrees/explain` | `feat/explain` | Optional post-hoc incident explanation |

## Main Repository Ownership

The main repository owns:

- WorkSwarm reliability
- Shared configuration
- Generated API schema/types
- Canonical docs
- Merges
- UI/demo refinement

## Merge Policy

No parallel agent merges its own branch.
