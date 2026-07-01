# OAuth bootstrap and reauthorization

This is an attended operator procedure. It must never run in the scheduled
runtime identity.

1. Enable the bootstrap identity and confirm it can access only the Kakao OAuth
   client secret and candidate token secret.
2. Start the CLI bootstrap flow and request only the Kakao self-message scope.
3. Open the printed authorization URL, approve consent, and paste the returned
   code into the waiting process. Do not paste codes into chat or logs.
4. The CLI exchanges the code directly into Secret Manager and verifies the
   granted scopes. Confirm no token file was written locally.
5. Run a dry-run. A live self-message smoke test requires separate explicit
   authorization.
6. Disable the bootstrap identity and clear shell history/temporary output if
   it could contain an authorization code.

If refresh returns revoked/invalid grant, stop scheduled delivery, preserve the
edition ledger, repeat this procedure, then resume only after dry-run succeeds.
Never reset an `unknown` edition to retry as part of reauthorization.
