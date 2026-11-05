"""Konocap: Omarchy service lifetime -> native lease. No Hyprland file writes."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STOCK = Path("/usr/lib/omarchy-hyprland-titlebars/titlebars.so")
NAME = "focus-titlebars"
# Keep native/cache/lock identifiers stable across the branding migration.
PLUGIN_ID = "konochi.konocap"
LEGACY_IDS = ("xvvhang.focus-titlebars", "alec.focus-titlebars")


def ctl(*args: str) -> str:
    result = subprocess.run(["hyprctl", *args], text=True, capture_output=True, timeout=10, check=True)
    output = result.stdout.strip()
    if output.startswith(("Err", "error", "Couldn't", "Cannot", "no such")):
        raise RuntimeError(output)
    if "could not be loaded" in output:
        raise RuntimeError(output)
    return output


def plugins() -> set[str]:
    return {entry["name"] for entry in json.loads(ctl("plugin", "list", "-j"))}


def durations(settings: dict) -> tuple[int, int]:
    def bounded(key: str, default: int) -> int:
        value = settings.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return default
        return max(0, min(290, int(value)))
    return bounded("showDuration", 180), bounded("hideDuration", 120)


def configured_settings() -> dict:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    try:
        document = json.loads((config_home / "omarchy/shell.json").read_text())
        entries = document.get("plugins", [])
        for plugin_id in (PLUGIN_ID, *LEGACY_IDS):
            entry = next((p for p in entries if isinstance(p, dict) and p.get("id") == plugin_id), None)
            if entry is not None:
                return entry
        return {}
    except (OSError, ValueError, TypeError):
        return {}


def emit(state: str, **details) -> None:
    print(json.dumps({"state": state, **details}), flush=True)


def build() -> Path:
    # Key both the running ABI and build inputs; never overwrite a mapped .so.
    version = ctl("version", "-j")
    header = Path("/usr/include/hyprland/src/version.h").read_bytes()
    digest = hashlib.sha256(version.encode() + header)
    for source in sorted((ROOT / "native").iterdir()):
        if source.is_file():
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "omarchy-focus-titlebars" / digest.hexdigest()[:24]
    library = cache / "build/focus-titlebars.so"
    if library.is_file() and (cache / "complete").is_file():
        return library
    emit("building")
    cache.mkdir(parents=True, exist_ok=True)
    # Separate build lock for simultaneous sessions sharing a user's cache.
    with (cache / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if library.is_file() and (cache / "complete").is_file():
            return library
        with (cache / "build.log").open("w") as log:
            subprocess.run(["cmake", "-S", str(ROOT / "native"), "-B", str(cache / "build"), "-DCMAKE_BUILD_TYPE=Release"], stdout=log, stderr=log, check=True, timeout=60)
            subprocess.run(["cmake", "--build", str(cache / "build"), "-j", "2"], stdout=log, stderr=log, check=True, timeout=180)
        (cache / "complete").touch()
    return library


def activate(settings: dict) -> tuple[int, int]:
    show, hide = durations(settings)
    ctl("eval", f"hl.plugin.focus_titlebars.activate({os.getpid()}, {show}, {hide})")
    return show, hide


def previous_library(record: Path) -> Path:
    previous = Path(record.read_text().strip())
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "omarchy-focus-titlebars"
    if not previous.is_relative_to(cache_root) or previous.name != "focus-titlebars.so":
        raise RuntimeError("Refusing to unload an unknown native library")
    return previous


def run(settings: dict) -> None:
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if not signature or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in signature):
        raise RuntimeError("No valid Hyprland session")
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    # Serialize hot reload/restart cleanup and activation. A departing service
    # must never unload a successor's library. Kernel releases lock on SIGKILL.
    with (runtime / f"omarchy-focus-titlebars-{signature}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = runtime / f"omarchy-focus-titlebars-{signature}.library"
        library = build()  # Build failure leaves stock completely untouched.
        if "hyprbars" not in plugins():
            ctl("plugin", "load", str(STOCK))
        if NAME in plugins():
            # An uncleanly terminated former owner has already been deactivated
            # by its pidfd. Unload it before installing this exact cached build.
            ctl("plugin", "unload", str(previous_library(record)))
        loaded = False
        try:
            record.write_text(str(library))
            ctl("plugin", "load", str(library))
            loaded = True
            show, hide = activate(settings)
            emit("active", library=str(library), owner=os.getpid(), showDuration=show, hideDuration=hide)
            # Quickshell owns this stdin pipe. EOF means plugin destruction or
            # shell exit; SIGTERM also reaches the same finally block.
            for line in sys.stdin:
                if len(line) > 4096:
                    continue
                message = json.loads(line)
                show, hide = activate(message)
                emit("active", library=str(library), owner=os.getpid(), showDuration=show, hideDuration=hide)
        finally:
            if loaded:
                try:
                    ctl("eval", f"if hl.plugin.focus_titlebars then hl.plugin.focus_titlebars.deactivate({os.getpid()}) end")
                    ctl("plugin", "unload", str(library))
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    print(f"cleanup: {error}", file=sys.stderr, flush=True)


def supervise(settings: dict) -> int:
    # Quickshell can SIGKILL its direct Process child during QML destruction.
    # A worker in its own process group survives that long enough to receive
    # EOF on Quickshell's stdin pipe and restore/unload the native extension.
    # Neither process outlives the pipe; the supervisor only blocks in waitpid.
    pid = os.fork()
    if pid == 0:
        os.setsid()
        run(settings)
        return 0

    def forward(signum, _frame):
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default="{}")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        if args.build_only:
            print(build(), flush=True)
        else:
            return supervise({**configured_settings(), **json.loads(args.settings)})
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        emit("error", error=str(error))
        print(str(error), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
