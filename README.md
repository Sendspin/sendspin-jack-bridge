# Sendspin JACK Bridge

Stream audio from [JACK Audio Connection Kit](https://jackaudio.org/) to a [Sendspin](https://github.com/Sendspin) server. Any JACK-connected audio source (turntable, microphone, line-in, software synth) can be distributed via Sendspin to synchronized players on your network.

This bridge acts as a Sendspin `source@v1` client — it captures audio, timestamps it, and streams it over WebSocket to the server, which then distributes it to all connected players in sync.

## Prerequisites

- Python 3.12 or later
- JACK Audio Connection Kit
- A running Sendspin server

## Windows Setup (Step by Step)

### Step 1: Install Python

Download and install Python 3.12+ from [python.org](https://www.python.org/downloads/).

During installation, **check "Add Python to PATH"**.

Verify it works by opening a terminal (PowerShell or Command Prompt):

```
python --version
```

### Step 2: Install JACK Audio

1. Download the **JACK2 64-bit installer** from the [JACK downloads page](https://jackaudio.org/downloads/) (the GitHub releases link for "JACK 1.9.22 win64").

2. Run the installer. When prompted, select **"Full installation (with JACK-Router)"**. This installs:
   - The JACK server (`jackd`)
   - The JACK library DLLs (needed by the Python bridge)
   - QjackCtl (graphical control panel)
   - JACK-Router (virtual ASIO driver for routing audio between apps)

3. **Reboot** after installation to ensure the JACK DLLs are on your system PATH.

### Step 3: Start the JACK Server

1. Launch **QjackCtl** from the Windows Start menu.

2. Click **Setup** and configure:
   - **Interface**: Select your audio device (soundcard, USB interface, etc.)
   - **Sample Rate**: Choose your preferred rate (44100, 48000, etc.)
   - **Frames/Period**: Start with 1024 (lower = less latency but more CPU)

3. Click **OK**, then click **Start** to launch the JACK server.

   You should see the server status change to "Started" with your sample rate displayed.

### Step 4: Install the Bridge

Clone and install the bridge; pip installs a compatible released aiosendspin automatically:

```
git clone https://github.com/Sendspin/sendspin-jack-bridge.git
python -m pip install ./sendspin-jack-bridge
```

The bridge requires `aiosendspin>=9.1.1,<10`. Music Assistant 2.10.2 uses
aiosendspin 9.1.1. To reproduce that exact combination, install with:

```
python -m pip install ./sendspin-jack-bridge "aiosendspin==9.1.1"
```

A separate aiosendspin checkout or the old `source-v1` branch is no longer needed.
For development, run `uv sync --locked` inside the bridge repository.

### Step 5: Prepare the Sendspin Server

Start a compatible Sendspin server, such as Music Assistant 2.10.2, and enable
its Sendspin provider. Use its WebSocket URL in the next step. For Music Assistant,
the default URL is `ws://YOUR_SERVER_IP:8927/sendspin`.

### Step 6: Run the Bridge

With QjackCtl running, the JACK server started, and the Sendspin server running:

```
sendspin-jack-bridge --server ws://YOUR_SERVER_IP:8927/sendspin
```

Replace `YOUR_SERVER_IP` with the IP address of the machine running the Sendspin server (use `localhost` if it's the same machine).

Pair the source in your server's interface. During pairing, the bridge logs a code
to enter on the server. Once paired and synchronized, it waits for the server to
request source playback; connecting JACK ports alone does not start streaming.

After selecting this source for playback, you should see output like:

```
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: Creating JACK client 'sendspin'
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: JACK: sample_rate=48000, blocksize=1024, channels=2
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: JACK client activated
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: Connecting to Sendspin server at ws://localhost:8927/sendspin
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: Connected to Sendspin server
2026-02-21 12:00:01 INFO     sendspin_jack_bridge.bridge: Time synchronization converged
2026-02-21 12:00:01 INFO     sendspin_jack_bridge.bridge: Streaming started: PCM 48000Hz 2ch 16bit
```

### Step 7: Connect Your Audio Source

The bridge registers JACK input ports (`sendspin:input_L` and `sendspin:input_R`). You need to connect an audio source to these ports.

**Option A — Auto-connect on startup:**

```
sendspin-jack-bridge --server ws://YOUR_SERVER_IP:8927/sendspin --connect "system:capture_*"
```

This automatically connects your system's physical capture ports (microphone, line-in) to the bridge.

**Option B — Connect manually in QjackCtl:**

1. In QjackCtl, click **Graph** (or **Connect**).
2. Find your audio source on the left (e.g., `system` capture ports).
3. Find `sendspin` on the right (input_L, input_R).
4. Draw connections from source to destination by dragging or selecting and clicking **Connect**.

### Step 8: Verify on Players

Select this source and start playback on the desired player or group in your server. The server sends source start and stop commands to the bridge. Confirm audio on a selected player.

## Command-Line Options

```
sendspin-jack-bridge --help
```

| Option | Default | Description |
|---|---|---|
| `--server URL` | *(required)* | Sendspin server WebSocket URL |
| `--name NAME` | `Sendspin JACK Bridge` | Friendly name shown on the server |
| `--client-id ID` | *(none)* | Deprecated; logs a warning and is ignored |
| `--state-dir PATH` | `~/.config/sendspin-jack-bridge` | Persistent identity and pairing state; separate directory per instance |
| `--jack-name NAME` | `sendspin` | JACK client name |
| `--channels {1,2}` | `2` | Number of audio channels (mono or stereo) |
| `--bit-depth {16,24}` | `16` | PCM bit depth |
| `--connect PATTERN` | *(none)* | Auto-connect to JACK ports matching this pattern |
| `-v, --verbose` | off | Enable debug logging |

## Identity and Pairing

The bridge stores its identity in `identity.key` and trusted pairings in
`pairings.json` under `--state-dir`. The default is the user's home directory
followed by `.config/sendspin-jack-bridge` on Linux, macOS, and Windows. This
preserves existing installations; it does not follow XDG or Windows AppData
overrides. Use `--state-dir` to choose another location.

The cryptographic identity determines the client ID. The old `--client-id` option
is accepted with a deprecation warning, but cannot override that identity. For
multiple sources, give each bridge its own state directory and JACK client name.
Only one bridge process may use a state directory at a time. The `bridge.lock`
file may remain after exit; do not delete it while a bridge is running.

Identity creation is atomic. New identity files are owner-only on POSIX; on
Windows, protect the directory with your user account's filesystem ACLs. Keep
identity and pairing files private and together when backing up or moving a
source. An empty or corrupt identity causes startup to fail rather than silently
creating a new client. Restore it from a trusted backup to preserve pairings.

On disconnect or a capture error the bridge exits and releases JACK resources.
It does not automatically reconnect; start it again to reconnect using the same
identity and pairings. Signal detection and automatic playback when audio appears
are not implemented.

## Examples

Stream a turntable connected to a USB audio interface:

```
sendspin-jack-bridge --server ws://192.168.1.100:8927/sendspin \
  --name "Turntable" \
  --connect "system:capture_*"
```

Stream mono microphone input at 24-bit:

```
sendspin-jack-bridge --server ws://192.168.1.100:8927/sendspin \
  --name "Microphone" \
  --channels 1 \
  --bit-depth 24 \
  --connect "system:capture_1"
```

## Troubleshooting

**"No JACK ports matching '...' found"**
- Make sure the JACK server is running (check QjackCtl).
- Verify your audio device is selected in QjackCtl Setup.
- Check available ports: in QjackCtl, click **Graph** to see all registered ports.

**"Could not connect to Sendspin server"**
- Verify the Sendspin server is running (Step 5) and the URL is correct.
- Make sure the URL path ends with `/sendspin` (e.g., `ws://localhost:8927/sendspin`).
- Check that your firewall allows WebSocket connections on port 8927.

**Audio is choppy or has dropouts**
- Increase the JACK buffer size (Frames/Period) in QjackCtl Setup.
- Check QjackCtl for xrun warnings — these indicate the audio pipeline can't keep up.
- Close other CPU-intensive applications.

**Bridge starts but no audio reaches players**
- Check QjackCtl Graph to confirm audio connections exist between your source and the `sendspin` input ports.
- Confirm that pairing completed and the source is selected for playback on the server.
- Use `--verbose` to see debug output including timestamp calibration.

## License

Apache-2.0
