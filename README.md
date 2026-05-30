# phionyx-letta

> **Memory-mutation audit chain for Letta agents** — every memory write,
> append, clear, delete, forget, or consolidation emits a signed,
> hash-chained envelope with a structured before/after diff.
> AGPL-3.0 · Python 3.10+ · alpha (v0.1.0a1)

Phionyx-letta is a **framework adapter** in the Phionyx portfolio. It
implements the **memory diff audit** layer described in the Phionyx
runtime-evidence design. It treats Letta core-memory blocks the same way
the rest of the Phionyx stack treats agent turns: every state change is
captured in a hash-chained, tamper-evident envelope that a third party
can replay without operator-side insider knowledge.

**Where this sits in the Phionyx stack.** Phionyx ships three distinct
things, each with its own version line:

- **Engine** — `phionyx-core` (latest v0.7.2): the deterministic-cognition
  SDK (46-block canonical pipeline, contract v3.8.0; state vector; kill
  switch; HITL; ethics/safety gates; signed audit chain). It is the
  reference implementation that scores L3 + D3 on the Evaluation Standard.
- **Gate** — `phionyx-pipeline-mcp` (stable v0.2.0, alpha v0.3.0a1): the
  self-governance MCP gate that verifies an agent's own "I fixed / I
  tested / this changed" claims. This is the component the
  Claim-Governance ladder (CG-L0…CG-L5) rates.
- **Standard** — `phionyx-evaluation-standard` (released v0.1.1 / v0.2.0;
  v0.3 layer in draft): a vendor-neutral spec defining L0-L3 (evaluation
  maturity), D0-D3 (determinism), and CG-L0…CG-L5 (claim-governance).

**`phionyx-letta` (v0.1.0a1) is a framework adapter** — it emits audit
envelopes; it is not the engine, the gate, or the Standard. Its envelopes
share the engine's canonical JSON + SHA-256 hash chain and verify against
`phionyx-mcp-server` (v0.1.0). See the Evaluation Standard for the
vendor-neutral L0-L3 / D0-D3 / CG-L0…CG-L5 scales that place every
component on a common footing.

## What it gives you

For each memory mutation:

- A **structured diff summary** — before/after content hashes, byte
  sizes, character-level added / removed / unchanged counts.
- A **typed mutation kind** — one of `write`, `append`, `clear`,
  `delete`, `forget`, `consolidate`.
- An optional **forgetting reason** — for `clear`, `delete`, `forget`
  mutations (e.g. `explicit_user_request`, `retention_policy`,
  `consolidation_promotion`).
- An optional **consolidation audit subblock** — for `consolidate`
  mutations, cross-references canonical pipeline block #43
  (`memory_consolidation`) with the participating memory ids and
  algorithm identifier.
- An optional **cross-runtime parent reference** — when the mutation
  was caused by an upstream adapter envelope (langchain, openai_agents,
  RGE v0.2), this envelope can point back at it via
  `subject.metadata.memory_audit.parent_envelope_ref`.

All envelopes share Phionyx's canonical JSON + SHA-256 hash chain +
opt-in Ed25519 signing surface (HMAC for demo). The verifier semantics
match `phionyx-mcp-server` (v0.1.0) `audit_chain.verify_chain`
byte-for-byte.

## Sixty-second usage

```python
from phionyx_letta import (
    MemoryMutationContext,
    HmacSigner,
    FilesystemEnvelopeStore,
    build_memory_envelope,
    compute_memory_diff,
    GENESIS_HASH,
)

signer = HmacSigner(secret="REPLACE_IN_PRODUCTION_WITH_ED25519")
store = FilesystemEnvelopeStore(root="/var/lib/phionyx/letta_audit")

# Compute the diff between before and after content
diff = compute_memory_diff(
    before="User prefers concise answers.",
    after="User prefers concise answers. They speak Turkish.",
)

ctx = MemoryMutationContext(
    trace_id="letta-trace-alex-001",
    turn_index=42,
    producer="letta.agent_alex",
    block_id="block-9e3a-...",
    block_label="core_memory.persona",
    mutation_kind="append",
    diff=diff,
)

envelope = build_memory_envelope(
    ctx=ctx,
    previous_hash=store.head("letta-trace-alex-001"),
    package_version="0.1.0a1",
    signer=signer,
)
store.append("letta-trace-alex-001", envelope)
```

## Schema

`phionyx.memory_mutation_envelope.v1` — one envelope per memory
mutation event. The cross-runtime composition surface
(`subject.metadata.memory_audit`) is documented in the schema portfolio
shipped with the public Phionyx research umbrella
(`phionyx-research`).

