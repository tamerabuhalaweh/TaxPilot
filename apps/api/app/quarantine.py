"""Private quarantine storage (EP-04B). Local dev/test adapter + fail-closed policy.

Security model: opaque unpredictable keys (never derived from filenames),
tenant-namespaced directories, exclusive atomic writes that are owner-only
from the first byte (no readable window), enforced owner-only directories,
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
import stat
from pathlib import Path

_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{2}/[A-Za-z0-9_-]{43}$"
)
_DIR_MODE = 0o700
_FILE_MODE = 0o600


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


def _posix_owner(path: Path) -> int | None:
    if not hasattr(os, "getuid"):
        return None  # non-POSIX (e.g. Windows dev): ownership check unavailable
    try:
        return path.stat().st_uid
    except OSError:
        return None


def _ensure_dir(path: Path, *, what: str) -> Path:
    """Create-or-validate one quarantine directory: real dir, owner-only mode.

    Pre-existing loose permissions are tightened (documented contract: roots
    and shards are owner-only); symlinks, non-directories, and foreign-owned
    directories fail closed.
    """
    if path.is_symlink():
        raise StorageUnavailable(f"quarantine {what} must not be a symlink")
    path.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise StorageUnavailable(f"quarantine {what} must be a real directory")
    try:
        os.chmod(path, _DIR_MODE)
    except OSError as exc:
        raise StorageUnavailable(f"quarantine {what} permissions cannot be enforced") from exc
    if hasattr(os, "getuid"):
        owner = _posix_owner(path)
        if owner is not None and owner != os.getuid():
            raise StorageUnavailable(f"quarantine {what} is not owned by this process user")
    return path.resolve()


class LocalQuarantine:
    """Development/test-only private quarantine rooted at one directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        _ensure_dir(self._root, what="root")

    def _shard(self, key: str) -> tuple[Path, Path]:
        tenant, shard, _token = key.split("/")
        base = _ensure_dir(self._root, what="root")
        tenant_dir = _ensure_dir(base / tenant, what="tenant directory")
        shard_dir = _ensure_dir(tenant_dir / shard, what="shard directory")
        path = _resolve(self._root, key)
        if path.parent != shard_dir:
            raise ValueError("storage path escapes quarantine")
        return shard_dir, path

    def put(self, key: str, data: bytes) -> int:
        """Atomically store bytes under an opaque key. Returns byte count.

        The temp file is created exclusively (O_EXCL: pre-existing symlinks or
        files fail instead of being followed) with owner-only mode from the
        first byte, so quarantined content is never group/other-readable —
        not even between creation and chmod. Final placement is atomic rename.
        """
        if not isinstance(data, bytes | bytearray):
            raise TypeError(f"data must be bytes, got {type(data).__name__}")
        _shard_dir, path = self._shard(key)
        for _attempt in range(3):
            tmp = path.parent / f".tmp-{secrets.token_hex(16)}"
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
            except FileExistsError:
                continue
            break
        else:
            raise StorageUnavailable("quarantine temp file cannot be created exclusively")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(data))
            os.chmod(tmp, _FILE_MODE)
            if tmp.is_symlink():
                raise StorageUnavailable("quarantine temp file is a symlink")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return len(data)

    def delete(self, key: str) -> None:
        """Best-effort orphan cleanup. Missing blobs are not an error."""
        try:
            _shard_dir, path = self._shard(key)
        except (ValueError, StorageUnavailable):
            return
        try:
            if path.is_symlink():
                return  # never follow links, even for deletion
            os.unlink(path)
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        try:
            _shard_dir, path = self._shard(key)
        except (ValueError, StorageUnavailable):
            return False
        return path.is_file() and not path.is_symlink()

    def blob_mode(self, key: str) -> int | None:
        """POSIX mode bits of a stored blob (introspection for tests/ops)."""
        try:
            _shard_dir, path = self._shard(key)
            return stat.S_IMODE(path.stat().st_mode)
        except (ValueError, StorageUnavailable, OSError):
            return None
