"""Source lifecycle regressions using real 9.1.1 models and a mocked JACK device."""

from __future__ import annotations

import asyncio
import struct
import sys
import unittest
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from aiosendspin.models.core import ServerCommandPayload
from aiosendspin.models.source import SourceCommandServerPayload

# No native JACK library or running audio server is required by these unit tests.
sys.modules.setdefault("jack", MagicMock())

from sendspin_jack_bridge.bridge import JackSendspinBridge  # noqa: E402


def command(value: Literal["start", "stop"]) -> ServerCommandPayload:
    """Build a command with the actual aiosendspin model."""
    return ServerCommandPayload(source=SourceCommandServerPayload(command=value))


class SourceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """Exercise command ordering, timestamps, and failures without network I/O."""

    def setUp(self) -> None:
        """Prepare a source and controlled asynchronous capture."""
        self.bridge = JackSendspinBridge("ws://localhost/sendspin")
        self.bridge._sample_rate = 48000
        self.bridge._blocksize = 2
        self.capture = MagicMock()
        self.capture.start = AsyncMock()
        self.capture.stop = AsyncMock()
        self.capture.feed = AsyncMock()
        self.client = MagicMock()
        self.client.create_source_capture.return_value = self.capture
        self.client.now_us.return_value = 0
        self.client.disconnect = AsyncMock()
        self.bridge._sendspin_client = self.client

    async def test_waits_for_command_and_duplicate_start_is_idempotent(self) -> None:
        """Idle and duplicate commands never create additional captures."""
        await self.bridge._update_source()
        self.client.create_source_capture.assert_not_called()
        for _ in range(2):
            self.bridge._on_server_command(command("start"))
            await self.bridge._update_source()
        self.capture.start.assert_awaited_once()
        self.assertTrue(self.bridge._streaming)
        for _ in range(2):
            self.bridge._on_server_command(command("stop"))
            await self.bridge._update_source()
        self.capture.stop.assert_awaited_once()
        self.assertIsNone(self.bridge._source_capture)

    async def test_stop_during_start(self) -> None:
        """A stop arriving during network I/O cannot leave capture enabled."""
        entered, release = asyncio.Event(), asyncio.Event()

        async def start() -> None:
            entered.set()
            await release.wait()

        self.capture.start.side_effect = start
        self.bridge._on_server_command(command("start"))
        task = asyncio.create_task(self.bridge._update_source())
        await entered.wait()
        self.bridge._on_server_command(command("stop"))
        release.set()
        await task
        self.capture.stop.assert_awaited_once()
        self.assertFalse(self.bridge._streaming)
        self.assertIsNone(self.bridge._source_capture)

    async def test_quick_stop_start_creates_new_capture(self) -> None:
        """A stop is not lost when immediately followed by a start."""
        self.bridge._on_server_command(command("start"))
        await self.bridge._update_source()
        self.bridge._on_server_command(command("stop"))
        self.bridge._on_server_command(command("start"))
        await self.bridge._update_source()
        self.capture.stop.assert_awaited_once()
        self.assertEqual(self.client.create_source_capture.call_count, 2)

    async def test_start_failure_is_cleaned_up(self) -> None:
        """Retain a failed capture only until cleanup can stop it."""
        self.capture.start.side_effect = RuntimeError("start failed")
        self.bridge._on_server_command(command("start"))
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            await self.bridge._update_source()
        await self.bridge._cleanup()
        self.assertFalse(self.bridge._streaming)
        self.assertIsNone(self.bridge._source_capture)
        self.capture.stop.assert_awaited_once()
        self.client.disconnect.assert_awaited_once()

    async def test_stop_failure_still_releases_clients(self) -> None:
        """A failed stop must not skip network or JACK cleanup."""
        self.bridge._on_server_command(command("start"))
        await self.bridge._update_source()
        self.capture.stop.side_effect = RuntimeError("stop failed")
        jack_client = MagicMock()
        self.bridge._jack_client = jack_client
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            await self.bridge._cleanup()
        self.assertFalse(self.bridge._streaming)
        self.assertIsNone(self.bridge._source_capture)
        self.client.disconnect.assert_awaited_once()
        jack_client.close.assert_called_once()

    async def test_disconnect_during_start(self) -> None:
        """A capture bound to a closed connection cannot become active."""
        self.capture.start.side_effect = self.bridge._on_disconnect
        self.bridge._on_server_command(command("start"))
        await self.bridge._update_source()
        self.assertTrue(self.bridge._shutdown_event.is_set())
        self.assertFalse(self.bridge._streaming)
        self.assertIsNone(self.bridge._source_capture)
        self.bridge._on_server_command(command("start"))
        self.assertFalse(self.bridge._source_requested)

    async def test_stereo_feed_preserves_samples_and_timestamp(self) -> None:
        """The consumer interleaves JACK channels into timestamped s16 PCM."""
        audio = MagicMock()
        audio.read_space = 16
        audio.read.side_effect = [
            np.array([0.5, -0.5], dtype=np.float32).tobytes(),
            np.array([0.25, -0.25], dtype=np.float32).tobytes(),
        ]
        timestamps = MagicMock()
        timestamps.read_space = 8
        timestamps.read.return_value = struct.pack(">q", 48000)
        self.bridge._audio_ringbuffer = audio
        self.bridge._ts_ringbuffer = timestamps
        self.capture.feed.side_effect = lambda *_args, **_kwargs: self.bridge._shutdown_event.set()
        self.bridge._on_server_command(command("start"))
        await self.bridge._audio_consumer_loop()
        self.capture.feed.assert_awaited_once_with(
            struct.pack("<hhhh", 16383, 8191, -16383, -8191), capture_timestamp_us=1000000
        )

    async def test_feed_failure_reaches_cleanup(self) -> None:
        """A feed failure terminates run instead of retrying a broken capture."""
        self.bridge._setup_jack = MagicMock()
        self.bridge._setup_sendspin = AsyncMock()
        self.bridge._wait_for_time_sync = AsyncMock()
        self.bridge._audio_consumer_loop = AsyncMock(side_effect=RuntimeError("feed failed"))
        self.bridge._source_capture = self.capture
        with (
            patch("sendspin_jack_bridge.bridge.lock_state"),
            self.assertLogs("sendspin_jack_bridge.bridge", level="ERROR"),
        ):
            await self.bridge.run()
        self.capture.stop.assert_awaited_once()
        self.client.disconnect.assert_awaited_once()

    def test_client_id_warns(self) -> None:
        """The retained compatibility option cannot silently do nothing."""
        with self.assertLogs("sendspin_jack_bridge.bridge", level="WARNING") as logs:
            JackSendspinBridge("ws://localhost/sendspin", client_id="old-id")
        self.assertIn("deprecated and ignored", logs.output[0])

    async def test_sdk_pairing_setup_uses_loop_clock(self) -> None:
        """Construct the real client/store while preventing any network connection."""
        import tempfile  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from aiosendspin.client import SendspinClient  # noqa: PLC0415
        from aiosendspin.clock import LoopClock  # noqa: PLC0415
        from aiosendspin.noise.trust_store import FileClientPairingStore  # noqa: PLC0415

        from sendspin_jack_bridge.state import lock_state  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as directory:
            bridge = JackSendspinBridge("ws://localhost/sendspin", state_dir=Path(directory))
            with lock_state(Path(directory)), patch.object(SendspinClient, "connect", AsyncMock()):
                await bridge._setup_sendspin()
                client = bridge._sendspin_client
                self.assertIsInstance(client, SendspinClient)
                self.assertIsInstance(client.clock, LoopClock)
                self.assertIsInstance(client.pairing_store, FileClientPairingStore)
                self.assertEqual(client.pin_display, bridge._display_pairing_code)
                await bridge._cleanup()

    async def test_real_source_capture_pcm_start_feed_stop(self) -> None:
        """Exercise the actual 9.1.1 PCM encoder and source methods offline."""
        from aiosendspin.client import SourceCapture  # noqa: PLC0415
        from aiosendspin.models.player import SupportedAudioFormat  # noqa: PLC0415
        from aiosendspin.models.types import AudioCodec  # noqa: PLC0415

        connection = MagicMock()
        connection.send_client_stream_start = AsyncMock()
        connection.send_source_chunk = AsyncMock()
        connection.send_client_stream_end = AsyncMock()
        connection.compute_source_timestamp.side_effect = lambda timestamp: timestamp
        capture = SourceCapture(
            self.client,
            connection,
            SupportedAudioFormat(codec=AudioCodec.PCM, channels=2, sample_rate=48000, bit_depth=16),
        )
        for timestamp in (1000000, 2000000):
            await capture.start()
            await capture.feed(bytes(4800), capture_timestamp_us=timestamp)
            await capture.stop()
        self.assertEqual(connection.send_client_stream_start.await_count, 2)
        self.assertEqual(connection.send_client_stream_end.await_count, 2)
        connection.send_source_chunk.assert_any_await(bytes(4800), timestamp_us=1000000)
        connection.send_source_chunk.assert_any_await(bytes(4800), timestamp_us=2000000)

    def prepare_audio(self, frames: list[int]) -> None:
        """Supply complete stereo JACK blocks with chosen frame timestamps."""
        audio, timestamps = MagicMock(), MagicMock()
        audio.read_space = 16
        audio.read.return_value = bytes(8)
        timestamps.read_space = 8
        timestamps.read.side_effect = [struct.pack(">q", frame) for frame in frames]
        self.bridge._audio_ringbuffer = audio
        self.bridge._ts_ringbuffer = timestamps

    async def test_stale_audio_is_discarded_after_start(self) -> None:
        """Never send a previous stream's buffered block to a new capture."""
        self.prepare_audio([48000, 96000])
        self.client.now_us.return_value = 1500000
        self.capture.feed.side_effect = lambda *_args, **_kwargs: self.bridge._shutdown_event.set()
        self.bridge._on_server_command(command("start"))
        await self.bridge._audio_consumer_loop()
        self.capture.feed.assert_awaited_once_with(bytes(8), capture_timestamp_us=2000000)

    async def test_stop_during_feed_is_serialized(self) -> None:
        """A stop command waits for the in-flight feed to finish."""
        self.prepare_audio([48000])

        async def feed(*_args: object, **_kwargs: object) -> None:
            self.bridge._on_server_command(command("stop"))
            await asyncio.sleep(0)
            self.capture.stop.assert_not_awaited()

        self.capture.feed.side_effect = feed
        self.capture.stop.side_effect = self.bridge._shutdown_event.set
        self.bridge._on_server_command(command("start"))
        await self.bridge._audio_consumer_loop()
        self.capture.stop.assert_awaited_once()
        self.assertIsNone(self.bridge._source_capture)

    async def test_actual_feed_exception_exits_consumer(self) -> None:
        """Propagate a feed error to run's cleanup instead of repeated retries."""
        self.prepare_audio([48000])
        self.capture.feed.side_effect = RuntimeError("feed failed")
        self.bridge._on_server_command(command("start"))
        with self.assertRaisesRegex(RuntimeError, "feed failed"):
            await self.bridge._audio_consumer_loop()
        await self.bridge._cleanup()
        self.capture.stop.assert_awaited_once()
