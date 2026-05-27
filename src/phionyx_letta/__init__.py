"""phionyx-letta — memory-mutation audit adapter for Phionyx runtime evidence.

Every Letta memory mutation (write, append, clear, delete, forget,
consolidate) emits a signed, hash-chained envelope. The envelope schema
captures before/after content hashes, a structured diff summary, and an
optional forgetting-policy / consolidation audit subblock.

Public surface:

    from phionyx_letta import (
        SCHEMA_ID,
        MemoryDiff,
        MemoryMutationContext,
        MemoryConsolidationAudit,
        build_memory_envelope,
        compute_memory_diff,
        HmacSigner,
        FilesystemEnvelopeStore,
        verify_chain,
        GENESIS_HASH,
    )

Schema id: `phionyx.memory_mutation_envelope.v1` — additive only within
v1; new optional fields land without a schema bump. See
`examples/envelopes/v0_7_schema_portfolio.md` §7 for the cross-runtime
composition surface (`subject.metadata.memory_audit`).
"""
from __future__ import annotations

from .audit_chain import (
    GENESIS_HASH,
    SCHEMA_ID,
    FilesystemEnvelopeStore,
    HmacSigner,
    MemoryConsolidationAudit,
    MemoryDiff,
    MemoryMutationContext,
    build_memory_envelope,
    compute_memory_diff,
    verify_chain,
)

__version__ = "0.1.0a1"

__all__ = [
    "GENESIS_HASH",
    "SCHEMA_ID",
    "FilesystemEnvelopeStore",
    "HmacSigner",
    "MemoryConsolidationAudit",
    "MemoryDiff",
    "MemoryMutationContext",
    "build_memory_envelope",
    "compute_memory_diff",
    "verify_chain",
    "__version__",
]
