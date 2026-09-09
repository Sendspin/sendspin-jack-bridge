"""Identity persistence tests use only isolated, temporary test state."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("jack", MagicMock())

from sendspin_jack_bridge.state import load_identity, lock_state  # noqa: E402


class IdentityTests(unittest.TestCase):
    """Check persistence, fail-closed reads, and exclusive ownership."""

    def test_identity_survives_restart(self) -> None:
        """Repeated starts keep the same public identity and secure POSIX mode."""
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with lock_state(state):
                first = load_identity(state).peer_id
            with lock_state(state):
                self.assertEqual(load_identity(state).peer_id, first)
            if os.name != "nt":
                self.assertEqual((state / "identity.key").stat().st_mode & 0o777, 0o600)

    def test_invalid_identity_is_never_replaced(self) -> None:
        """Empty, malformed, and non-ASCII data fail without revealing contents."""
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            path = state / "identity.key"
            for data in (b"", b"invalid-test-data", b"!" * 43, b"\xff"):
                with self.subTest(data_length=len(data)):
                    path.write_bytes(data)
                    with lock_state(state), self.assertRaisesRegex(ValueError, "Invalid identity"):
                        load_identity(state)
                    self.assertEqual(path.read_bytes(), data)

    def test_failed_atomic_publish_leaves_no_partial_identity(self) -> None:
        """Failed replacement does not publish an empty or incomplete identity."""
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with (
                lock_state(state),
                patch.object(Path, "replace", side_effect=OSError("test failure")),
                self.assertRaises(OSError),
            ):
                load_identity(state)
            self.assertEqual([p.name for p in state.iterdir()], ["bridge.lock"])

    def test_concurrent_process_is_rejected_and_lock_releases(self) -> None:
        """A second process cannot race identity creation or pairing-store writes."""
        script = (
            "import sys; from unittest.mock import MagicMock; sys.modules['jack'] = MagicMock(); "
            "from pathlib import Path; "
            "from sendspin_jack_bridge.state import lock_state; "
            "lock = lock_state(Path(sys.argv[1])); lock.__enter__(); lock.__exit__(None,None,None)"
        )
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with lock_state(state):
                result = subprocess.run(  # noqa: S603
                    [sys.executable, "-c", script, directory], capture_output=True, check=False
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Cannot lock state directory", result.stderr)
            with lock_state(state):
                load_identity(state)
