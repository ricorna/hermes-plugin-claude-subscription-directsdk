# Pinned 0.3.0 admission correction

This is a narrow backport to `pinned/directsdk-0.3.0`, not an upgrade to the moved upstream plugin.

## Defects reproduced

- An empty or whitespace-only `input_json_delta` for a no-argument tool caused `Capture._block_stop` to parse empty JSON and abort a valid HTTP 200 stream. Native recovery then encountered the deliberately consumed admission. Accept an empty argument stream as `{}`; malformed nonempty JSON still fails.
- Any first-request HTTP failure was overwritten in the reported error by native's last admission-denial response. Report the first status, capture state, relay exception class, and denied retry count instead. Expose the first HTTP error as `status_code` for host retry/fallback classification. Never use the local denial's 400 as the upstream status.

The one-upstream-request rule, authorization forwarding, cancellation and denied-retry behavior are unchanged. Diagnostics deliberately exclude raw upstream bodies, native output and admission URLs.

Equivalent upstream changes exist in commits `10ba8f0255c043be09a19b37acb1436f539b8b18`, `efb9cd7030f9dd72a447aa8070e90089f4b587d4`, and the HTTP-status portion of `144bd1d1ddf3fe747c53cb5c045aaa7927a03f20`. This backport avoids unrelated behavior changes.

## Incident limits

The historical `HERMES_MODEL_ADMISSION_CONSUMED` log alone cannot establish whether its first attempt was empty-tool capture, overload, throttling, another upstream rejection, or a transport error. It is not evidence that an admission credential was reused across host requests: the transport creates a fresh `Admission` per request. The regression reproduces the misleading symptom and an actual parser defect; do not claim forensic attribution of the historical first failure.

## Regression coverage

`tests/test_first_failure_authority.py` drives real subprocesses through the real loopback admission relay. It covers empty, whitespace, valid and malformed tool arguments, and HTTP 400/401/413/429/529. Native deliberately retries: each case asserts exactly one upstream request. Successful capture remains authoritative even when native's final result is a denial. HTTP errors preserve their first status; parser errors have no fabricated HTTP error status.

Before the production change: 8 regression failures and 1 valid-JSON pass. After: 9 regression passes; with existing admission/cancellation tests: 13 passes.
