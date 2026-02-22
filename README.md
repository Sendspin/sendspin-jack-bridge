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

Open a terminal and clone the repos:

```
git clone https://github.com/Sendspin/aiosendspin.git
git clone https://github.com/Sendspin/sendspin-jack-bridge.git
```

> **Note:** The `aiosendspin` library needs the source@v1 branch until it is merged to main:
>
> ```
> cd aiosendspin
> git checkout source-v1
> cd ..
> ```

Install both packages (aiosendspin first, then the bridge):

```
pip install ./aiosendspin
pip install ./sendspin-jack-bridge
```

### Step 5: Run the Bridge

With QjackCtl running and the JACK server started:

```
sendspin-jack-bridge --server ws://YOUR_SERVER_IP:8927/ws
```

Replace `YOUR_SERVER_IP` with the IP address of your Sendspin server.

You should see output like:

```
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: Creating JACK client 'sendspin'
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: JACK: sample_rate=48000, blocksize=1024, channels=2
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: JACK client activated
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: Connecting to Sendspin server at ws://192.168.1.100:8927/ws
2026-02-21 12:00:00 INFO     sendspin_jack_bridge.bridge: Connected to Sendspin server
2026-02-21 12:00:01 INFO     sendspin_jack_bridge.bridge: Time synchronization converged
2026-02-21 12:00:01 INFO     sendspin_jack_bridge.bridge: Streaming started: PCM 48000Hz 2ch 16bit
```

### Step 6: Connect Your Audio Source

The bridge registers JACK input ports (`sendspin:input_L` and `sendspin:input_R`). You need to connect an audio source to these ports.

**Option A — Auto-connect on startup:**

```
sendspin-jack-bridge --server ws://YOUR_SERVER_IP:8927/ws --connect "system:capture_*"
```

This automatically connects your system's physical capture ports (microphone, line-in) to the bridge.

**Option B — Connect manually in QjackCtl:**

1. In QjackCtl, click **Graph** (or **Connect**).
2. Find your audio source on the left (e.g., `system` capture ports).
3. Find `sendspin` on the right (input_L, input_R).
4. Draw connections from source to destination by dragging or selecting and clicking **Connect**.

### Step 7: Verify on Players

Once connected, audio should be streaming to the Sendspin server and playing on all connected Sendspin players in your group. Check the server logs or a connected player to confirm audio is being received.

## Command-Line Options

```
sendspin-jack-bridge --help
```

| Option | Default | Description |
|---|---|---|
| `--server URL` | *(required)* | Sendspin server WebSocket URL |
| `--name NAME` | `Sendspin JACK Bridge` | Friendly name shown on the server |
| `--client-id ID` | *(auto-generated)* | Unique client identifier |
| `--jack-name NAME` | `sendspin` | JACK client name |
| `--channels {1,2}` | `2` | Number of audio channels (mono or stereo) |
| `--bit-depth {16,24}` | `16` | PCM bit depth |
| `--connect PATTERN` | *(none)* | Auto-connect to JACK ports matching this pattern |
| `-v, --verbose` | off | Enable debug logging |

## Examples

Stream a turntable connected to a USB audio interface:

```
sendspin-jack-bridge --server ws://192.168.1.100:8927/ws \
  --name "Turntable" \
  --connect "system:capture_*"
```

Stream mono microphone input at 24-bit:

```
sendspin-jack-bridge --server ws://192.168.1.100:8927/ws \
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

**"Failed to connect to Sendspin server"**
- Verify the server URL is correct and the server is running.
- Check that your firewall allows outbound WebSocket connections on the server port.

**Audio is choppy or has dropouts**
- Increase the JACK buffer size (Frames/Period) in QjackCtl Setup.
- Check QjackCtl for xrun warnings — these indicate the audio pipeline can't keep up.
- Close other CPU-intensive applications.

**Bridge starts but no audio reaches players**
- Check QjackCtl Graph to confirm audio connections exist between your source and the `sendspin` input ports.
- Use `--verbose` to see debug output including timestamp calibration and audio chunk sends.

## License

Apache-2.0
