"""Behavior tests for the Letta memory-mutation audit chain.

Covers W3.1 (per-mutation envelope + diff + chain), W3.2 (consolidation
audit subblock), W3.3 (cross-runtime composition via
subject.metadata.memory_audit).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from phionyx_letta import (
    GENESIS_HASH,
    SCHEMA_ID,
    FilesystemEnvelopeStore,
    HmacSigner,
    MemoryConsolidationAudit,
    MemoryMutationContext,
    build_memory_envelope,
    compute_memory_diff,
    verify_chain,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def signer() -> HmacSigner:
    return HmacSigner(secret="test.fixed.secret")


@pytest.fixture
def store(tmp_path: Path) -> FilesystemEnvelopeStore:
    return FilesystemEnvelopeStore(root=tmp_path)


def _ctx(
    turn: int,
    *,
    kind: str = "write",
    before: str = "old",
    after: str = "new",
    trace: str = "letta-trace-1",
    consolidation: MemoryConsolidationAudit | None = None,
    forgetting_reason: str | None = None,
    metadata: dict | None = None,
) -> MemoryMutationContext:
    return MemoryMutationContext(
        trace_id=trace,
        turn_index=turn,
        producer="letta.agent_test",
        block_id=f"block-{turn}",
        block_label="core_memory.persona",
        mutation_kind=kind,
        diff=compute_memory_diff(before=before, after=after),
        consolidation_audit=consolidation,
        forgetting_reason=forgetting_reason,
        metadata=metadata or {},
    )


# ── W3.1 — diff primitives ─────────────────────────────────────────────────


def test_w3_1_diff_pure_append():
    """Append-only diff: added=4, removed=0, unchanged=3."""
    d = compute_memory_diff(before="abc", after="abcdefg")
    assert d.added_chars == 4
    assert d.removed_chars == 0
    assert d.unchanged_chars == 3
    assert d.before_size_bytes == 3
    assert d.after_size_bytes == 7
    assert d.before_hash.startswith("sha256:")
    assert d.after_hash.startswith("sha256:")
    assert d.before_hash != d.after_hash


def test_w3_1_diff_pure_clear():
    """Clear-style mutation: removed=full size, added=0, unchanged=0."""
    d = compute_memory_diff(before="hello world", after="")
    assert d.added_chars == 0
    assert d.removed_chars == 11
    assert d.unchanged_chars == 0
    assert d.after_size_bytes == 0


def test_w3_1_diff_identical_is_no_op():
    """Identical strings produce 0 added, 0 removed, full unchanged."""
    d = compute_memory_diff(before="same content", after="same content")
    assert d.added_chars == 0
    assert d.removed_chars == 0
    assert d.unchanged_chars == len("same content")
    assert d.before_hash == d.after_hash


def test_w3_1_diff_replace_counts_both():
    """Replace: both added and removed populated."""
    d = compute_memory_diff(before="cat", after="dog")
    assert d.removed_chars == 3
    assert d.added_chars == 3
    assert d.unchanged_chars == 0


def test_w3_1_diff_text_optional():
    """diff_text is None by default, populated when include_diff_text=True."""
    d1 = compute_memory_diff(before="a\nb", after="a\nc")
    assert d1.diff_text is None
    d2 = compute_memory_diff(before="a\nb", after="a\nc", include_diff_text=True)
    assert d2.diff_text is not None
    assert "before" in d2.diff_text  # unified diff header


# ── W3.1 — envelope builder ─────────────────────────────────────────────────


def test_w3_1_envelope_schema_and_subject(signer):
    env = build_memory_envelope(
        ctx=_ctx(turn=1),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    assert env["schema"] == SCHEMA_ID
    assert env["subject"]["runtime"] == "phionyx-letta"
    assert env["subject"]["version"] == "0.1.0a1"
    assert env["subject"]["turn_index"] == 1
    assert env["subject"]["event_type"] == "memory_write"
    assert env["subject"]["producer"] == "letta.agent_test"


def test_w3_1_envelope_mutation_block_carries_diff(signer):
    env = build_memory_envelope(
        ctx=_ctx(turn=2, before="x", after="xyz"),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    m = env["mutation"]
    assert m["block_id"] == "block-2"
    assert m["block_label"] == "core_memory.persona"
    assert m["mutation_kind"] == "write"
    assert m["diff"]["added_chars"] == 2
    assert m["diff"]["before_size_bytes"] == 1
    assert m["diff"]["after_size_bytes"] == 3
    assert m["forgetting_reason"] is None


def test_w3_1_envelope_integrity_first_envelope(signer):
    env = build_memory_envelope(
        ctx=_ctx(turn=1),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    assert env["integrity"]["previous"] == GENESIS_HASH
    assert env["integrity"]["current"].startswith("sha256:")
    assert env["integrity"]["signature"].startswith("hmac-sha256:")
    assert env["integrity"]["canonical_json"] is True


def test_w3_1_invalid_mutation_kind_rejected():
    """MemoryMutationContext rejects an unknown mutation_kind."""
    with pytest.raises(ValueError, match="not in"):
        MemoryMutationContext(
            trace_id="t",
            turn_index=1,
            producer="letta.test",
            block_id="b",
            block_label="x",
            mutation_kind="invalid_kind",
            diff=compute_memory_diff(before="a", after="b"),
        )


# ── W3.2 — forgetting + consolidation audit ────────────────────────────────


def test_w3_2_forget_envelope_carries_reason(signer):
    env = build_memory_envelope(
        ctx=_ctx(
            turn=1,
            kind="forget",
            before="sensitive data",
            after="",
            forgetting_reason="explicit_user_request",
        ),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    assert env["mutation"]["mutation_kind"] == "forget"
    assert env["mutation"]["forgetting_reason"] == "explicit_user_request"
    assert env["subject"]["event_type"] == "memory_forget"


def test_w3_2_consolidation_audit_subblock(signer):
    audit = MemoryConsolidationAudit(
        from_episodic=["mem-001", "mem-002", "mem-003"],
        to_semantic=["sem-A"],
        consolidation_method="cluster.kmeans.k3.20260527",
        decay_applied=True,
    )
    env = build_memory_envelope(
        ctx=_ctx(
            turn=1,
            kind="consolidate",
            before="raw episodic 1; raw episodic 2; raw episodic 3",
            after="consolidated semantic A",
            consolidation=audit,
        ),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    sub = env["memory_consolidation_audit"]
    assert sub is not None
    assert sub["block_ref"] == "pipeline_block_43:memory_consolidation"
    assert sub["from_episodic"] == ["mem-001", "mem-002", "mem-003"]
    assert sub["to_semantic"] == ["sem-A"]
    assert sub["consolidation_method"] == "cluster.kmeans.k3.20260527"
    assert sub["decay_applied"] is True


def test_w3_2_non_consolidation_envelope_has_null_audit(signer):
    """Write/append/clear/delete/forget mutations do not carry the
    consolidation audit subblock (it stays None)."""
    env = build_memory_envelope(
        ctx=_ctx(turn=1, kind="write"),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    assert env["memory_consolidation_audit"] is None


# ── W3.3 — cross-runtime composition ────────────────────────────────────────


def test_w3_3_no_parent_ref_produces_clean_metadata(signer):
    """Without memory_audit_parent_ref, subject.metadata does not carry
    a memory_audit field — the envelope is standalone."""
    env = build_memory_envelope(
        ctx=_ctx(turn=1),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    md = env["subject"]["metadata"]
    assert "memory_audit" not in md


def test_w3_3_parent_ref_populates_cross_runtime_composition(signer):
    """Passing memory_audit_parent_ref populates the cross-runtime
    composition handle so upstream adapter envelopes can be walked."""
    env = build_memory_envelope(
        ctx=_ctx(turn=1, kind="write"),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
        memory_audit_parent_ref="envelope://sha256:abc123",
    )
    md = env["subject"]["metadata"]["memory_audit"]
    assert md["parent_envelope_ref"] == "envelope://sha256:abc123"
    assert md["schema"] == SCHEMA_ID
    assert md["kind"] == "write"


def test_w3_3_producer_metadata_preserved_alongside_parent_ref(signer):
    """Producer-supplied metadata coexists with the memory_audit handle."""
    env = build_memory_envelope(
        ctx=_ctx(turn=1, metadata={"custom_key": "custom_value"}),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
        memory_audit_parent_ref="envelope://sha256:xyz789",
    )
    md = env["subject"]["metadata"]
    assert md["custom_key"] == "custom_value"
    assert md["memory_audit"]["parent_envelope_ref"] == "envelope://sha256:xyz789"


# ── Chain integrity (round-trip) ────────────────────────────────────────────


def test_chain_three_turns_round_trip_verifies(signer, store):
    """A 3-mutation chain stored to disk, read back, and verified end-to-end."""
    trace = "letta-trace-multi"
    head = store.head(trace)
    assert head == GENESIS_HASH

    e1 = build_memory_envelope(
        ctx=_ctx(turn=1, kind="write", before="", after="hello"),
        previous_hash=head,
        package_version="0.1.0a1",
        signer=signer,
    )
    store.append(trace, e1)

    e2 = build_memory_envelope(
        ctx=_ctx(turn=2, kind="append", before="hello", after="hello world"),
        previous_hash=store.head(trace),
        package_version="0.1.0a1",
        signer=signer,
    )
    store.append(trace, e2)

    e3 = build_memory_envelope(
        ctx=_ctx(
            turn=3,
            kind="forget",
            before="hello world",
            after="",
            forgetting_reason="retention_policy",
        ),
        previous_hash=store.head(trace),
        package_version="0.1.0a1",
        signer=signer,
    )
    store.append(trace, e3)

    chain = list(store.iter_chain(trace))
    assert len(chain) == 3
    result = verify_chain(chain)
    assert result["valid"] is True
    assert result["checked"] == 3
    assert result["broken_at"] is None


def test_chain_tampered_envelope_detected(signer, store):
    """Modify any envelope's content after persistence — verify_chain
    must detect it at the tampered turn."""
    trace = "letta-trace-tamper"
    e1 = build_memory_envelope(
        ctx=_ctx(turn=1),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    e2 = build_memory_envelope(
        ctx=_ctx(turn=2),
        previous_hash=e1["integrity"]["current"],
        package_version="0.1.0a1",
        signer=signer,
    )
    # Tamper e1's mutation block
    e1["mutation"]["block_label"] = "TAMPERED"
    result = verify_chain([e1, e2])
    assert result["valid"] is False
    assert result["broken_at"] == 0


def test_chain_refuses_mixed_schemas(signer):
    e1 = build_memory_envelope(
        ctx=_ctx(turn=1),
        previous_hash=GENESIS_HASH,
        package_version="0.1.0a1",
        signer=signer,
    )
    # Fake a different-schema envelope
    e2 = {
        "schema": "phionyx.governed_response_envelope.v0_2",
        "subject": {"turn_index": 2},
        "integrity": {"previous": e1["integrity"]["current"], "current": "sha256:00"},
    }
    result = verify_chain([e1, e2])
    assert result["valid"] is False
    assert "mixed schemas" in result["reason"]


def test_empty_chain_is_trivially_valid():
    assert verify_chain([])["valid"] is True


def test_signer_signature_format(signer):
    sig = signer.sign("sha256:abc")
    assert sig.startswith("hmac-sha256:")
    assert len(sig) == len("hmac-sha256:") + 32
