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
# Production adapter mapping

`SecretManagerTokenStore` creates and verifies a new secret version, then
switches the `active` Secret Manager version alias with the secret resource's
etag carried through the update. Keep the previous version enabled until the
new active version has been read and used successfully. Never disable the
version currently referenced by `active`.

## Rotation state and validation

A newly refreshed secret moves through `candidate_created`, `candidate_verified`, and
`active_pending_validation`. Alias CAS races are recoverable: the losing candidate is
disabled and the winner is re-read. An `Aborted`/`FailedPrecondition` etag conflict is
treated as a CAS miss, never as permission to overwrite the winner. The new version is
marked successfully used only after Kakao accepts an authenticated send; creating,
verifying, or activating a version alone is not proof of usability. Keep the previous
version enabled until this validation is visible, so an operator can roll the alias back.

The `oauth_refresh_expiry_warning` structured event is emitted within seven days of
refresh-token expiry. Alert on it and repeat attended authorization before expiry.

Secret Manager aliases provide the durable audit markers: `rotation-candidate`,
`rotation-previous`, phase-specific `rotation-*` markers, and `rotation-proven`.
The first Kakao acceptance writes `rotation-proven`. If the first authenticated
request is definitely rejected before that proof, the runtime atomically restores
`active` to `rotation-previous` using the secret etag and records
`rotation-rolled-back`. The rejected edition remains terminal and is never resent.
An etag conflict means another worker won; the runtime does not overwrite it.
