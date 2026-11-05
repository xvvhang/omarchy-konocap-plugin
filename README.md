# Konocap

Part of **Konochi**, a personal Omarchy plugin series by Alec Xu.

**Konocap 1.1.0** · Formerly Focus Titlebars. A focus-aware "cap" for floating
windows, complementing Konospaces and Konoview.

An Omarchy service plugin that shows floating-window titlebars **only on the
active window**, sliding them out of—and back into—the window's top edge.

**Zero manual Hyprland configuration.** Install and enable through Omarchy's
plugin system. No edits to `hyprland.lua`, generated includes, autostart entries,
load-path wrappers, or changes to packaged system files.

## Features

- Focused window: slide out in **180 ms**; unfocused window: retract in **120 ms**.
- OutCubic easing; respects Hyprland's global animation toggle.
- Hidden titlebars reserve no space and accept no clicks. Client geometry stays
  unchanged when focus moves.
- Follows the stock titlebar's theme, typography, workspace tags, no-bar rules,
  and double-click action.
- Preserves the standard Omarchy close, maximize, and minimize buttons and
  titlebar dragging.
- Automatically builds the bundled native extension on first enable.
- Disabling restores stock titlebars. Handles config reloads, plugin hot reloads,
  Shell restarts, and unexpected manager exits.

This changes **Omarchy's titlebars for floating workspaces**, not titlebars drawn
by applications themselves. It is a service plugin, not a Bar widget.

## Compatibility

Tested with:

| Component | Version |
| --- | --- |
| Omarchy | **4.5.0-3 (stable)**; also tested on 4.5.0rc3-1 |
| Hyprland, Lua configuration | 0.56.2-4 |
| `omarchy-hyprland-titlebars` | 0.2.2-2 |

The native extension uses Hyprland's internal C++ API. Other versions are not
guaranteed to work; a new major API may require a source update, not just a
rebuild. ABI checks reject an incompatible binary.

Build requirements:

- Linux with pidfd support and Python 3.9 or newer.
- CMake 3.27+, a C++23 compiler, and pkg-config.
- Installed Hyprland headers and the development files for libdrm, libinput,
  libudev, pixman, Wayland server, and xkbcommon.
- Omarchy's stock `omarchy-hyprland-titlebars` package.

Dependencies are **not** downloaded or installed automatically. A build failure
leaves stock titlebars unchanged.

## Install

```sh
omarchy plugin add https://github.com/xvvhang/omarchy-konocap-plugin.git --enable
```

Omarchy installs the plugin as **`konochi.konocap`**, the ID in its manifest.
The first activation may take a little longer while the native extension builds.

The repository is `xvvhang/omarchy-konocap-plugin`. GitHub redirects the previous
`omarchy-focus-titlebars-plugin` URL; new installations should use the URL above.

### Enable / disable

Use Omarchy's plugin manager, or:

```sh
omarchy plugin enable konochi.konocap
omarchy plugin disable konochi.konocap
```

Disabling restores the stock behavior; no Hyprland configuration cleanup is
needed. Update through Omarchy's plugin manager:

```sh
omarchy plugin update konochi.konocap
```

### Status

```sh
omarchy-shell konochi.konocap status
```

An active service reports its cached library path, manager PID, and animation
durations. During the first build it reports `building`; a startup failure
reports `error`.

### Upgrading from Focus Titlebars 1.0.0

The plugin and IPC ID changed to `konochi.konocap`. Before updating an existing
installation, disable its legacy ID (`xvvhang.focus-titlebars` or
`alec.focus-titlebars`) through Omarchy. After updating the files:

1. Rename the installed plugin directory to `konochi.konocap` if it still uses
   the old name. Do not leave two copies of the same repository installed.
2. Replace the legacy entry in `shell.json` with `konochi.konocap`, retaining any
   custom duration settings, and remove duplicate legacy enablement entries.
3. Enable `konochi.konocap` and use its new status command above.

For existing Git checkouts, update the remote to the new repository URL:

```sh
git remote set-url origin https://github.com/xvvhang/omarchy-konocap-plugin.git
```

Native module/library (`focus-titlebars`) and cache/lock names intentionally stay
unchanged: the branding migration does not change lifecycle ownership or create
a second independent native module. The service can still read legacy duration
settings if no canonical entry exists. No Hyprland configuration edits are needed.

## Optional settings

Defaults require no configuration. To change animation durations, add these keys
to the **existing** plugin entry in `~/.config/omarchy/shell.json`:

