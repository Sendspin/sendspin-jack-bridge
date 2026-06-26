# Sendspin JACK Bridge

Stream audio from [JACK Audio Connection Kit](https://jackaudio.org/) to a [Sendspin](https://github.com/Sendspin) server. Any JACK-connected audio source (turntable, microphone, line-in, software synth) can be distributed via Sendspin to synchronized players on your network.

This bridge acts as a Sendspin `source@v1` client — it captures audio, timestamps it, and streams it over WebSocket to the server, which then distributes it to all connected players in sync.

## Prerequisites

- Python 3.12 or later
- JACK Audio Connection Kit
- A running Sendspin server

## Windows Setup

Three PowerShell scripts in [`scripts/`](scripts/) automate the command-line
parts of setup. First complete the GUI prerequisites below (these can't be
scripted reliably), then use the scripts.

### Prerequisites (install these by hand first)

1. **Install Python 3.12+** from [python.org](https://www.python.org/downloads/).
   During installation, **check "Add Python to PATH"**. Verify with
   `python --version`.

2. **Install JACK Audio.** Download the **JACK2 64-bit installer** from the
   [JACK downloads page](https://jackaudio.org/downloads/) and choose
   **"Full installation (with JACK-Router)"** — this installs the JACK server
   (`jackd`), the JACK library DLLs (needed by the Python bridge), QjackCtl,
   and JACK-Router. **Reboot** afterwards so the JACK DLLs are on your PATH.

3. **Start the JACK server.** Launch **QjackCtl**, click **Setup** to choose
   your **Interface** (audio device), **Sample Rate**, and **Frames/Period**
   (1024 is a good starting point), click **OK**, then click **Start**. The
   status should change to "Started".

### Quick start with the scripts

From the repository root in **PowerShell**:

```powershell
# 1. One-time install: checks prerequisites, clones aiosendspin (source-v1),
#    and installs aiosendspin + this bridge with pip.
.\scripts\install.ps1

# 2. Start a local Sendspin server (leave this terminal open).
.\scripts\start-server.ps1

# 3. In a separate terminal, launch the bridge and auto-connect capture ports.
.\scripts\run-bridge.ps1 -Connect "system:capture_*"
```

Each script supports `-?` for full help on its parameters:

- **`install.ps1`** — one-time setup. Clones `aiosendspin` as a sibling folder
  next to this repo, then installs both packages. Safe to re-run.
- **`start-server.ps1`** — starts the Sendspin server. Defaults to
  `-Port 8927 -ServerId home -ServerName Home`.
- **`run-bridge.ps1`** — launches the bridge. Defaults to
  `-Server ws://localhost:8927/sendspin`; pass `-Connect "system:capture_*"`
  to auto-connect your physical capture ports, or omit it to wire ports up
  manually in QjackCtl's **Graph** (connect `system` capture ports to the
  `sendspin` input ports). For other options (e.g. `--name`, `--channels`,
  `--verbose`), run `sendspin-jack-bridge` directly — see
  [Command-Line Options](#command-line-options) and [Examples](#examples).

If the server runs on another machine, point the bridge at it:
`.\scripts\run-bridge.ps1 -Server ws://YOUR_SERVER_IP:8927/sendspin`.

Once connected, audio streams to the Sendspin server and plays on all connected
players in your group. Check the server logs or a player to confirm.

### Manual setup (without the scripts)

If you'd rather run the commands yourself, the scripts wrap these steps. From a
folder that will **contain** both repos:

```powershell
# Clone aiosendspin (source-v1 branch) next to this repo.
git clone https://github.com/Sendspin/aiosendspin.git
cd aiosendspin; git checkout source-v1; cd ..

# Install aiosendspin first, then the bridge.
pip install ./aiosendspin
pip install ./sendspin-jack-bridge
```

> **Tip:** Run `pip install` from the directory that **contains** these folders,
> not from inside them.

Start the Sendspin server in a separate terminal:

```
python -c "import asyncio; from aiosendspin.server.server import SendspinServer; loop = asyncio.new_event_loop(); server = SendspinServer(loop=loop, server_id='home', server_name='Home'); loop.run_until_complete(server.start_server(port=8927)); print('Sendspin server running on port 8927 — press Ctrl+C to stop'); loop.run_forever()"
```

Then run the bridge (use `localhost` if the server is on the same machine):

```
sendspin-jack-bridge --server ws://YOUR_SERVER_IP:8927/sendspin --connect "system:capture_*"
```

The bridge registers JACK input ports (`sendspin:input_L`, `sendspin:input_R`).
Without `--connect`, connect your audio source to them manually in QjackCtl's
**Graph**.

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
- Use `--verbose` to see debug output including timestamp calibration and audio chunk sends.

## License

Apache-2.0
