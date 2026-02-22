"""JACK Audio to Sendspin source bridge.

Captures audio from JACK Audio and streams it to a Sendspin server
as a source@v1 client. Any JACK-connected audio source (turntable,
microphone, line-in, software synth) can be distributed via Sendspin
to synchronized players.

Usage:
    sendspin-jack-bridge --server ws://192.168.1.100:8927/ws
    python -m sendspin_jack_bridge --server ws://192.168.1.100:8927/ws
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import struct
import time
import uuid

import jack
import numpy as np
from aiosendspin.client import SendspinClient
from aiosendspin.models.source import (
    ClientHelloSourceSupport,
    InputStreamStartSource,
    SourceCommandPayload,
    SourceFormat,
    SourceStatePayload,
)
from aiosendspin.models.types import (
    AudioCodec,
    Roles,
    SourceCommand,
    SourceStateType,
)

logger = logging.getLogger(__name__)

# How many seconds of audio the ringbuffer can hold before overrun
RINGBUFFER_SECONDS = 0.5

# How often the async consumer polls the ringbuffer (seconds)
POLL_INTERVAL = 0.005

# How often to recalibrate the JACK frame-time to loop-time offset (seconds)
RECALIBRATE_INTERVAL = 10.0


class JackSendspinBridge:
    """Bridges JACK audio capture to a Sendspin source client."""

    def __init__(  # noqa: D107
        self,
        server_url: str,
        client_name: str = "Sendspin JACK Bridge",
        client_id: str | None = None,
        jack_name: str = "sendspin",
        channels: int = 2,
        bit_depth: int = 16,
        connect_pattern: str | None = None,
    ) -> None:
        self._server_url = server_url
        self._client_name = client_name
        self._client_id = client_id or f"jack-bridge-{uuid.uuid4().hex[:8]}"
        self._jack_name = jack_name
        self._channels = channels
        self._bit_depth = bit_depth
        self._connect_pattern = connect_pattern

        self._shutdown_event = asyncio.Event()
        self._streaming = False

        # Populated during setup
        self._jack_client: jack.Client | None = None
        self._sendspin_client: SendspinClient | None = None
        self._audio_ringbuffer: jack.RingBuffer | None = None
        self._ts_ringbuffer: jack.RingBuffer | None = None
        self._sample_rate: int = 0
        self._blocksize: int = 0

        # JACK frame time to asyncio loop time offset
        self._jack_epoch_offset_us: float = 0.0

    async def run(self) -> None:
        """Set up JACK + Sendspin and stream until shutdown."""
        loop = asyncio.get_running_loop()

        # Install signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        try:
            self._setup_jack()
            await self._setup_sendspin()
            await self._wait_for_time_sync()
            await self._start_streaming()
            await self._audio_consumer_loop()
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup()

    def _setup_jack(self) -> None:
        """Create JACK client, register ports, set up ringbuffers."""
        logger.info("Creating JACK client '%s'", self._jack_name)
        self._jack_client = jack.Client(self._jack_name)

        self._sample_rate = self._jack_client.samplerate
        self._blocksize = self._jack_client.blocksize
        logger.info(
            "JACK: sample_rate=%d, blocksize=%d, channels=%d",
            self._sample_rate,
            self._blocksize,
            self._channels,
        )

        # Register input ports
        port_names = ["input_L", "input_R"] if self._channels == 2 else ["input_mono"]
        for name in port_names[: self._channels]:
            self._jack_client.inports.register(name)

        # Audio ringbuffer: float32, sized for RINGBUFFER_SECONDS of audio
        # Each port writes separately, so total size = seconds * samplerate * channels * 4 bytes
        audio_buf_size = int(RINGBUFFER_SECONDS * self._sample_rate * self._channels * 4)
        self._audio_ringbuffer = jack.RingBuffer(audio_buf_size)

        # Timestamp ringbuffer: one int64 (8 bytes) per JACK block
        max_blocks = int(RINGBUFFER_SECONDS * self._sample_rate / self._blocksize) + 16
        self._ts_ringbuffer = jack.RingBuffer(max_blocks * 8)

        # Set the process callback
        @self._jack_client.set_process_callback  # type: ignore[untyped-decorator]
        def process(frames: int) -> None:
            self._jack_process(frames)

        @self._jack_client.set_shutdown_callback  # type: ignore[untyped-decorator]
        def shutdown(status: jack.Status, reason: str) -> None:
            logger.warning("JACK shut down: %s (status=%s)", reason, status)
            self._shutdown_event.set()

        # Activate the JACK client
        self._jack_client.activate()
        logger.info("JACK client activated")

        # Calibrate JACK frame time to loop time
        self._calibrate_time_offset()

        # Auto-connect to ports if pattern specified
        if self._connect_pattern:
            self._auto_connect()

    def _jack_process(self, _frames: int) -> None:
        """Write audio + timestamp to ringbuffers (JACK real-time callback)."""
        assert self._audio_ringbuffer is not None
        assert self._ts_ringbuffer is not None
        assert self._jack_client is not None

        if not self._streaming:
            return

        # Write each port's float32 buffer into the audio ringbuffer
        for port in self._jack_client.inports:
            buf = port.get_buffer()
            if self._audio_ringbuffer.write_space >= len(buf):
                self._audio_ringbuffer.write(buf)
            else:
                # Buffer overrun — drop this block
                logger.debug("Audio ringbuffer overrun, dropping block")
                return

        # Store the JACK frame timestamp for this block
        frame_time = self._jack_client.last_frame_time
        ts_bytes = struct.pack(">q", frame_time)
        if self._ts_ringbuffer.write_space >= 8:
            self._ts_ringbuffer.write(ts_bytes)

    def _calibrate_time_offset(self) -> None:
        """Establish mapping between JACK frame time and asyncio loop time."""
        assert self._jack_client is not None
        loop = asyncio.get_running_loop()

        # Sample both clocks as close together as possible
        jack_frames = self._jack_client.frame_time
        loop_time_us = int(loop.time() * 1_000_000)

        # JACK frame time in microseconds
        jack_time_us = int(jack_frames / self._sample_rate * 1_000_000)

        # offset such that: loop_time_us = jack_time_us + offset
        self._jack_epoch_offset_us = loop_time_us - jack_time_us
        logger.debug(
            "Calibrated JACK time offset: %+d us (jack_frames=%d, loop_time=%d us)",
            self._jack_epoch_offset_us,
            jack_frames,
            loop_time_us,
        )

    def _jack_frame_to_loop_us(self, jack_frame_time: int) -> int:
        """Convert a JACK frame timestamp to asyncio loop time in microseconds."""
        jack_time_us = int(jack_frame_time / self._sample_rate * 1_000_000)
        return int(jack_time_us + self._jack_epoch_offset_us)

    def _auto_connect(self) -> None:
        """Auto-connect JACK input ports to physical capture ports."""
        assert self._jack_client is not None
        assert self._connect_pattern is not None

        capture_ports = self._jack_client.get_ports(
            self._connect_pattern, is_output=True, is_audio=True
        )
        if not capture_ports:
            logger.warning("No JACK ports matching '%s' found", self._connect_pattern)
            return

        for src, dest in zip(capture_ports, self._jack_client.inports, strict=False):
            try:
                self._jack_client.connect(src, dest)
                logger.info("Connected %s -> %s", src.name, dest.name)
            except jack.JackError as exc:
                logger.warning("Failed to connect %s -> %s: %s", src.name, dest.name, exc)

    async def _setup_sendspin(self) -> None:
        """Create and connect the Sendspin source client."""
        source_format = SourceFormat(
            codec=AudioCodec.PCM,
            channels=self._channels,
            sample_rate=self._sample_rate,
            bit_depth=self._bit_depth,
        )

        self._sendspin_client = SendspinClient(
            client_id=self._client_id,
            client_name=self._client_name,
            roles=[Roles.SOURCE],
            source_support=ClientHelloSourceSupport(
                supported_formats=[source_format],
            ),
        )

        # Listen for server source commands (start/stop)
        self._sendspin_client.add_source_command_listener(self._on_source_command)

        logger.info("Connecting to Sendspin server at %s", self._server_url)
        await self._sendspin_client.connect(self._server_url)
        logger.info("Connected to Sendspin server")

    async def _wait_for_time_sync(self) -> None:
        """Wait for the Sendspin time synchronization to converge."""
        assert self._sendspin_client is not None
        logger.info("Waiting for time synchronization...")

        while not self._shutdown_event.is_set():
            if self._sendspin_client.is_time_synchronized():
                logger.info("Time synchronization converged")
                return
            await asyncio.sleep(0.1)

    async def _start_streaming(self) -> None:
        """Send input_stream/start and begin capturing audio."""
        assert self._sendspin_client is not None

        stream_format = InputStreamStartSource(
            codec=AudioCodec.PCM,
            channels=self._channels,
            sample_rate=self._sample_rate,
            bit_depth=self._bit_depth,
        )
        await self._sendspin_client.send_input_stream_start(stream_format)
        await self._sendspin_client.send_source_state(
            state=SourceStatePayload(state=SourceStateType.STREAMING)
        )

        self._streaming = True
        logger.info(
            "Streaming started: PCM %dHz %dch %dbit",
            self._sample_rate,
            self._channels,
            self._bit_depth,
        )

    async def _stop_streaming(self) -> None:
        """Stop streaming and send input_stream/end."""
        if not self._streaming:
            return

        self._streaming = False

        if self._sendspin_client and self._sendspin_client.connected:
            await self._sendspin_client.send_input_stream_end()
            await self._sendspin_client.send_source_state(
                state=SourceStatePayload(state=SourceStateType.IDLE)
            )
        logger.info("Streaming stopped")

    def _on_source_command(self, payload: SourceCommandPayload) -> None:
        """Handle server source commands (start/stop)."""
        if payload.command == SourceCommand.START:
            logger.info("Server requested start")
            asyncio.get_running_loop().create_task(self._start_streaming())
        elif payload.command == SourceCommand.STOP:
            logger.info("Server requested stop")
            asyncio.get_running_loop().create_task(self._stop_streaming())

    async def _audio_consumer_loop(self) -> None:
        """Async loop that reads audio from JACK ringbuffer and sends to Sendspin."""
        assert self._audio_ringbuffer is not None
        assert self._ts_ringbuffer is not None
        assert self._sendspin_client is not None

        bytes_per_sample = 4  # float32
        block_audio_bytes = self._blocksize * self._channels * bytes_per_sample
        last_recalibrate = time.monotonic()

        while not self._shutdown_event.is_set():
            # Periodically recalibrate JACK frame-time to loop-time offset
            now = time.monotonic()
            if now - last_recalibrate > RECALIBRATE_INTERVAL:
                self._calibrate_time_offset()
                last_recalibrate = now

            # Check if we have a full block of audio + its timestamp
            audio_available = self._audio_ringbuffer.read_space
            ts_available = self._ts_ringbuffer.read_space

            if audio_available < block_audio_bytes or ts_available < 8:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Read timestamp for this block
            ts_bytes = self._ts_ringbuffer.read(8)
            jack_frame_time = struct.unpack(">q", ts_bytes)[0]

            # Read per-channel float32 audio and interleave
            channel_buffers: list[np.ndarray] = []
            per_channel_bytes = self._blocksize * bytes_per_sample
            for _ in range(self._channels):
                raw = self._audio_ringbuffer.read(per_channel_bytes)
                channel_buffers.append(np.frombuffer(raw, dtype=np.float32))

            # Interleave per-channel buffers into a single array
            if self._channels == 1:
                interleaved = channel_buffers[0]
            else:
                interleaved = np.column_stack(channel_buffers).ravel()

            # Convert float32 [-1.0, 1.0] to PCM bytes
            pcm_bytes = self._float32_to_pcm(interleaved)

            # Convert JACK frame time to asyncio loop time (microseconds)
            capture_timestamp_us = self._jack_frame_to_loop_us(jack_frame_time)

            # Send to Sendspin
            try:
                await self._sendspin_client.send_source_audio_chunk(
                    pcm_bytes, capture_timestamp_us=capture_timestamp_us
                )
            except Exception:
                logger.exception("Failed to send audio chunk")
                await asyncio.sleep(0.1)

    def _float32_to_pcm(self, samples: np.ndarray) -> bytes:
        """Convert float32 audio samples to PCM bytes."""
        if self._bit_depth == 16:
            pcm = (samples * 32767).clip(-32768, 32767).astype(np.int16)
            return pcm.tobytes()
        if self._bit_depth == 24:
            # 24-bit PCM: little-endian, 3 bytes per sample
            pcm32 = (samples * 8388607).clip(-8388608, 8388607).astype(np.int32)
            # Pack each int32 as 3 little-endian bytes
            raw = pcm32.tobytes()
            # int32 is 4 bytes LE: [b0, b1, b2, b3] — take first 3 for 24-bit
            out = bytearray(len(pcm32) * 3)
            for i in range(len(pcm32)):
                out[i * 3 : i * 3 + 3] = raw[i * 4 : i * 4 + 3]
            return bytes(out)
        raise ValueError(f"Unsupported bit depth: {self._bit_depth}")

    async def _cleanup(self) -> None:
        """Graceful shutdown of JACK and Sendspin."""
        logger.info("Shutting down...")

        await self._stop_streaming()

        if self._sendspin_client and self._sendspin_client.connected:
            await self._sendspin_client.disconnect()
            logger.info("Disconnected from Sendspin server")

        if self._jack_client:
            self._jack_client.deactivate()
            self._jack_client.close()
            logger.info("JACK client closed")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="JACK Audio to Sendspin source bridge",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--server",
        required=True,
        help="Sendspin server WebSocket URL (e.g., ws://192.168.1.100:8927/ws)",
    )
    parser.add_argument(
        "--name",
        default="Sendspin JACK Bridge",
        help="Friendly name for this source client",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Unique client ID (default: auto-generated)",
    )
    parser.add_argument(
        "--jack-name",
        default="sendspin",
        help="JACK client name",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=2,
        choices=[1, 2],
        help="Number of audio channels",
    )
    parser.add_argument(
        "--bit-depth",
        type=int,
        default=16,
        choices=[16, 24],
        help="PCM bit depth",
    )
    parser.add_argument(
        "--connect",
        default=None,
        metavar="PATTERN",
        help="Auto-connect to JACK ports matching this pattern (e.g., 'system:capture_*')",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    bridge = JackSendspinBridge(
        server_url=args.server,
        client_name=args.name,
        client_id=args.client_id,
        jack_name=args.jack_name,
        channels=args.channels,
        bit_depth=args.bit_depth,
        connect_pattern=args.connect,
    )

    asyncio.run(bridge.run())
