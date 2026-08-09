"""WP-13 — honest signer contract (mirrors phionyx-mcp-server WP-11).

An unconfigured run must emit EXPLICITLY UNSIGNED envelopes, never a silent demo-HMAC signature
that looks real. Demo-HMAC and Ed25519 are opt-in via environment.
"""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from phionyx_letta import (
    Ed25519Signer,
    HmacSigner,
    UnsignedSigner,
    get_signer,
    signature_algorithm,
)

ENV = "PHIONYX_LETTA"


def _clear(mp):
    for s in ("SIGNING_KEY", "DEMO", "KEY_ID"):
        mp.delenv(f"{ENV}_{s}", raising=False)


def test_default_is_unsigned(monkeypatch):
    _clear(monkeypatch)
    s = get_signer()
    assert isinstance(s, UnsignedSigner)
    assert s.sign("sha256:x") == "unsigned"
    assert signature_algorithm(s.sign("sha256:x")) == "unsigned"


def test_demo_flag_selects_hmac(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(f"{ENV}_DEMO", "1")
    s = get_signer()
    assert isinstance(s, HmacSigner)
    assert signature_algorithm(s.sign("sha256:x")) == "hmac-sha256"


def test_key_selects_ed25519(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(f"{ENV}_SIGNING_KEY", Ed25519PrivateKey.generate().private_bytes_raw().hex())
    s = get_signer()
    assert isinstance(s, Ed25519Signer)
    sig = s.sign("sha256:x")
    assert sig.startswith("ed25519:") and signature_algorithm(sig) == "ed25519"


def test_key_beats_demo(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv(f"{ENV}_DEMO", "1")
    monkeypatch.setenv(f"{ENV}_SIGNING_KEY", Ed25519PrivateKey.generate().private_bytes_raw().hex())
    assert isinstance(get_signer(), Ed25519Signer)


def test_signature_algorithm_sentinels():
    assert signature_algorithm("") == "unsigned"
    assert signature_algorithm("unsigned") == "unsigned"
    assert signature_algorithm("hmac-sha256:ab") == "hmac-sha256"
    assert signature_algorithm("weird-no-colon") == "unknown"


def test_key_file_with_trailing_indented_comment(monkeypatch, tmp_path):
    """_load_key_material must strip comment lines even when indented / trailing (codex blocker).

    Key first, then an indented comment as the LAST line: pre-fix the loader returned the comment
    and hard-failed; post-fix the comment is skipped and the key loads.
    """
    _clear(monkeypatch)
    seed = Ed25519PrivateKey.generate().private_bytes_raw().hex()
    kf = tmp_path / "key.hex"
    kf.write_text(f"{seed}\n   # trailing indented comment\n", encoding="utf-8")
    monkeypatch.setenv(f"{ENV}_SIGNING_KEY", str(kf))
    s = get_signer()
    assert isinstance(s, Ed25519Signer)
    assert s.sign("sha256:x").startswith("ed25519:")
