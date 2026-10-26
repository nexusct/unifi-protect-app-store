"""Shared TLS verification policy for UniFi HTTP clients."""

import os


def tls_verify_from_env(name: str):
    """Return requests-compatible verification: True, False, or a CA-bundle path.

    Verification is on by default. Operators may explicitly set false for a
    controlled lab, or provide a filesystem path to their controller CA bundle.
    """
    raw = os.environ.get(name, "true").strip()
    lowered = raw.lower()
    if not raw or lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return raw
