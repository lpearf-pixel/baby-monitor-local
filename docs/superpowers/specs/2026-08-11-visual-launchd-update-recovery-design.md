# Visual Launchd Update Recovery Design

## Context

The first production run of `make alpha-visual-launchd-update` stopped the
registered visual worker, installed the candidate plist, and then reported
`rollback_failed`. The installed plist bytes were restored, but the old job
was left unregistered. The i9 launchd log showed the old service becoming
inactive and then being removed; a manual `bootstrap` issued later succeeded.

The update script currently assumes `launchctl bootout` makes the service
immediately absent. Its test double makes the same assumption. Both candidate
activation and rollback also discard launchctl stderr and collapse failures
into broad error reasons. The evidence supports a launchd state-transition
race, while the exact launchd-internal timing remains external to this
repository.

## Scope

Change only the visual worker launchd update lifecycle, its deployment tests,
and the existing production-performance evidence. Do not change the visual
analyzer, model set, load controller, FPS targets, latency budgets, other
launchd jobs, or the installed i9 service during software implementation.

## Lifecycle Design

After `bootout`, poll `launchctl print` until the visual job is absent. Use a
one-second interval and at most 30 observations. This is condition-based
waiting with a bounded deadline, not a fixed deployment sleep.

Candidate activation and rollback use the same registration primitive:

1. Attempt `launchctl bootstrap`.
2. If it succeeds, continue.
3. If it fails but `launchctl print` reports the job registered, treat the
   registration as successful.
4. Otherwise wait one second and retry, for at most 30 attempts.
5. After registration, run `kickstart -k` and require `launchctl print` to
   confirm the job remains registered.

The existing atomic plist replacement, exact pre-update snapshot, persistent
non-overwritten `.r3-background.bak`, and runtime plist synchronization remain
unchanged. The EXIT trap must still restore the exact snapshot after every
post-bootout failure.

## Error Contract

User-visible output remains fixed and contains no paths, launchctl messages,
runtime configuration, credentials, private addresses, or household data.
Failures are separated by lifecycle stage:

- `stop_failed`: `bootout` itself failed.
- `stop_timeout`: the old job remained registered after the bounded wait.
- `activation_bootstrap_timeout`: the candidate could not be registered.
- `activation_kickstart_failed`: the registered candidate could not be
  started.
- `activation_verify_failed`: registration was absent after kickstart.
- `rollback_bootstrap_timeout`: the exact previous plist was restored, but
  the old job could not be registered.
- `rollback_stop_failed`: a partially activated candidate could not be
  booted out before restoration.
- `rollback_stop_timeout`: the candidate remained registered after the
  bounded bootout wait.
- `rollback_install_failed`: the exact previous plist could not be restored
  atomically.
- `rollback_kickstart_failed`: the restored old job could not be started.
- `rollback_verify_failed`: the restored old job was absent after kickstart.

When candidate activation fails and rollback succeeds, preserve the original
activation reason and exit 2. When rollback itself fails, report the specific
rollback reason and exit 3.

## Test Design

The stateful fake launchctl must model an unloading state in which `print`
temporarily succeeds and `bootstrap` fails. A fake `sleep` keeps the bounded
polling deterministic and fast.

Regression coverage must prove:

- two unloading observations occur before candidate bootstrap and the update
  then succeeds;
- two transient candidate bootstrap failures are retried and the third
  attempt succeeds;
- permanent candidate failure triggers rollback, transient rollback
  bootstrap failures are retried, the exact old plist is restored, and the
  original activation error is returned;
- permanent rollback registration failure returns
  `rollback_bootstrap_timeout` rather than the previous undifferentiated
  `rollback_failed`;
- existing preflight, backup preservation, Make target, and success behavior
  remain covered.

## Performance Evidence Correction

The i9 worker later reached 5 FPS after a restart while its installed plist
still used `ProcessType=Background`, then dropped to the controller's 3 FPS
target under the same PID. A window P95 of `256.935ms` and maximum of
`325.313ms` exceeded the 180 ms budget and reset the 60-second recovery
period. Therefore `Background` correlates with earlier degradation but is not
proven to be its sole cause. `Interactive` remains a controlled experiment;
it is not accepted until the repaired updater is deployed and the same-host
three-minute observation plus full ten-minute performance gate pass.

## Acceptance

Focused deployment tests must demonstrate RED against the current updater and
GREEN after the change. Final verification includes the focused pytest set,
Python compilation for the changed test, `bash -n`, Make dry-run, plist lint
where available, ASCII/LF checks for the shell script, `git diff --check`, and
tracked/new-file scans for secrets, private addresses, runtime media, and
database artifacts. Delivery is a local commit only; no push, PR, merge, or
`main` modification is authorized.
