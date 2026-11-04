"""Lifecycle/pixel tests in a disposable nested Hyprland. Never load in parent."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
STOCK = '/usr/lib/omarchy-hyprland-titlebars/titlebars.so'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('library', type=Path)
args = parser.parse_args()
library = args.library.resolve()
artifacts = Path('/tmp/opencode/focus-titlebars-service-tests')
artifacts.mkdir(parents=True, exist_ok=True)
parent_signature = os.environ['HYPRLAND_INSTANCE_SIGNATURE']
parent_display = str(Path(os.environ['XDG_RUNTIME_DIR']) / os.environ['WAYLAND_DISPLAY'])

with tempfile.TemporaryDirectory(prefix='ft-', dir='/tmp/opencode') as tmp:
    tmp = Path(tmp)
    config = tmp / 'hyprland.lua'
    config.write_text('''
hl.monitor({ output = "", mode = "1280x800@60", position = "0x0", scale = 1 })
hl.config({ general = { gaps_in = 8, gaps_out = 8, border_size = 2, resize_on_border = true }, animations = { enabled = false }, input = { follow_mouse = 0 }, misc = { disable_hyprland_logo = true, disable_splash_rendering = true } })
hl.plugin.load("/usr/lib/omarchy-hyprland-titlebars/titlebars.so")
if hl.plugin.hyprbars then
  hl.config({ plugin = { hyprbars = {
    enabled = true, bar_height = 30, bar_color = "rgb(24283b)", bar_color_inactive = "rgb(24283b)", col = { text = "rgb(c0caf5)" },
    bar_text_align = "left", bar_text_size = 12, bar_part_of_window = true, bar_precedence_over_border = true,
    on_double_click = [[hyprctl dispatch 'hl.dsp.window.fullscreen({ mode = "maximized", action = "toggle", window = "address:%WINDOW%" })']],
  } } })
  hl.plugin.hyprbars.add_button({ bg_color = "rgb(24283b)", fg_color = "rgb(c0caf5)", size = 20, icon = "×", action = [[hyprctl dispatch 'hl.dsp.window.close({ window = "address:%WINDOW%" })']] })
end
''')
    original_config = config.read_bytes()
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp), AQ_BACKEND='wayland', WAYLAND_DISPLAY=parent_display, HYPRLAND_NO_SD_NOTIFY='1', HYPRLAND_NO_SD_VARS='1')
    env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
    log = (artifacts / 'compositor.log').open('w')
    compositor = subprocess.Popen(['Hyprland', '--config', str(config)], env=env, stdout=log, stderr=log)
    clients = []
    service = None
    quickshell = None
    victim = None

    def ctl(*argv):
        if argv[0] in ('plugin', 'eval'):
            assert env.get('HYPRLAND_INSTANCE_SIGNATURE') not in (None, parent_signature)
        result = subprocess.run(['hyprctl', *argv], env=env, text=True, capture_output=True, timeout=8)
        if result.returncode:
            raise RuntimeError(f'{argv}: {result.stdout} {result.stderr} (exit {result.returncode})')
        output = result.stdout.strip()
        if output.startswith(('Err', 'error', "Couldn't", 'Cannot')):
            raise RuntimeError(output)
        return output

    def names():
        return {p['name'] for p in json.loads(ctl('plugin', 'list', '-j'))}

    def stock_enabled():
        return json.loads(ctl('getoption', 'plugin:hyprbars:enabled', '-j'))['bool']

    def focus(address):
        ctl('dispatch', f'hl.dsp.focus({{ window = "address:{address}" }})')

    def activate(pid=os.getpid(), show=180, hide=120):
        ctl('eval', f'hl.plugin.focus_titlebars.activate({pid}, {show}, {hide})')

    def geometry():
        return {w['address']: (w['at'], w['size']) for w in json.loads(ctl('clients', '-j'))}

    def pixels(address):
        window = next(w for w in json.loads(ctl('clients', '-j')) if w['address'] == address)
        x, y = window['at'][0] + min(250, window['size'][0] - 130), window['at'][1] - 30
        ppm = subprocess.check_output(['grim', '-t', 'ppm', '-g', f'{x},{y} 1x30', '-'], env=env)
        magic, size, depth, data = ppm.split(b'\n', 3)
        assert magic == b'P6' and depth == b'255'
        return [tuple(data[i:i+3]) for i in range(0, 90, 3)]

    def pointer(commands):
        monitor = json.loads(ctl('monitors', '-j'))[0]
        subprocess.run([str(tmp / 'pointer'), str(round(monitor['width'] / monitor['scale'])), str(round(monitor['height'] / monitor['scale']))], env=env, input='\n'.join(commands) + '\n', text=True, check=True, timeout=10)
        time.sleep(.2)

    def start_service():
        process = subprocess.Popen(['/usr/bin/python3', str(ROOT / 'manager.py')], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 1)
            if ready:
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError('manager exited; inspect compositor.log')
                state = json.loads(line)
                if state['state'] == 'active':
                    process.worker_pid = state['owner']
                    return process
                if state['state'] == 'error':
                    raise RuntimeError(state)
        process.kill()
        process.wait()
        raise RuntimeError('manager startup timed out')

    try:
        for _ in range(80):
            if compositor.poll() is not None:
                raise RuntimeError('nested compositor exited')
            try:
                instances = json.loads(ctl('instances', '-j'))
                if instances:
                    env['HYPRLAND_INSTANCE_SIGNATURE'] = instances[0]['instance']
                    env['WAYLAND_DISPLAY'] = instances[0]['wl_socket']
                    break
            except (ValueError, subprocess.SubprocessError):
                pass
            time.sleep(.1)
        assert env.get('HYPRLAND_INSTANCE_SIGNATURE') != parent_signature
        for kind, name in [('client-header', 'pointer-protocol.h'), ('private-code', 'pointer-protocol.c')]:
            subprocess.run(['wayland-scanner', kind, str(ROOT / 'tests/wlr-virtual-pointer-unstable-v1.xml'), str(tmp / name)], check=True)
        subprocess.run(['cc', str(ROOT / 'tests/pointer.c'), str(tmp / 'pointer-protocol.c'), '-I', str(tmp), '-lwayland-client', '-o', str(tmp / 'pointer')], check=True)
        addresses = []
        monitor = json.loads(ctl('monitors', '-j'))[0]
        width = round(monitor['width'] / monitor['scale'])
        height = round(monitor['height'] / monitor['scale'])
        window_width = min(500, width // 2 - 60)
        window_height = min(300, height - 100)
        window_y = min(320, height - window_height - 20)
        for index, x in enumerate((30, width // 2 + 20)):
            process = subprocess.Popen(['alacritty', '--config-file', '/dev/null', '--class', f'focus-test-{index}', '-e', 'sleep', '180'], env=env, stdout=log, stderr=log)
            clients.append(process)
            for _ in range(60):
                windows = json.loads(ctl('clients', '-j'))
                if len(windows) == index + 1: break
                time.sleep(.1)
            address = next(w['address'] for w in windows if w['address'] not in addresses)
            addresses.append(address)
            ctl('dispatch', f'hl.dsp.window.float({{ action = "enable", window = "address:{address}" }})')
            ctl('dispatch', f'hl.dsp.window.resize({{ x = {window_width}, y = {window_height}, window = "address:{address}" }})')
            ctl('dispatch', f'hl.dsp.window.move({{ x = {x}, y = {window_y}, window = "address:{address}" }})')
        a, b = addresses
        time.sleep(.2)
        bar_pixel = pixels(b)[2]
        assert pixels(a).count(bar_pixel) >= 28 and pixels(b).count(bar_pixel) >= 28
        original_geometry = geometry()
        for _ in range(3):
            result = ctl('plugin', 'load', str(library))
            assert 'focus-titlebars' in names(), result
            activate()
            assert not stock_enabled()
            focus(b)
            time.sleep(.15)
            assert pixels(a).count(bar_pixel) == 0, pixels(a)
            assert pixels(b).count(bar_pixel) >= 28, pixels(b)
            for _ in range(3):
                ctl('reload')
                time.sleep(.1)
                assert names() == {'hyprbars', 'focus-titlebars'}, names()
                assert not stock_enabled()
                assert not ctl('configerrors'), ctl('configerrors')
            ctl('plugin', 'unload', str(library))
            time.sleep(.15)
            assert stock_enabled()
            assert names() == {'hyprbars'}
            assert pixels(a).count(bar_pixel) >= 28 and pixels(b).count(bar_pixel) >= 28
        print('PASS: coexistence, repeated activation/reload/unload, automatic stock restoration', flush=True)

        ctl('plugin', 'load', str(library))
        activate()
        focus(a)
        time.sleep(.15)
        assert pixels(a).count(bar_pixel) >= 28 and pixels(b).count(bar_pixel) == 0
        assert geometry() == original_geometry
        ctl('eval', 'hl.config({ plugin = { hyprbars = { workspace_tag = "focus-test" } } })')
        ctl('dispatch', f'hl.dsp.window.tag({{ tag = "+focus-test", window = "address:{a}" }})')
        time.sleep(.15)
        assert pixels(a).count(bar_pixel) >= 28 and pixels(b).count(bar_pixel) == 0
        ctl('dispatch', f'hl.dsp.window.tag({{ tag = "-focus-test", window = "address:{a}" }})')
        time.sleep(.15)
        assert pixels(a).count(bar_pixel) == 0
        ctl('eval', 'hl.config({ plugin = { hyprbars = { workspace_tag = "" } } })')
        config.write_bytes(original_config.replace(b'enabled = true, bar_height', b'enabled = false, bar_height'))
        ctl('reload')
        time.sleep(.15)
        assert pixels(a).count(bar_pixel) == 0 and pixels(b).count(bar_pixel) == 0
        config.write_bytes(original_config)
        ctl('reload')
        time.sleep(.15)
        assert pixels(a).count(bar_pixel) >= 28 and pixels(b).count(bar_pixel) == 0
        print('PASS: live workspace tags and no-floating-workspace config transitions', flush=True)
        ctl('eval', 'hl.config({ animations = { enabled = true } })')
        activate(show=290, hide=290)
        focus(b)
        time.sleep(.035)
        incoming, outgoing = pixels(b).count(bar_pixel), pixels(a).count(bar_pixel)
        assert 0 < incoming < 30 and 0 < outgoing < 30, (incoming, outgoing)
        for index in range(12):
            focus(a if index % 2 == 0 else b)
            time.sleep(.02)
        time.sleep(.4)
        assert pixels(a).count(bar_pixel) == 0 and pixels(b).count(bar_pixel) >= 28
        assert geometry() == original_geometry
        bw = next(w for w in json.loads(ctl('clients', '-j')) if w['address'] == b)
        pointer([f'move {bw["at"][0] + 100} {bw["at"][1] - 15}', 'wait 450', 'down', 'up', 'wait 100', 'down', 'up'])
        assert next(w for w in json.loads(ctl('clients', '-j')) if w['address'] == b)['fullscreen'] == 1
        ctl('dispatch', f'hl.dsp.window.fullscreen({{ mode = "maximized", action = "unset", window = "address:{b}" }})')
        print('PASS: focus-only pixels, intermediate slide frames, rapid reversal, unchanged client geometry, double click', flush=True)

        # A SIGKILL must restore stock without relying on Python finally/QML.
        victim = subprocess.Popen(['sleep', '180'])
        activate(pid=victim.pid)
        victim.kill()
        victim.wait()
        time.sleep(.2)
        assert stock_enabled()
        ctl('plugin', 'unload', str(library))
        print('PASS: pidfd restores stock after owner SIGKILL', flush=True)

        service = start_service()
        assert not stock_enabled() and names() == {'hyprbars', 'focus-titlebars'}
        service.stdin.close()
        service.wait(timeout=10)
        service = None
        assert stock_enabled() and names() == {'hyprbars'}
        service = start_service()
        service.kill()
        service.wait()
        os.kill(service.worker_pid, 9)
        service.stdin.close()
        service = None
        time.sleep(.2)
        assert stock_enabled()
        service = start_service()  # handles the crashed owner's stale library
        assert not stock_enabled()
        service.terminate()
        service.wait(timeout=10)
        service = None
        assert stock_enabled() and names() == {'hyprbars'}
        shell_config = tmp / 'shell.qml'
        shell_config.write_text(f'import QtQuick\nimport Quickshell\nimport Quickshell.Io\nShellRoot {{ Loader {{ id: service; source: "{(ROOT / "Service.qml").as_uri()}" }} IpcHandler {{ target: "test"; function unload(): void {{ service.active = false }} }} }}\n')
        quickshell = subprocess.Popen(['qs', '-p', str(shell_config), '--no-color'], env=env, stdout=log, stderr=log)
        for _ in range(80):
            if quickshell.poll() is not None:
                raise RuntimeError('Quickshell service failed to load; inspect compositor.log')
            if 'focus-titlebars' in names() and not stock_enabled(): break
            time.sleep(.1)
        assert not stock_enabled() and 'focus-titlebars' in names()
        status = subprocess.check_output(['qs', 'ipc', '-p', str(shell_config), 'call', 'alec.focus-titlebars', 'status'], env=env, text=True)
        assert json.loads(status)['state'] == 'active', status
        subprocess.run(['qs', 'ipc', '-p', str(shell_config), 'call', 'test', 'unload'], env=env, check=True, capture_output=True)
        for _ in range(60):
            if stock_enabled() and names() == {'hyprbars'}: break
            time.sleep(.1)
        assert stock_enabled() and names() == {'hyprbars'}
        quickshell.terminate()
        quickshell.wait(timeout=10)
        quickshell = None
        for _ in range(40):
            if stock_enabled() and names() == {'hyprbars'}: break
            time.sleep(.1)
        assert stock_enabled() and names() == {'hyprbars'}
        print('PASS: actual Quickshell service loads, reports active IPC status, restores stock on shell exit', flush=True)
        assert config.read_bytes() == original_config
        assert not ctl('configerrors'), ctl('configerrors')
        print('PASS: service EOF/disable, SIGKILL recovery, restart, zero config-file mutations', flush=True)
    finally:
        if quickshell and quickshell.poll() is None:
            quickshell.terminate()
            quickshell.wait(timeout=10)
        if service and service.poll() is None:
            service.terminate()
            service.wait(timeout=10)
        if victim and victim.poll() is None:
            victim.kill()
            victim.wait()
        for client in clients:
            if client.poll() is None:
                client.terminate()
                client.wait(timeout=5)
        compositor.terminate()
        try: compositor.wait(timeout=5)
        except subprocess.TimeoutExpired:
            compositor.kill()
            compositor.wait()
        for path in tmp.glob('hypr/*/hyprland.log'):
            shutil.copy2(path, artifacts / 'hyprland.log')
        log.close()
