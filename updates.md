# Updates

Summary of changes made to the `docker/` Caldera-for-OT lab setup, organized by topic.

## Caldera version upgrade (5.0.0 → 5.3.0)

- Bumped the cloned Caldera tag in `docker/Dockerfile.caldera` from `5.0.0` to `5.3.0`.
- Removed the forced `yarl==1.9.4` downgrade. That pin was a workaround for a 5.0.0/aiohttp-3.9
  quirk; it's incompatible with 5.3.0, which ships aiohttp 3.10.11 and needs a newer `yarl` that
  provides `Query` (pinning the old version made the server crash on import). Removing the pin
  lets pip resolve a compatible version on its own.
- Verified the version-tied patches still apply cleanly under 5.3.0 (the `app_svc.py`
  Jinja2 template-path patch, and the manx `c_session` stub that `contact_tcp.py` still imports).

## Enable all Caldera for OT plugins

- Previously only the `dnp3` plugin was appended to `conf/default.yml`'s enabled plugin list,
  even though the Dockerfile clones the entire `caldera-ot` repo (all plugins).
- The plugin-copy step now records the name of every OT plugin directory it installs to
  `ot_plugins.txt`, which is filtered against whatever survives the existing "missing
  `hook.py`" cleanup step, and then all of them are appended to `default.yml`'s plugin list
  (not just `dnp3`).

## IEC 61850 payload fetching

- The `iec61850` plugin's ability definitions reference precompiled payload binaries
  (`iec61850_actions`, `iec61850_actions.exe`, `iec61850_actions_darwin`) that aren't checked
  into the `caldera-ot` repo - they're distributed separately from
  [mitre/iec61850-payloads](https://github.com/mitre/iec61850-payloads). Without them, Caldera
  logs "Payload referenced ... but not found" warnings at startup and the plugin's abilities
  can't run.
- `Dockerfile.caldera` now fetches all three binaries from that repo's latest GitHub release
  into `plugins/iec61850/payloads/` and sets the correct executable permissions, per that
  repo's README instructions.

## DNP3 scenario auto-provisioning

- `docker/Dockerfile.caldera` now copies this repo's DNP3 fact source
  (`docs/sources/grid-simulator-facts.yml`) and all four adversary profile templates
  (`docs/adversaries/*.yml`) into the `dnp3` plugin's `data/sources/` and `data/adversaries/`
  directories at build time, so the scenarios documented in the README are available out of the
  box instead of requiring a manual copy step.
- The fact source's templated `dnp3.server.ip` (`127.0.0.1`, meant for local/manual use) is
  patched to `outstation`, the correct hostname on the `ot-lab` Docker network.

## Bug fixes

- **Caldera startup hang.** The `atomic` plugin's `enable()` falls back to a live `git clone`
  of `redcanaryco/atomic-red-team` when its submodule data isn't present in the image, which
  was blocking the whole server boot sequence for 5+ minutes. Since this lab only needs the OT
  plugins, `atomic` and `training` are now explicitly removed from `default.yml`'s plugin list
  in `Dockerfile.caldera`. Caldera now reaches "healthy" in under 20 seconds.
- **Agent container couldn't execute the DNP3 payload.** The `dnp3-actions` Linux payload is a
  dynamically-linked amd64 glibc binary with no ARM64 build wired into its ability definitions.
  The `agent` container was Alpine (musl-based, no glibc at all) running natively as arm64 on
  Apple Silicon, so any attempt to execute the payload failed with
  `rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2`. Fixed by:
  - Pinning `agent` to `platform: linux/amd64` in `docker-compose.yml`, so Docker Desktop's
    Rosetta emulates the *whole* container as real x86_64 (rather than one foreign binary
    inside a native arm64 filesystem, which doesn't work for dynamically-linked binaries).
  - Switching `docker/Dockerfile.agent`'s base image from `alpine:3.19` to `ubuntu:24.04`
    (glibc-based; `debian:bookworm-slim` was tried first but its glibc 2.36 was too old - the
    payload needs `GLIBC_2.38`, which Ubuntu 24.04's glibc 2.39 satisfies).
  - Verified with a real DNP3 integrity poll executed against the outstation from inside the
    fixed agent container - exit code 0, real protocol data read back.
- **`smoke-test.sh` operation creation failing with a 500.** Caldera's `/api/v2/operations`
  endpoint requires `source.id` whenever `source.facts` are supplied (its own API docs say so),
  but the script's operation payload only set `source.name`. This wasn't caused by the version
  bump - the same code path exists in 5.0.0 - it was a pre-existing bug in the script. Added
  `"id": "smoke-test-source"` to the request body.

## Wireshark packet capture sidecar

- Added an optional `capture` service to `docker/docker-compose.yml`, gated behind a Compose
  profile (`--profile capture`) so it doesn't run by default.
- It shares the `outstation` container's network namespace (`network_mode: "service:outstation"`)
  rather than joining the `ot-lab` network directly - a Linux bridge only forwards unicast
  frames to their actual destination port, so a third container on `ot-lab` would never see
  `agent`↔`outstation` traffic. Sitting in `outstation`'s namespace instead sees everything sent
  to or from it, including DNP3 attack traffic from `agent` and connections via the published
  `20000` port.
- Implemented with [`linuxserver/wireshark`](https://hub.docker.com/r/linuxserver/wireshark),
  a full browser-accessible Wireshark desktop (via Selkies), reachable at
  `https://127.0.0.1:3001` (HTTP on `3000`). Both ports are bound to `127.0.0.1` only, since the
  image ships with no built-in authentication.
  - Because the sidecar shares `outstation`'s network namespace, it can't publish its own
    ports - the GUI ports are declared on the `outstation` service instead.
  - Verified live: the container starts cleanly, the GUI responds on both ports, `eth0` is
    visible inside the container, and a real `dumpcap` capture correctly recorded packets from
    a connection hitting `outstation`'s published port.
- **Black screen bug (Wireshark never appeared).** The desktop loaded fine but nothing rendered
  in it. Root cause: this image's desktop session is a nested Wayland setup - the Python
  "selkies" streaming process is the actual (outer) compositor, and `labwc` (window manager,
  which runs Wireshark's autostart) connects to it as a client over a Unix domain socket under
  `$XDG_RUNTIME_DIR`, which the image's own init script hardcodes to `$HOME/.XDG` (i.e.
  `/config/.XDG`) regardless of any environment override. That path sat on the `./captures`
  bind mount, and Unix domain sockets are unreliable over Docker Desktop for Mac's bind-mount
  filesystem (virtiofs/osxfs) - the socket file "exists" but connections to it fail, so
  `labwc`'s backend can't start and nothing (Wireshark included) ever renders. Fixed by keeping
  `/config` itself off the bind-mount filesystem entirely: it's now a named Docker volume
  (`wireshark-config`, backed by the VM's real filesystem, where sockets work normally), with
  only the `Desktop` subfolder - where saved/downloaded files actually land - bind-mounted to
  `./captures` so output stays host-readable. Verified fixed on repeated cold starts (fresh
  volume, no leftover state): Wireshark now launches immediately every time.

## Documentation and misc

- `README.md`: added a "Packet Capture (Wireshark)" section under the Docker instructions,
  documenting the sidecar and a lighter-weight one-off `tcpdump`-into-local-Wireshark
  alternative.
- `.gitignore`: added `docker/captures/` (the capture sidecar's output/config directory).
- `docker/demo.md` (new file): added a `## commands` section with the exact `docker compose`
  commands to spin up the full stack (with the capture profile) and tear it down.
