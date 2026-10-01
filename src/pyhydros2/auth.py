"""Authorization header construction for the HYDROS Public API.

The API documents two credential formats (see ``Authentication`` in
https://developers.api.coralvuehydros.com/public-api.html):

- **V1 (simple)**: ``Authorization: {provider_key}:{device_key}``
- **V2 (HMAC-signed)**: ``Authorization: HYDROS-HMAC-SHA256
  {keyid}:{device_key}:{timestamp}:{base64-hmac}``

Only V1 is implemented here. The public spec documents V2's header *shape*
but does not publish the canonical string that must be signed (which
request parts -- method, path, body, etc. -- are covered). Shipping a
guessed HMAC scheme for an auth mechanism would be worse than not
shipping one: it could silently sign the wrong thing and offer no real
security benefit, or simply fail against the real server. Use V1 (over
HTTPS, which the client enforces) until CoralVue publishes the V2 signing
algorithm.
"""

from __future__ import annotations

from .exceptions import HydrosConfigError

_CONTROL_CHARS = frozenset(chr(c) for c in range(0x00, 0x20))


def _validate_key(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HydrosConfigError(f"Invalid {label}: must be a non-empty string")
    normalized = value.strip()
    if any(ch in _CONTROL_CHARS for ch in normalized):
        raise HydrosConfigError(f"Invalid {label}: contains control characters")
    return normalized


def build_provider_v1_header(provider_key: str, device_key: str) -> str:
    """Build the ``Authorization`` header value for V1 (simple) auth.

    Raises:
        HydrosConfigError: if either key is empty or contains header-injection
            control characters (e.g. embedded CR/LF).
    """
    provider_key = _validate_key(provider_key, "provider_key")
    device_key = _validate_key(device_key, "device_key")
    return f"{provider_key}:{device_key}"


def build_provider_v2_header(*_args: object, **_kwargs: object) -> str:
    """Build the ``Authorization`` header value for V2 (HMAC-signed) auth.

    Not implemented: the public API spec documents the header shape but not
    the canonical signing payload. Raises ``NotImplementedError``.
    """
    raise NotImplementedError(
        "HYDROS V2 (HMAC-signed) authentication is not implemented: the "
        "public API spec does not document the canonical string to sign. "
        "Use provider_v1 authentication, or consult "
        "https://forum.coralvuehydros.com/forums/hydros-developer-api.36/ "
        "for the current signing algorithm before implementing this."
    )
