"""Memory mutation audit chain.

Schema: `phionyx.memory_mutation_envelope.v1` — one envelope per memory
mutation event (write / append / clear / delete / forget / consolidate).
Schema design mirrors the v0.2 RGE invariants (canonical JSON, SHA-256
hash chain, opt-in Ed25519 signing) so verifiers can reuse the same
walk-and-verify path.

Two W3 deliverables built on this module:

* W3.1 — per-mutation envelope: `MemoryMutationContext` →
  `build_memory_envelope` produces the signed dict.
* W3.2 — forgetting / consolidation audit: optional
  `MemoryConsolidationAudit` subblock surfaces the bridge to canonical
  pipeline block #43 (`memory_consolidation`).

W3.3 (cross-runtime composition) is documented in the README §6 and
implemented by the `subject.metadata.memory_audit` reference object —
populated by upstream adapter envelopes (langchain_event,
openai_agents_event, RGE v0.2) when they cause a memory mutation that
this package records.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Protocol


SCHEMA_ID = "phionyx.memory_mutation_envelope.v1"
RUNTIME = "phionyx-letta"
GENESIS_HASH = "sha256:" + ("0" * 64)


# ── Canonical JSON helper (byte-identical with other Phionyx adapters) ─────

def canonical_json(payload: dict[str, Any]) -> str:
    """Sort_keys, no whitespace, ASCII-safe, no NaN — matches the
    canonical_json helper used in phionyx-mcp-server,
    phionyx-langchain-langgraph, etc."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ── Memory diff primitives ─────────────────────────────────────────────────

@dataclass(frozen=True)
class MemoryDiff:
    """Summary diff between two memory block states.

    Always carries the size deltas (cheap, audit-friendly) and SHA-256
    content hashes for tamper-evidence. Optional `diff_text` carries a
    unified-diff style payload — withheld by default to avoid leaking
    raw memory contents into envelopes when those contents may contain
    PII or model-private state. Producers that need replay enable
    `include_diff_text=True` at compute time.
    """

    before_hash: str  # "sha256:<64-hex>"
    after_hash: str  # "sha256:<64-hex>"
    before_size_bytes: int
    after_size_bytes: int
    added_chars: int
    removed_chars: int
    unchanged_chars: int
    diff_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "before_size_bytes": self.before_size_bytes,
            "after_size_bytes": self.after_size_bytes,
            "added_chars": self.added_chars,
            "removed_chars": self.removed_chars,
            "unchanged_chars": self.unchanged_chars,
            "diff_text": self.diff_text,
        }


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_memory_diff(
    before: str,
    after: str,
    *,
    include_diff_text: bool = False,
) -> MemoryDiff:
    """Compute a structured diff summary between two memory block states.

    Uses difflib.SequenceMatcher for opcodes — O(n*m) worst case but the
    char-level breakdown is robust and well-understood. For very large
    memory blocks (>1MB), the caller should pre-truncate or hash without
    a structured diff.

    Returns a `MemoryDiff` with size deltas + per-op character counts;
    `diff_text` is None unless `include_diff_text=True`.
    """
    before_str = before or ""
    after_str = after or ""

    added = 0
    removed = 0
    unchanged = 0
    matcher = SequenceMatcher(a=before_str, b=after_str, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "insert":
            added += j2 - j1
        elif tag == "replace":
            removed += i2 - i1
            added += j2 - j1

    diff_text: str | None = None
    if include_diff_text:
        # Compact unified-diff style payload. Producers that want raw
        # text can use difflib.unified_diff externally and pass it via
        # MemoryMutationContext.mutation_metadata.
        from difflib import unified_diff

        diff_text = "\n".join(
            unified_diff(
                before_str.splitlines(keepends=False),
                after_str.splitlines(keepends=False),
                fromfile="before",
                tofile="after",
                n=2,
                lineterm="",
            )
        )

    return MemoryDiff(
        before_hash=_sha256(before_str),
        after_hash=_sha256(after_str),
        before_size_bytes=len(before_str.encode("utf-8")),
        after_size_bytes=len(after_str.encode("utf-8")),
        added_chars=added,
        removed_chars=removed,
        unchanged_chars=unchanged,
        diff_text=diff_text,
    )


# ── Memory consolidation audit subblock (W3.2) ─────────────────────────────

@dataclass(frozen=True)
class MemoryConsolidationAudit:
    """Optional bridge to canonical pipeline block #43 (memory_consolidation).

    When a mutation is a *consolidation* event — episodic memories
    promoted to semantic, decayed memories pruned, or weak memories
    tombstoned — this subblock captures which memory ids participated
    and which algorithm produced the promotion. Cross-references the
    pipeline block by its canonical id so reviewers can replay the
    consolidation against the pipeline's recorded state.

    Fields:
        block_ref: canonical pipeline block reference, e.g.
            `pipeline_block_43:memory_consolidation`
        from_episodic: list of episodic memory ids that participated
        to_semantic: list of semantic memory ids produced (may be empty
            for pure-pruning consolidations)
        consolidation_method: producer-named algorithm identifier
        decay_applied: True if memory decay was applied, False if not,
            None when not tracked
    """

    block_ref: str = "pipeline_block_43:memory_consolidation"
    from_episodic: list[str] = field(default_factory=list)
    to_semantic: list[str] = field(default_factory=list)
    consolidation_method: str = ""
    decay_applied: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_ref": self.block_ref,
            "from_episodic": list(self.from_episodic),
            "to_semantic": list(self.to_semantic),
            "consolidation_method": self.consolidation_method,
            "decay_applied": self.decay_applied,
        }