```json
{
  "id": "konochi.konocap",
  "showDuration": 180,
  "hideDuration": 120
}
```

Do not replace the whole configuration file with this fragment. Durations are
milliseconds, clamped to 0–290; zero disables that transition. Changes are read
on the next plugin start—disable and re-enable to apply them.

## How it works

`Service.qml` follows Omarchy's service-plugin lifecycle. `manager.py` builds and
loads the native extension, holds a per-session lock, and restores/unloads the
extension when the service stops.

The native module has distinct symbols, name, and decorations. Stock `hyprbars`
**stays loaded** and retains ownership of its settings, rules, and buttons. The
extension reads those live settings and temporarily suppresses stock drawing
through Hyprland's **session-only config-value API**. It neither unloads the stock
library nor requests a configuration reload.

Native config/rule events resynchronize settings after reloads and when floating
workspaces are activated. A per-session lock serializes outgoing cleanup and
incoming activation during hot reloads and restarts.

The service uses an idle supervisor/worker pair. Quickshell owns the supervisor;
the worker also holds Quickshell's stdin pipe. Even if QML destruction immediately
kills the direct child, pipe EOF lets the worker finish restoring/unloading the
extension. Neither is an independent autostart or persistent system service.

A **pidfd lease** additionally watches the worker from Hyprland. If the worker is
killed with SIGKILL, a kernel readiness event restores stock automatically, with
no polling loop. The extension may remain loaded but dormant after an unclean
exit; the next activation removes it before loading the current build.

### Files and state

All implementation and test code lives in the installed plugin directory:

```text
konochi.konocap/
├── manifest.json
├── Service.qml             # Omarchy lifecycle and status IPC
├── manager.py              # Build cache, loading, ownership, cleanup
├── native/                 # Native rendering, lifecycle, CMake, upstream licenses
├── tests/                  # Isolated lifecycle and rendering tests
├── LICENSE
├── CHANGELOG.md
└── README.md
```

Outside that directory, the plugin uses only:

| Location | Purpose |
| --- | --- |
| `~/.config/omarchy/shell.json` | Standard Omarchy enablement and optional settings |
| `$XDG_CACHE_HOME/omarchy-focus-titlebars/` | Compiled libraries and build logs; defaults to `~/.cache/` |
| `$XDG_RUNTIME_DIR/omarchy-focus-titlebars-*` | Per-session lock and last-loaded-library record |

Build-cache keys include the source, running Hyprland version, and installed
version header. Builds never overwrite an already mapped `.so`.

## Troubleshooting

1. Check the status command above.
2. Inspect the cached `build.log` if compilation failed.
3. Inspect Shell logs for messages containing `Konocap`.
4. Disable the plugin to restore stock behavior immediately.

After a Hyprland upgrade, restart the desktop session so the running compositor
matches its installed headers, then re-enable the plugin. A new cache key causes
an automatic rebuild. If the internal API changed, source changes may be needed.

## Development and verification

From the repository directory:

```sh
omarchy plugin validate .
python3 -m unittest discover -s tests -p 'test_*.py'
python3 manager.py --build-only
python3 tests/verify.py /path/printed/by/build-only/focus-titlebars.so
```

The verifier also needs Quickshell, Alacritty, grim, wayland-scanner, and a C
compiler, and must run inside a live Hyprland session. It creates a disposable
nested compositor; **no candidate is loaded into the parent desktop**.

Tests cover:

- Stock coexistence and repeated activation, reload, and unload.
- Live workspace tags and transitions away from floating workspaces.
- Pixel-level focus visibility and intermediate slide frames.
- Rapid focus reversal and unchanged client geometry.
- Double-click maximize.
- EOF, SIGTERM, and SIGKILL restoration and restart recovery.
- The real QML service's loading, status IPC, and destruction.
- No changes to the nested compositor's configuration file.

Artifacts are written to `/tmp/opencode/focus-titlebars-service-tests/`.

## License and attribution

The service and integration code are MIT-licensed; see [LICENSE](LICENSE).

Native rendering is derived from
[omacom/omarchy-hyprland-titlebars](https://github.com/omacom/omarchy-hyprland-titlebars)
v0.2.2 (`379ff91`), itself based on Hyprland's hyprbars plugin. Its original
[BSD-3-Clause](native/LICENSE) and [MIT](native/LICENSE.MIT) notices are retained.
