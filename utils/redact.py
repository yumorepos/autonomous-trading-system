"""
Wallet address redaction utility.

All logging should use redact_address() before writing wallet addresses.
Separates public-safe logs from private execution records.
"""

from __future__ import annotations
import re

_ADDR_PATTERN = re.compile(r"0x([0-9a-fA-F]{4})[0-9a-fA-F]{32}([0-9a-fA-F]{4})")


def redact_address(addr: str | None) -> str:
    """Redact a wallet address to 0xABCD...EFGH format."""
    if not addr:
        return "0x????...????"
    m = _ADDR_PATTERN.match(addr)
    if m:
        return f"0x{m.group(1)}...{m.group(2)}"
    return addr[:6] + "..." + addr[-4:] if len(addr) > 10 else addr


def redact_text(text: str) -> str:
    """Redact all wallet addresses in a block of text."""
    return _ADDR_PATTERN.sub(r"0x\1...\2", text)


def redact_dict(d: dict, keys: tuple[str, ...] = ("address", "wallet", "funder", "sender", "receiver")) -> dict:
    """Redact known address fields in a dict (shallow copy)."""
    out = dict(d)
    for k in keys:
        if k in out and isinstance(out[k], str):
            out[k] = redact_address(out[k])
    return out