# ── Mutation context ───────────────────────────────────────────────────────

# Mutation kind enum — keep the set narrow so reviewers can reason about
# the surface. New kinds land additively, never break removals.
MUTATION_KINDS = frozenset({
    "write",       # full replace of a memory block
    "append",      # add to the end of a memory block
    "clear",       # zero out a memory block
    "delete",      # remove the memory block entirely
    "forget",      # explicit forgetting (tombstone, retention policy)
    "consolidate", # episodic → semantic promotion (carries MemoryConsolidationAudit)
})


@dataclass(frozen=True)
class MemoryMutationContext:
    """The minimum a host must surface for a v1-compliant memory envelope.

    `block_id` and `block_label` together identify which memory block
    mutated. `block_id` should be the stable Letta block UUID; `block_label`
    is the human-readable label (e.g. `core_memory.persona`).
    """

    trace_id: str
    turn_index: int
    producer: str  # e.g. "letta.agent_alex"
    block_id: str
    block_label: str
    mutation_kind: str  # one of MUTATION_KINDS
    diff: MemoryDiff
    consolidation_audit: MemoryConsolidationAudit | None = None
    forgetting_reason: str | None = None  # populated when mutation_kind in {"forget", "delete", "clear"}
    metadata: dict[str, Any] = field(default_factory=dict)  # producer-supplied opaque key/value

    def __post_init__(self) -> None:
        if self.mutation_kind not in MUTATION_KINDS:
            raise ValueError(
                f"mutation_kind {self.mutation_kind!r} not in {sorted(MUTATION_KINDS)}"
            )


# ── Signer + Store (protocol-compatible with phionyx-mcp-server) ───────────

class Signer(Protocol):
    """Minimal signer surface so the envelope builder stays backend-agnostic."""

    def sign(self, current_hash: str) -> str: ...


class HmacSigner:
    """Demo signer (HMAC over current_hash). Production uses Ed25519."""

    def __init__(self, secret: str = "phionyx.letta.demo.replace.in.production") -> None:
        self._secret = secret.encode("utf-8")

    def sign(self, current_hash: str) -> str:
        digest = _hmac.new(self._secret, current_hash.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest[:32]}"


class EnvelopeStore(Protocol):
    def head(self, trace_id: str) -> str: ...
    def append(self, trace_id: str, envelope: dict[str, Any]) -> None: ...
    def iter_chain(self, trace_id: str) -> Iterable[dict[str, Any]]: ...


