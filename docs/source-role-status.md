# `source@v1` dependency status & revival plan

**Status:** the documented install path for this bridge is broken. This bridge
depends on a Sendspin **`source@v1`** role that does **not** exist in upstream
`aiosendspin`, and the branch the README told you to check out has been deleted.
A fresh `git clone` + `git checkout source-v1` + `pip install` therefore fails
today. The bridge's own code is not the blocker.

This document records the facts, where the missing code still survives, and the
options for reviving it. It is **research only** — it changes no dependency pins
and attempts no live run. Choosing and applying a real fix is a follow-up task.

_Last verified: 2026-06-26._

## What the bridge depends on

`sendspin_jack_bridge/bridge.py` imports the entire `source@v1` surface from
`aiosendspin` (lines 27–40):

```python
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
```

Beyond the symbols above, the bridge calls these `SendspinClient` methods that
only exist in the source implementation:

- `connect`
- `is_time_synchronized`
- `send_input_stream_start`
- `send_input_stream_end`
- `send_source_state`
- `send_source_audio_chunk`
- `add_source_command_listener`

It also relies on `Roles.SOURCE == "source@v1"`. If any of the above is missing
from the installed `aiosendspin`, the bridge fails to import or run.

## Why it's broken: upstream has no source role

Verified against upstream `Sendspin/aiosendspin` and the Sendspin spec on
2026-06-26:

- **`main` has no `source.py`** and no source role. Only the
  player / controller / metadata / artwork / visualizer / color roles exist.
- **The `source-v1` branch the README points to is deleted.** `git checkout
  source-v1` now 404s, so the README's documented install step is broken for
  everyone — not just on this machine.
- **The Sendspin spec defines no source role.** The roles it ratifies are
  player / controller / metadata / artwork / visualizer / color. The proposal to
  add one — **`Sendspin/spec#14` ("Add a Source Role…")** — is **open and not
  ratified**.

In short: `source@v1` was an experimental role that was never merged upstream and
has since been removed from public GitHub.

## Where the source code still survives (local only)

The complete `source@v1` implementation still exists in a **local clone** —
nowhere public:

- **Clone:** `C:\CodeProjects\aiosendspin`
- **Branch:** `feature/jack-source-bridge`
- **Tip:** `a8e646d` (2026-02-21) — a merge of `rudy/source-v1-reference-impl`
  into `feature/jack-source-bridge`

This branch contains everything the bridge imports:

- `aiosendspin/models/source.py` with every class listed above
- `Roles.SOURCE` plus `SourceCommand` / `SourceStateType` in `models/types.py`
- the `SendspinClient` source send/listener methods

Provenance and staleness (verified with `git` against the clone):

- The source role was added in commit **`96a6b50`**
  (`feat(source): implement source@v1 role and input stream protocol`).
- `feature/jack-source-bridge` **fully contains** `rudy/source-v1-reference-impl`
  (it is an ancestor — `git merge-base --is-ancestor` exits 0).
- The branch forked from an older `main` (~Feb 2026) and was never rebased
  forward: it is **55 commits behind current upstream `main`**
  (`git rev-list --count feature/jack-source-bridge..origin/main` → `55`).

> ⚠️ This code lives only in a local working copy. It is not pushed anywhere
> durable. Treat preserving it (push to a fork you control) as a prerequisite for
> any of the revival options below.

## Revival options

### A. Pin to the surviving source branch _(fastest)_

Point the install at `feature/jack-source-bridge` and reinstall:

- Push `feature/jack-source-bridge` to a git remote you control (a fork), then
  set this repo's `aiosendspin` source to that branch — either via
  `pyproject.toml` `[tool.uv.sources]` (currently an editable local path,
  `../aiosendspin`) or a `git`/URL pin — and fix the README's install step to
  match.
- Reinstall and run. The bridge code very likely needs **no** change, because
  this is the exact API it was written against.

**Tradeoff:** fastest path to a working end-to-end run, but you're pinned to a
branch that is ~4 months / 55 commits behind upstream `main`. You inherit none of
upstream's later fixes, and the gap only grows.

### B. Rebase `source@v1` onto current `main` _(durable)_

Carry the source work forward onto today's `aiosendspin` `main`:

- Replay the source commits (the role addition `96a6b50` and the rest of the
  source work in `feature/jack-source-bridge`) onto current upstream `main`,
  resolving conflicts from the 55 intervening commits.
- Publish the rebased branch and pin to it.

**Tradeoff:** more work up front (a real rebase across 55 commits, with
conflicts likely), but the result rides current upstream and stays maintainable
until/unless upstream ships its own source role.

### C. Wait for / drive upstream adoption _(strategic)_

Track **`Sendspin/spec#14`**. If an official source role is ratified and lands in
`aiosendspin`, port the bridge to it.

**Tradeoff:** lowest maintenance and the only path that ends in a *supported*
dependency — but it's blocked on an unratified spec proposal with no timeline,
and the official API may differ from this experimental one, so a port (not a
drop-in) should be expected.

## Recommended next step

**Start with A to confirm the bridge still works end-to-end**, then move to **B**
for a durable dependency. A is the cheapest way to verify nothing else is broken
(the bridge code was written against exactly this API); once that's confirmed, B
keeps the role current instead of frozen 55 commits in the past. C is the
long-term resolution but can't be acted on until spec #14 moves.

Whichever path: **first push `feature/jack-source-bridge` to a remote you
control** so the only surviving copy of `source@v1` isn't a single local clone.
