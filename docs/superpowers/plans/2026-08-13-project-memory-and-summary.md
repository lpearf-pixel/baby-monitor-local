# Project Memory and Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every future Work session a durable project rulebook and a concise, evidence-backed current handoff snapshot.

**Architecture:** Expand the existing root `AGENTS.md` into the stable instruction layer and create root `SUMMARY.md` as the changing state layer. Detailed chronology remains in `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`, specifications and plans; the two root files link to those sources instead of duplicating them.

**Tech Stack:** Markdown, Git, POSIX/macOS-oriented shell verification.

## Global Constraints

- Modify only `AGENTS.md`, `SUMMARY.md`, this plan and its approved design record.
- Do not modify application code, tests, thresholds, models, runtime configuration, remotes, pull requests or protected branches.
- Never record credentials, private addresses, household media, personal identifiers or local deployment paths.
- Preserve the untracked `uv.lock` without staging or modifying it.
- Distinguish synthetic/software evidence from i9, Xiaomi camera, M2, two-phone, accuracy and performance acceptance.
- Use repository state and fresh verification as authoritative when prose conflicts.

---

### Task 1: Expand the durable project rulebook

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: current repository rules, `README.md`, `SECURITY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`, and verified Make targets.
- Produces: stable instructions automatically loaded by future coding agents.

- [ ] **Step 1: Capture the current rulebook and repository facts**

Run:

```bash
sed -n '1,260p' AGENTS.md
git status -sb
git log -1 --oneline
rg -n '^alpha-(guardian-start|guardian-test|visual-status|visual-performance):' Makefile
```

Expected: current branch and HEAD are visible, `uv.lock` is the only unrelated untracked file, and all referenced Make targets exist.

- [ ] **Step 2: Write the stable instruction layer**

Expand `AGENTS.md` with these exact responsibility groups:

```text
Project Mission and Boundaries
System Architecture and Ownership
Safety and Privacy Invariants
Repository and Git Governance
Configuration and Runtime Rules
macOS and Shell Compatibility
Verification Strategy
Work Session Takeover
Required Delivery Report
Authoritative Documentation
```

Keep transient commit hashes, PIDs, measured performance samples and chronological milestone details out of `AGENTS.md`.

- [ ] **Step 3: Verify the rulebook**

Run:

```bash
git diff --check -- AGENTS.md
rg -n 'Project Mission|Safety and Privacy|Verification Strategy|Work Session Takeover|Required Delivery Report' AGENTS.md
```

Expected: zero diff errors and every durable responsibility group is present.

### Task 2: Create the current project handoff snapshot

**Files:**
- Create: `SUMMARY.md`

**Interfaces:**
- Consumes: the verified repository state and detailed project records.
- Produces: a dated current-state handoff for new Work sessions.

- [ ] **Step 1: Write the current snapshot**

Create `SUMMARY.md` with these exact sections:

```text
Snapshot
Product Scope
Deployment Architecture
Completed Capabilities
Verification Evidence
Current Git State
Pending Real-Device Acceptance
Known Limitations
Next Priorities
Operating Commands
Detailed Records
Takeover Checklist
```

Record local `fb3eee3` as the preserved development history and remote `27274d8` as the content-equivalent squash snapshot. State that both point to tree `adf3672`, and that the remote feature branch has not been merged into `stable/xiaomi-alpha` or `main`.

- [ ] **Step 2: Check repository references**

Run:

```bash
test -f README.md
test -f SECURITY.md
test -f docs/STATUS.md
test -f docs/CHECKPOINT.md
test -f docs/NEXT.md
rg -n '^alpha-guardian-(start|test):' Makefile
```

Expected: every referenced file and operating command exists.

- [ ] **Step 3: Verify safety, scope and formatting**

Run:

```bash
git diff --check -- AGENTS.md SUMMARY.md
! rg -n 'github_pat_|ghp_|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|192\.168\.|10\.[0-9]+\.|172\.(1[6-9]|2[0-9]|3[01])\.' AGENTS.md SUMMARY.md
git status --short
git diff --stat
```

Expected: no formatting or sensitive-literal matches; only the approved documentation files plus the preserved untracked `uv.lock` appear.

- [ ] **Step 4: Commit the handoff documents**

Run:

```bash
git add AGENTS.md SUMMARY.md docs/superpowers/plans/2026-08-13-project-memory-and-summary.md
git commit -m "docs: add durable project handoff"
```

Expected: one local documentation commit; no push, PR, merge or protected-branch modification.