class FilesystemEnvelopeStore:
    """Default filesystem-backed envelope store.

    Layout::

        <root>/<trace_id>/chain.jsonl       (turn_index, current_hash, previous_hash, envelope_path)
        <root>/<trace_id>/<turn_index>.json (full envelope)
    """

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = Path(
                os.environ.get("PHIONYX_LETTA_AUDIT_ROOT", "~/.phionyx/letta_audit")
            ).expanduser()
        self.root = Path(root)

    def _trace_dir(self, trace_id: str) -> Path:
        safe = trace_id.replace("/", "_").replace("..", "__")
        return self.root / safe

    def head(self, trace_id: str) -> str:
        chain = self._trace_dir(trace_id) / "chain.jsonl"
        if not chain.exists():
            return GENESIS_HASH
        with chain.open("r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        if not lines:
            return GENESIS_HASH
        try:
            return str(json.loads(lines[-1])["current_hash"])
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"corrupt chain index for {trace_id!r}: {e}") from e

    def append(self, trace_id: str, envelope: dict[str, Any]) -> None:
        td = self._trace_dir(trace_id)
        td.mkdir(parents=True, exist_ok=True)
        turn = int(envelope["subject"]["turn_index"])
        envelope_path = td / f"{turn:06d}.json"
        envelope_path.write_text(canonical_json(envelope), encoding="utf-8")
        index_entry = {
            "turn_index": turn,
            "current_hash": envelope["integrity"]["current"],
            "previous_hash": envelope["integrity"]["previous"],
            "envelope_path": str(envelope_path.relative_to(self.root)),
        }
        with (td / "chain.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_entry, sort_keys=True) + "\n")

    def iter_chain(self, trace_id: str) -> Iterable[dict[str, Any]]:
        chain = self._trace_dir(trace_id) / "chain.jsonl"
        if not chain.exists():
            return
        with chain.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                envelope_path = self.root / entry["envelope_path"]
                yield json.loads(envelope_path.read_text(encoding="utf-8"))


# ── Envelope builder ───────────────────────────────────────────────────────


def _envelope_hash(payload: dict[str, Any], previous_hash: str) -> str:
    """SHA-256 over canonical-JSON({record: payload_without_integrity, previous: previous_hash})."""
    record = {k: v for k, v in payload.items() if k != "integrity"}
    bound = canonical_json({"record": record, "previous": previous_hash})
    return "sha256:" + hashlib.sha256(bound.encode("utf-8")).hexdigest()


def build_memory_envelope(
    ctx: MemoryMutationContext,
    *,
    previous_hash: str,
    package_version: str,
    signer: Signer,
    memory_audit_parent_ref: str | None = None,
) -> dict[str, Any]:
    """Build a v1 memory-mutation envelope.

    Args:
        ctx: the mutation context (block id, kind, diff, optional
            consolidation audit, optional forgetting reason).
        previous_hash: chain head for ctx.trace_id; pass `GENESIS_HASH`
            for the first envelope in a chain.
        package_version: semver string for the `subject.version` field
            (e.g. `0.1.0a1`).
        signer: produces `integrity.signature`.
        memory_audit_parent_ref: optional `envelope://sha256:<hex>`
            reference back to the upstream adapter envelope (langchain,
            openai_agents, RGE v0.2, …) that caused this mutation.
            Populates `subject.metadata.memory_audit.parent_envelope_ref`.
            W3.3 cross-runtime composition.

    Returns a fully-formed envelope dict ready for an EnvelopeStore.
    """
    subject_metadata: dict[str, Any] = dict(ctx.metadata)
    if memory_audit_parent_ref is not None:
        subject_metadata["memory_audit"] = {
            "parent_envelope_ref": memory_audit_parent_ref,
            "schema": SCHEMA_ID,
            "kind": ctx.mutation_kind,
        }

    payload: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "subject": {
            "runtime": RUNTIME,
            "version": package_version,
            "producer": ctx.producer,
            "turn_index": ctx.turn_index,
            "event_type": f"memory_{ctx.mutation_kind}",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": subject_metadata,
        },
        "mutation": {
            "block_id": ctx.block_id,
            "block_label": ctx.block_label,
            "mutation_kind": ctx.mutation_kind,
            "diff": ctx.diff.to_dict(),
            "forgetting_reason": ctx.forgetting_reason,
        },
        "memory_consolidation_audit": (
            ctx.consolidation_audit.to_dict()
            if ctx.consolidation_audit is not None
            else None
        ),
    }

    current_hash = _envelope_hash(payload, previous_hash)
    payload["integrity"] = {
        "previous": previous_hash,
        "current": current_hash,
        "signature": signer.sign(current_hash),
        "canonical_json": True,
    }
    return payload


# ── Verification ───────────────────────────────────────────────────────────


def verify_chain(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk a chain of envelopes and verify integrity.

    Returns `{"valid": bool, "checked": int, "broken_at": int|None,
    "reason": str|None}`. Mirrors the verifier semantics of
    phionyx-mcp-server.audit_chain.verify_chain so downstream tools can
    treat both surfaces uniformly.
    """
    if not envelopes:
        return {"valid": True, "checked": 0, "broken_at": None, "reason": None}

    schemas = {e.get("schema", "<missing>") for e in envelopes}
    if len(schemas) > 1:
        return {
            "valid": False,
            "checked": 0,
            "broken_at": 0,
            "reason": f"mixed schemas in chain: {sorted(schemas)}",
        }

    previous = GENESIS_HASH
    for i, env in enumerate(envelopes):
        integrity = env.get("integrity") or {}
        claimed_previous = integrity.get("previous")
        claimed_current = integrity.get("current")
        if claimed_previous != previous:
            return {
                "valid": False,
                "checked": i,
                "broken_at": i,
                "reason": f"previous mismatch at turn {env['subject']['turn_index']}",
            }
        recomputed = _envelope_hash(env, previous)
        if recomputed != claimed_current:
            return {
                "valid": False,
                "checked": i,
                "broken_at": i,
                "reason": f"content tampered at turn {env['subject']['turn_index']}",
            }
        previous = claimed_current

    return {"valid": True, "checked": len(envelopes), "broken_at": None, "reason": None}
