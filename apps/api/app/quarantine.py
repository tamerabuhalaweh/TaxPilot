"""Private quarantine storage (EP-04B). Local dev/test adapter + fail-closed policy.

Security model: opaque unpredictable keys (never derived from filenames),
tenant-namespaced directories, atomic writes with restrictive permissions,
symlink refusal, path-containment checks on every access. No listing, no
download, no content reads: quarantined bytes are write/delete-only until a
future scan gate (EP-04C) authorizes release. Staging/production always report
not-ready: no approved private object store, region, encryption, or malware
scanning exists in this slice, and local disk is never production persistence.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{2}/[A-Za-z0-9_-]{43}$"
)


class StorageUnavailable(Exception):
    """Quarantine cannot accept bytes in this environment (fail closed)."""


def storage_readiness(environment: str, backend: str, root: str | None) -> tuple[bool, str]:
    """Decide whether quarantine intake may accept bytes (pure, testable).

    Staging/production always refuse: local disk is dev/test-only and no
    remote provider is approved yet. Development/test require an explicit root.
    """
    if environment in ("staging", "production"):
        return False, (
            "quarantine storage is not approved for staging/production: no private "
            "object store, region, encryption, or malware scanning exists yet (EP-04C)"
        )
    if backend != "local":
        return False, f"storage backend {backend!r} is not implemented"
    if not root or not root.strip():
        return False, "quarantine root is not configured (refusing local fallback)"
    return True, "local quarantine ready (development/test only)"


def new_storage_key(tenant_id: str, sha256_hex: str) -> str:
    """Opaque unpredictable key namespaced by tenant and hash shard.

    The random token (256 bits) is the entire secret: keys are unguessable,
    unlistable, and carry no filename, type, or ordering information.
    """
    return f"{tenant_id}/{sha256_hex[:2]}/{secrets.token_urlsafe(32)}"


def _resolve(root: Path, key: str) -> Path:
    if not _KEY_RE.match(key):
        raise ValueError("malformed storage key")
    base = root.resolve()
    candidate = (base / key).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("storage path escapes quarantine")
    if candidate.is_symlink():
        raise ValueError("storage path is a symlink")
    return candidate


class LocalQuarantine:
    """Development/test-only private quarantine rooted at one directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        if self._root.is_symlink():
            raise StorageUnavailable("quarantine root must not be a symlink")

    def put(self, key: str, data: bytes) -> int:
        """Atomically store bytes under an opaque key. Returns byte count."""
        if self._root.is_symlink():
            raise StorageUnavailable("quarantine root must not be a symlink")
        path = _resolve(self._root, key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise StorageUnavailable("quarantine shard must not be a symlink")
        tmp = path.parent / f".tmp-{secrets.token_hex(8)}"
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return len(data)

    def delete(self, key: str) -> None:
        """Best-effort orphan cleanup. Missing blobs are not an error."""
        try:
            path = _resolve(self._root, key)
        except ValueError:
            return
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        try:
            path = _resolve(self._root, key)
        except ValueError:
            return False
        return path.is_file() and not path.is_symlink()
