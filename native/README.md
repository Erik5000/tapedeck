# TAPEDECK — native macOS app

SwiftUI + WKWebView shell for the tapedeck dashboard. Opening it starts the
local server; quitting it stops the server it started — and only that one.

The shell follows the convention in `trading-prep/native/` and
`fundamental-terminals/native/`. Divergences are listed at the bottom.

## Build & install

```bash
cd native
make install
```

Regenerates `Tapedeck.xcodeproj` from `project.yml`, builds Release, copies
`TAPEDECK.app` into `~/Applications/`, ad-hoc signs it, and prints the repo
path it baked — then reads it back out of the installed bundle. First-time
setup needs:

- Xcode (full Xcode.app, not just the Command Line Tools — `xcodebuild`)
- `brew install xcodegen librsvg`

There is no Swift test target and no CI here. Everything under "What the app
does" is verified by hand; the Python side it drives is covered by `pytest`.

## Targets

- `make project` — regenerate `Tapedeck.xcodeproj` from `project.yml`
- `make build`   — produce `build/Build/Products/Release/TAPEDECK.app`
- `make install` — install into `~/Applications/`
- `make icon`    — regenerate the app icon from `icon/icon.svg`
- `make venv`    — create the repo's `.venv` (the app refuses to boot without it)
- `make check`   — assert the interpreter exists and `tapedeck.server` imports
- `make clean`   — remove `build/`

`make build` depends on `check`, so a bundle that could never start its server
fails the build instead of failing at launch.

## What the app does

1. Preflight: the repo must contain `tapedeck.py`, and `.venv/bin/python3` must
   exist. Either missing gets a named error with a copy-pasteable fix, rather
   than a health timeout 15 seconds later with nothing to go on.

2. If something already answers `http://127.0.0.1:7360/api/health` **for this
   same repo**, it is **adopted**: no second server is spawned, and quitting the
   app leaves it running. That is the `tapedeck.py --serve` case.

3. Otherwise it spawns

   ```
   <repo>/.venv/bin/python3 -m tapedeck.server --host 127.0.0.1 \
       --port 7360 --parent-pid <app pid>
   ```

   with `PATH` widened (a GUI app inherits launchd's minimal PATH) and
   `PYTHONUNBUFFERED=1` — without the latter the run's progress lines only
   arrive when it finishes, and the live status line stays empty for the whole
   run. stdout and stderr go to `/tmp/tapedeck-server.log` and `.err`, rotated
   to `.1` at 5 MiB on spawn. Nothing else bounds those files.

4. It polls `/api/health` every 500 ms for up to 15 s, then loads
   `http://127.0.0.1:7360/` in a `WKWebView`. If the child exits early it says
   so immediately instead of waiting out the timeout, and the error view shows
   the tail of stderr with Retry / Copy command / Open log / Reveal repo.

`⌘R` reloads, `⇧⌘R` reloads ignoring cache (the app shell JS is cached, so a
plain reload can keep serving an old one after an edit), `⌥⌘R` restarts the
server.

## Stopping the server

Two independent paths, because the clean one doesn't cover every exit:

| How the app ends | What stops the server |
|---|---|
| ⌘Q, ⌘W, red button | `applicationWillTerminate` → SIGTERM, SIGKILL after 4 s |
| Log out / shut down | SIGTERM handler → `NSApp.terminate` → as above |
| Force-quit, `kill -9`, crash | the server's own kqueue watchdog on `--parent-pid` |

The watchdog is the reason `--parent-pid` exists. `applicationWillTerminate`
never runs on a force-quit, so without it the server would be left listening
with no window. Measured: gone ~1 s after the app is killed.

The server's own SIGTERM handler terminates any **running job** before exiting,
so quitting mid-scan doesn't leave an 8-minute VWAP fetch running headless.

`Window`, not `WindowGroup`: one window, so ⌘W and ⌘Q mean the same thing.
With a `WindowGroup` the user could close the last window and leave the app —
and its server — running with no window to quit from.

## Adopt, don't reclaim

`trading-prep`'s app kills whatever holds its port so every launch runs current
code. This app does not. A server on 7360 that reports this repo is adopted and
left alone on quit, because it is very likely a `--serve` you started yourself,
possibly with a scan in flight.

The cost is accepted: the app cannot guarantee a fresh code load. `⌥⌘R` or
stopping the CLI server is the deliberate way to force a restart.

Ownership is mechanical, not inferred: `ServerProcessBox` only holds a `Process`
for a child the app spawned, and `shutdown()` returns early when there isn't
one. There is no handle to terminate for an adopted server.

## Divergences from trading-prep's shell

- **`--parent-pid` watchdog** (from `fundamental-terminals`) — trading-prep has
  no in-process parent watch and leaks its server on force-quit.
- **Adopt instead of reclaim** — trading-prep kills whatever holds `:5050`.
- **`make check`** — refuses to build a bundle whose backend can't import.
- **Preflight with copy-pasteable fixes** — trading-prep reports whatever error
  the launcher returns; a missing venv isn't diagnosed specially.
- **No launcher shell script** — the app runs the Python module directly, so
  the spawned PID *is* the server and there's no wrapper to reap.