Top-level structure:

```json
{
  "schema": "phionyx.memory_mutation_envelope.v1",
  "subject": {
    "runtime": "phionyx-letta",
    "version": "0.1.0a1",
    "producer": "<letta agent identifier>",
    "turn_index": <int>,
    "event_type": "memory_<kind>",
    "timestamp_utc": "<ISO-8601 UTC>",
    "metadata": {
      "memory_audit": {                              // cross-runtime composition (optional)
        "parent_envelope_ref": "envelope://sha256:...",
        "schema": "phionyx.memory_mutation_envelope.v1",
        "kind": "<mutation kind>"
      },
      "<producer-supplied keys>": "..."
    }
  },
  "mutation": {
    "block_id": "<stable Letta block id>",
    "block_label": "<e.g. core_memory.persona>",
    "mutation_kind": "<write|append|clear|delete|forget|consolidate>",
    "diff": {
      "before_hash": "sha256:<hex>",
      "after_hash": "sha256:<hex>",
      "before_size_bytes": <int>,
      "after_size_bytes": <int>,
      "added_chars": <int>,
      "removed_chars": <int>,
      "unchanged_chars": <int>,
      "diff_text": null | "<unified diff>"
    },
    "forgetting_reason": null | "<reason>"
  },
  "memory_consolidation_audit": null | {           // only for `consolidate` mutations
    "block_ref": "pipeline_block_43:memory_consolidation",
    "from_episodic": ["<mem-id>", ...],
    "to_semantic": ["<sem-id>", ...],
    "consolidation_method": "<algorithm id>",
    "decay_applied": null | true | false
  },
  "integrity": {
    "previous": "sha256:<hex>",
    "current":  "sha256:<hex>",
    "signature": "<algo>:<hex>",
    "canonical_json": true
  }
}
```

## Cross-runtime composition

When a Letta memory mutation is triggered by another adapter (a
LangGraph node, an OpenAI Agents tool call, an RGE v0.2 turn), the
upstream envelope's id can be passed as `memory_audit_parent_ref`:

```python
envelope = build_memory_envelope(
    ctx=ctx,
    previous_hash=store.head(trace_id),
    package_version="0.1.0a1",
    signer=signer,
    memory_audit_parent_ref="envelope://sha256:<upstream RGE envelope current>",
)
```

The resulting envelope carries `subject.metadata.memory_audit` so a
reviewer can walk from any upstream envelope to the memory mutation it
caused without needing matching schema ids. The reference is *one-way*
(memory envelope → upstream envelope) because the upstream envelope is
sealed at sign time and cannot be amended retroactively.

The reverse direction is recommended on upstream emitters that *know*
they cause memory mutations: emit your envelope first, then build the
memory mutation envelope with `memory_audit_parent_ref` set to your own
`integrity.current`. The two envelopes form a verifiable pair.

## What this package does NOT do

- **It does not instrument Letta automatically.** You compute the diff
  yourself (with `compute_memory_diff` or your own logic) and call
  `build_memory_envelope` at the right point in your code. A future
  release MAY ship a Letta runtime hook that intercepts memory writes;
  v0.1.0a1 ships the audit primitives only.
- **It does not store memory contents by default.** `diff.diff_text` is
  None unless the caller explicitly requests it (`include_diff_text=True`).
  Size deltas + content hashes are always recorded; raw text is opt-in.
- **It does not interpret mutation semantics.** A `forget` envelope
  with `forgetting_reason="retention_policy"` is just two strings to
  this package — the operator decides what they mean.
- **It does not certify compliance.** Like the rest of the Phionyx
  stack, this is *evidence-grade audit*, not a regulatory attestation.

## Status

Current release: **v0.1.0a1** (alpha). The following capabilities are
available:

- **Per-mutation envelope.** Available. 20/20 tests pass.
- **Forgetting + consolidation audit subblock.** Available.
- **Cross-runtime composition.** Available via
  `subject.metadata.memory_audit`.

This is an alpha adapter; the API surface may change before a stable
release.

## License

AGPL-3.0-or-later. See the [`LICENSE`](./LICENSE) file in this
repository.

## Citing

If you use phionyx-letta in academic or policy work, cite the parent
project: Abak, A. T. (2026). *Phionyx Research — Runtime Evidence Layer
for Agentic AI*. ORCID
[0009-0002-3718-4010](https://orcid.org/0009-0002-3718-4010).
