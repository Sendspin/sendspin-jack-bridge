"""Persistent identity and exclusive access to a bridge's pairing state."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from aiosendspin.noise.keys import Identity, b64url_decode

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@contextmanager
def lock_state(state_dir: Path) -> Iterator[None]:
    """Hold an OS lock for the lifetime of the client, including pairing writes.

    Closing the file releases the lock even after a crash. Leave the lock file
    in place so another process cannot lock a different inode at the same path.
    """
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(state_dir / "bridge.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        try:
            if sys.platform == "win32":
                # Windows byte-range locks require a byte to lock.
                if os.fstat(lock.fileno()).st_size == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                f"Cannot lock state directory {state_dir}; another bridge may be using it. "
                "Use a separate --state-dir for each instance."
            ) from None
        yield


def load_identity(state_dir: Path) -> Identity:
    """Load or atomically create an identity while holding ``lock_state``.

    Never replace invalid state: doing so would silently change the client ID
    and invalidate existing pairings. Error messages must not include key data.
    """
    path = state_dir / "identity.key"
    try:
        encoded = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        identity = Identity.generate()
        # NamedTemporaryFile creates an owner-only file on POSIX. Close it before
        # replacing the destination so the rename also works on Windows.
        with tempfile.NamedTemporaryFile(dir=state_dir, delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                temp.write((identity.private_b64u + "\n").encode("ascii"))
                temp.flush()
                os.fsync(temp.fileno())
            except BaseException:
                temp.close()
                temp_path.unlink(missing_ok=True)
                raise
        try:
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
        return identity
    except UnicodeError:
        raise ValueError(
            f"Invalid identity file {path}; restore it from a trusted backup."
        ) from None

    try:
        identity = Identity.from_private_bytes(b64url_decode(encoded))
    except ValueError:
        raise ValueError(
            f"Invalid identity file {path}; restore it from a trusted backup."
        ) from None
    if identity.private_b64u != encoded:
        raise ValueError(f"Invalid identity file {path}; restore it from a trusted backup.")
    if sys.platform != "win32":
        path.chmod(0o600)
    return identity
