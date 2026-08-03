# Iteration Workflow

1. Select one task from the V1 implementation plan.
2. Create a focused `codex/...` branch.
3. Add failing tests before implementation.
4. Implement the smallest passing change.
5. Run unit, integration, security, and `git diff --check` gates relevant to the task.
6. Open a pull request with evidence and rollback notes.
7. Merge only after review; update `docs/STATUS.md` and the related issue.

Large household-media samples stay outside Git and are referenced only by local fixture manifests.
