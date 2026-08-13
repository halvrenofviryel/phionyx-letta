# Security policy

`phionyx-letta` is a Letta memory-mutation evidence-envelope builder for the Phionyx runtime-evidence layer. It is **alpha / experimental** software. Its value depends on its
evidence and governance checks being correct: a record or check is only worth anything if
something that *should* fail actually fails, and something unmeasured is reported as
unmeasured rather than as success. If you find a way to break that, please report it
**privately**.

## Report privately

Use GitHub's private vulnerability reporting — the **Report a vulnerability** button under this
repository's **Security** tab — not a public issue. If that is unavailable, email
**founder@phionyx.ai** with `[SECURITY] phionyx-letta` in the subject. Please do not open a public
issue or PR for a suspected vulnerability until it has been triaged.

Include, where you can: the version (`pip show phionyx-letta`), a minimal reproduction, and what
you expected versus what happened.

## In scope

- A **false-pass / false-valid defect**: an input that a check, verifier, or validator in this
  package accepts (reports success, `valid`, or a positive verdict) when it should fail, abstain,
  or return `NOT_MEASURED` / `INCONCLUSIVE`.
- A **signature, hash, or chain-integrity weakness**: a tampered, spliced, reordered, or forged
  record that is not detected on the path this package is responsible for.
- A **totality defect** that turns a malformed input into a crash or an incorrect verdict instead
  of a determinate, safe result.
- Secret or credential handling, dependency-surface issues, or injection vectors introduced by
  this package's code.

## Out of scope (by design, disclosed — not vulnerabilities)

- The **malicious-producer limit**: a key-holder can write a *valid, signed* record whose claim or
  scope is false. This project records the decision **path and evidence**, not the **truth** of a
  model's output. That is a property of the design, documented in the README, not a bug.
- **Documented alpha limits**: anything the README or code marks as a stub, `not_implemented`,
  `NOT_MEASURED`, unsigned-by-default, or "not independently reproduced" is disclosed, tracked work
  — not a vulnerability.
- Third-party frameworks, models, or services this package integrates with, except where the
  defect is in this package's own code.

Thank you for helping keep the evidence honest.