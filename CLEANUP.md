# AI Slop Cleanup Plan

## Scope and behavior lock

- Scope: every source, test, configuration, infrastructure, and documentation file in this session-owned repository.
- Baseline: `PYTHONPATH=src python3 -m unittest discover -s tests -q` passes 69 tests.
- Preserve: deterministic evidence fallback, compliance fail-closed checks, model cost ceilings, live-send opt-in, `UNKNOWN` no-resend handling, Kakao size/quota guards, OAuth rotation safety, and transactional state transitions.

## Fallback inventory

| Finding | Classification | Action |
| --- | --- | --- |
| Invalid or absent synthesis becomes a deterministic extractive summary | Grounded fail-safe | Preserve; evidence-bound behavior is regression-tested. |
| Model I/O or malformed model output becomes a deterministic extractive summary | Grounded fail-safe at an external boundary, but currently catches every `Exception` | Narrow expected failure types so programming defects remain visible; retain tests for malformed output and network failure. |
| OAuth refresh errors are wrapped as a safe authentication failure, while reauthorization is preserved | Grounded fail-safe | Preserve; this is the security boundary and retains exception causality. |
| Kakao non-definite transport failures become `AmbiguousDeliveryError` | Grounded fail-safe | Preserve; this enforces `UNKNOWN` and forbids unsafe resend. |
| Firestore adapter uses a non-transactional path only for injected SDK-free fakes | Grounded compatibility path | Preserve; the code documents that production clients use transactions and tests exercise the fake boundary. |
| Naver missing hostname is labeled `unknown` | Grounded descriptive default | Preserve; it does not authorize I/O or bypass validation. |

No masking fallback requires architectural escalation.

## Ordered cleanup passes

1. Remove dead imports and stale test setup.
2. Remove small readability duplication/noise without introducing helpers or layers.
3. Narrow model fallback error handling and clarify local names while preserving all safety boundaries.
4. Add the narrow regression proving unexpected programming errors are not silently masked.
5. Run the 70-test suite, byte-compile all source/tests, inspect the diff, and commit with Lore trailers.

No new dependencies or architecture changes are permitted in this pass.
