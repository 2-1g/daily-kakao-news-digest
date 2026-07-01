# Crash-safe refresh-token rotation

The active pointer is metadata; token values remain Secret Manager versions.

1. Create a candidate secret version while retaining the prior version.
2. Verify the candidate can refresh and has exactly the required scope.
3. Atomically switch the active-version pointer with a compare-and-set on the
   previously observed generation.
4. Keep the prior version enabled for the rollback grace period.
5. Record successful use of the new version by a normal authenticated request.
6. After both successful use and grace expiry, disable, then retire, the prior
   version according to retention policy.

Recovery is phase-driven and idempotent. Before pointer switch, discard or
retry the candidate and keep using prior. After pointer switch but before a
successful-use marker, attempt the candidate and roll the pointer back if it is
invalid. Never retire prior without both required proofs. If neither version
works, suspend delivery and follow the reauthorization runbook.
