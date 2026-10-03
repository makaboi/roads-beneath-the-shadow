"""Bounded Linux/X11 source integration for resize and fullscreen regressions.

The owner starts its own Xvfb, window manager and PixelWindow probe, then waits
every owned process on success or failure. The probe instruments set_mode calls
and synthetic stale notifications; it is not a public-binary gameplay test.
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 90
DESKTOP = (1920, 1200)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    with path.open("rb") as incoming:
        return hashlib.sha256(incoming.read()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def process_table() -> dict[int, tuple[int, int]]:
    """Read only PID, parent and process group; tolerate processes exiting."""
    result = {}
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            # comm may contain spaces and parentheses, unlike numeric fields.
            fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
            result[int(directory.name)] = (int(fields[1]), int(fields[2]))
        except (OSError, ValueError, IndexError):
            continue
    return result


class OwnedProcesses:
    """Terminate launched sessions and descendants, preserving caller children.

    Dedicated mode is only for a fresh CLI owner with no pre-existing children;
    every subsequent adoption belongs to this check. Library mode reports an
    ambiguous detached adoption rather than signalling an unrelated process.
    """

    def __init__(self, output: Path, *, dedicated_owner: bool = False) -> None:
        self.output = output
        self.children: list[tuple[str, subprocess.Popen]] = []
        self.streams = []
        self.known = set()
        self.closed = False
        self.cleanup: dict = {}
        self.dedicated_owner = dedicated_owner
        table = process_table()
        self.foreign = {pid for pid, (parent, _) in table.items() if parent == os.getpid()}
        require(not dedicated_owner or not self.foreign, "Dedicated native-check owner must start without caller children")
        self.ambiguous = set()
        self.libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot inspect Linux child subreaper")
        self.previous_subreaper = previous.value
        if self.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot own orphaned display descendants")

    def launch(self, role: str, arguments: list[str], environment: dict, *, pass_fds=()) -> subprocess.Popen:
        stream = (self.output / (role + ".log")).open("wb")
        self.streams.append(stream)
        process = subprocess.Popen(
            arguments, cwd=self.output, env=environment, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True, pass_fds=pass_fds,
        )
        self.children.append((role, process))
        self.known.add(process.pid)
        return process

    def discover(self) -> dict[int, tuple[int, int]]:
        table = process_table()
        groups = {process.pid for _, process in self.children}
        changed = True
        while changed:
            changed = False
            for pid, (parent, group) in table.items():
                if parent in self.foreign and pid not in self.foreign:
                    self.foreign.add(pid)
                    changed = True
                if pid in self.foreign:
                    continue
                adopted = parent == os.getpid() and pid not in self.known
                if pid not in self.known and (parent in self.known or group in groups or adopted and self.dedicated_owner):
                    self.known.add(pid)
                    changed = True
                elif adopted:
                    self.ambiguous.add(pid)
        return table

    def close(self) -> dict:
        if self.closed:
            return self.cleanup
        self.closed = True
        reaped, direct, errors, requested = [], [], [], []
        try:
            table = self.discover()
            # Each new session has a group equal to the launched child's PID.
            # Signal it only while a discovered owned process still belongs.
            for _, process in reversed(self.children):
                if any(pid in self.known and group == process.pid for pid, (_, group) in table.items()):
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        requested.append({"process_group": process.pid, "signal": "SIGTERM"})
                    except ProcessLookupError:
                        pass
            for role, process in reversed(self.children):
                try:
                    code = process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                        requested.append({"process_group": process.pid, "signal": "SIGKILL"})
                    except ProcessLookupError:
                        pass
                    code = process.wait(timeout=3)
                direct.append({"role": role, "pid": process.pid, "exit_code": code, "owner_wait_completed": True})
            # Subreaper adoption keeps grandchildren waitable rather than
            # leaving zombies under PID1. Never use waitpid(-1), which could
            # consume an unrelated caller's child.
            roots = {process.pid for _, process in self.children}
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                table = self.discover()
                remaining = self.known.difference(roots).intersection(table)
                if not remaining:
                    break
                for pid in sorted(remaining):
                    if table[pid][0] != os.getpid():
                        continue
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        waited, status = os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        continue
                    if waited:
                        reaped.append({"pid": waited, "wait_status": status, "owned_adopted_child": True})
                time.sleep(0.02)
            table = self.discover()
            present = sorted(self.known.intersection(table))
            ambiguous = sorted(self.ambiguous.intersection(table))
            if present:
                errors.append("Owned processes still present after cleanup: " + repr(present))
            if ambiguous:
                errors.append("Ambiguous adopted caller children were preserved, not signalled: " + repr(ambiguous))
            self.cleanup = {"direct_children": direct, "adopted_reaps": reaped,
                            "owner_requested_shutdown": requested,
                            "ownership_mode": "dedicated_cli" if self.dedicated_owner else "guarded_library",
                            "preserved_preexisting_caller_pids": sorted(self.foreign), "ambiguous_adopted_pids": ambiguous,
                            "observed_owned_pids": sorted(self.known), "all_owned_pids_absent": not present and not ambiguous, "errors": errors}
        finally:
            for stream in self.streams:
                stream.close()
            if self.libc.prctl(36, self.previous_subreaper, 0, 0, 0) != 0:
                self.cleanup.setdefault("errors", []).append("Could not restore child subreaper setting")
        return self.cleanup


def check_timeout(value: float) -> float:
    if not 15 <= value <= TIMEOUT:
        raise argparse.ArgumentTypeError("Native display timeout must be between 15 and 90 seconds")
    return value


def find_tools(tool_path: str | None, manager: str) -> tuple[dict, dict]:
    environment = dict(os.environ)
    if tool_path:
        environment["PATH"] = tool_path + os.pathsep + environment.get("PATH", "")
    names = ("Xvfb", "xdotool", "xprop", manager)
    found = {name: shutil.which(name, path=environment.get("PATH")) for name in names}
    missing = [name for name, path in found.items() if path is None]
    require(not missing, "Install native display tools first: " + ", ".join(missing))
    if manager == "xfwm4":
        found["dbus-run-session"] = shutil.which("dbus-run-session", path=environment.get("PATH"))
        require(found["dbus-run-session"] is not None, "xfwm4 check requires dbus-run-session")
    return found, environment


def source_context() -> dict:
    paths = [Path(__file__), *sorted((ROOT / "roads_beneath_shadow").rglob("*.py"))]
    context = {"files": {str(path.relative_to(ROOT)): sha256(path) for path in paths},
               "python": sys.version, "github_sha": os.environ.get("GITHUB_SHA")}
    for name, arguments in (("local_head", ["rev-parse", "HEAD"]), ("worktree_status", ["status", "--porcelain"])):
        result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, timeout=10)
        context[name] = result.stdout.strip() if result.returncode == 0 else None
    return context


def display_number(read_fd: int, server: subprocess.Popen, deadline: float) -> int:
    data = b""
    while time.monotonic() < deadline:
        require(server.poll() is None, "Owned Xvfb exited before announcing a display")
        ready, _, _ = select.select([read_fd], [], [], min(0.05, max(0, deadline - time.monotonic())))
        if ready:
            chunk = os.read(read_fd, 128)
            require(bool(chunk), "Owned Xvfb did not announce its display")
            data += chunk
            if b"\n" in data:
                require(re.fullmatch(rb"\d+\n", data), "Invalid owned Xvfb display number")
                return int(data)
    raise TimeoutError("Owned Xvfb display allocation timed out")


def run_probe(output: Path) -> int:
    """Render real source on the main thread; a worker holds a Unicode prompt."""
    sys.path.insert(0, str(ROOT))
    from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow
    from roads_beneath_shadow.ui import InputClosed

    report = {"scope": "Instrumented source PixelWindow on owned real X11; no Game route or public executable claim.",
              "errors": [], "set_mode_calls": [], "handled_native_resizes": 0, "handled_F11": 0,
              "frames": 0, "answers": [], "stale_batch_sequence": 0, "normal_pygame_quit": False,
              "probe_pid": os.getpid(), "owner_pid": os.getppid()}
    ui, window, pg, worker = None, None, None, None
    original_set_mode = None
    request = None
    started = time.monotonic()
    try:
        ui = PixelUI(fast=True, sound=False)
        window = PixelWindow(ui, size=(1200, 900))
        pg = window.pg
        original_set_mode = pg.display.set_mode

        def counted_set_mode(*arguments, **keywords):
            report["set_mode_calls"].append({"frame": report["frames"], "size": list(arguments[0]),
                                             "flags": arguments[1] if len(arguments) > 1 else keywords.get("flags", 0)})
            return original_set_mode(*arguments, **keywords)

        pg.display.set_mode = counted_set_mode

        def prompt():
            try:
                report["answers"].append(ui.prompt("Traveler's name: "))
            except InputClosed:
                pass

        worker = threading.Thread(target=prompt, name="native-display-pending-input")
        worker.start()
        while not ui.closed.is_set() and time.monotonic() - started < TIMEOUT:
            window.drain()
            if request is None and window.request is not None:
                request = window.request
            for event in pg.event.get():
                if event.type == pg.VIDEORESIZE:
                    report["handled_native_resizes"] += 1
                if event.type == pg.KEYDOWN and event.key == pg.K_F11:
                    report["handled_F11"] += 1
                window.handle_event(event)
            control = output / "control.json"
            if control.is_file():
                command = json.loads(control.read_text(encoding="utf-8"))
                if command.get("operation") == "quit":
                    ui.close()
                if command.get("operation") == "seed_unicode" and not report.get("synthetic_unicode_textinput"):
                    window.handle_event(pg.event.Event(pg.TEXTINPUT, text=command["text"]))
                    report["synthetic_unicode_textinput"] = command["text"]
                if command.get("operation") == "stale_resize_batch" and command["sequence"] > report["stale_batch_sequence"]:
                    for width, height in command["sizes"]:
                        window.handle_event(pg.event.Event(pg.VIDEORESIZE, size=(width, height), w=width, h=height))
                    report["stale_batch_sequence"] = command["sequence"]
                    report["synthetic_stale_notification_sizes"] = command["sizes"]
            if ui.closed.is_set() or report["answers"]:
                break
            window.render()
            report["frames"] += 1
            report.update(surface_size=list(window.screen.get_size()), native_size=list(pg.display.get_window_size()),
                          window_size=list(window.window_size), native_position=list(pg.display.get_window_position()),
                          fullscreen=window.fullscreen, pending_request=window.request is request and request is not None,
                          entry=window.entry, worker_alive=worker.is_alive(), renderer_surface_is_live=window.screen is pg.display.get_surface())
            write_json(output / "probe-progress.json", report)
            window.clock.tick(60)
        require(time.monotonic() - started < TIMEOUT, "Native probe exceeded its deadline")
    except BaseException:
        report["errors"].append(traceback.format_exc())
        traceback.print_exc()
    finally:
        if ui is not None:
            ui.close()
        if worker is not None:
            worker.join(timeout=1)
        report["worker_joined"] = worker is None or not worker.is_alive()
        if pg is not None:
            if original_set_mode is not None:
                pg.display.set_mode = original_set_mode
            pg.quit()
            report["normal_pygame_quit"] = True
        report["seconds"] = round(time.monotonic() - started, 3)
        write_json(output / "probe-result.json", report)
    return 0 if not report["errors"] and report["worker_joined"] else 1


def exercise_native_window(owner: OwnedProcesses, output: Path, tools: dict, environment: dict, deadline: float) -> dict:
    player = owner.launch("probe", [sys.executable, str(Path(__file__).resolve()), "--probe", "--output-dir", str(output)], environment)
    commands, checks = [], []

    def remaining(cap=5):
        value = min(cap, deadline - time.monotonic())
        require(value > 0, "Native display check exceeded its deadline")
        return value

    def xdo(*arguments):
        command = [tools["xdotool"], *map(str, arguments)]
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=remaining())
        commands.append({"arguments": command[1:], "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        with (output / "external-commands.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(commands[-1]) + "\n")
        require(result.returncode == 0, "Native input/geometry command failed: " + " ".join(command[1:]))
        return result.stdout.strip()

    def progress(predicate, timeout=5):
        end = min(deadline, time.monotonic() + timeout)
        while time.monotonic() < end:
            require(player.poll() is None, "Native PixelWindow probe exited before completing checks")
            path = output / "probe-progress.json"
            if path.is_file():
                value = json.loads(path.read_text(encoding="utf-8"))
                require(value["probe_pid"] == player.pid and value["owner_pid"] == os.getpid(), "Native progress belongs to another probe/owner")
                if predicate(value):
                    return value
            owner.discover()
            time.sleep(0.02)
        raise TimeoutError("Native display progress did not reach the requested state")

    def window_id():
        values = xdo("search", "--onlyvisible", "--pid", player.pid).splitlines()
        require(bool(values), "Owned PixelWindow XID could not be found")
        return values[-1]

    def geometry():
        text = xdo("getwindowgeometry", "--shell", window_id())
        fields = dict(re.findall(r"^(X|Y|WIDTH|HEIGHT)=(-?\d+)$", text, re.MULTILINE))
        require(set(fields) == {"X", "Y", "WIDTH", "HEIGHT"}, "Incomplete native window geometry")
        return {key: int(value) for key, value in fields.items()}

    def key(name):
        xdo("windowfocus", "--sync", window_id())
        xdo("key", "--clearmodifiers", name)

    def record(name, state, **extra):
        require(state["renderer_surface_is_live"], "Renderer no longer uses SDL's live display surface")
        checks.append({"check": name, "state": state, **extra})
        write_json(output / "native-check-progress.json", {"checks": checks, "external_commands": commands})

    initial = progress(lambda value: value["pending_request"] and value["worker_alive"])
    require(initial["native_size"] == [1200, 900], "Unexpected initial native dimensions")
    # Xvfb's keyboard map varies across runners. Seed Unicode through the same
    # SDL TEXTINPUT interface tested by the source, then type ASCII externally.
    # This is input-preservation coverage, not a physical Unicode keyboard test.
    write_json(output / "control.json", {"operation": "seed_unicode", "text": "Éowen"})
    progress(lambda value: value["entry"] == "Éowen")
    xdo("windowfocus", "--sync", window_id())
    xdo("type", "--clearmodifiers", "--delay", 15, " Native Review")
    named = progress(lambda value: value["entry"] == "Éowen Native Review")
    entry = named["entry"]

    def pending(value):
        require(value["entry"] == entry and value["pending_request"] and value["worker_alive"] and not value["answers"],
                "Native display transition consumed or changed pending Unicode input")
        require(value["surface_size"] == value["native_size"] == value["window_size"], "Native and renderer dimensions disagree")

    baseline = len(named["set_mode_calls"])
    xdo("windowsize", window_id(), 980, 700)
    resized = progress(lambda value: value["surface_size"] == value["native_size"] == value["window_size"] == [980, 700])
    pending(resized)
    require(len(resized["set_mode_calls"]) == baseline, "Ordinary native resize redundantly called set_mode")
    record("native_resize_without_set_mode", resized)
    for size in ((880, 660), (1060, 760), (1120, 780)):
        xdo("windowsize", window_id(), *size)
    latest = progress(lambda value: value["surface_size"] == value["native_size"] == value["window_size"] == [1120, 780])
    pending(latest)
    require(len(latest["set_mode_calls"]) == baseline, "Rapid native resizes replayed another mode change")
    record("rapid_external_resize_batch_keeps_latest_surface", latest)
    write_json(output / "control.json", {"operation": "stale_resize_batch", "sequence": 1, "sizes": [[980, 700], [760, 560]]})
    stale = progress(lambda value: value["stale_batch_sequence"] == 1)
    pending(stale)
    require(stale["surface_size"] == [1120, 780] and len(stale["set_mode_calls"]) == baseline,
            "Explicit stale notifications replayed an old native size")
    record("synthetic_stale_notifications_after_real_resize", stale)
    xdo("windowsize", window_id(), 500, 360)
    compact = progress(lambda value: value["surface_size"] == value["native_size"] == value["window_size"] == [760, 560])
    time.sleep(0.15)
    compact = progress(lambda value: value["surface_size"] == [760, 560])
    pending(compact)
    require(len(compact["set_mode_calls"]) == baseline + 1, "Below-minimum resize was not corrected exactly once")
    record("below_minimum_corrected_once", compact)
    for cycle in range(6):
        xdo("windowmove", window_id(), *((350, 250) if cycle % 2 == 0 else (-45, -11)))
        time.sleep(0.15)
        before = geometry()
        state = progress(lambda value: not value["fullscreen"])
        calls, toggles = len(state["set_mode_calls"]), state["handled_F11"]
        key("F11")
        full = progress(lambda value: value["fullscreen"] and value["handled_F11"] == toggles + 1)
        require(full["surface_size"] == list(DESKTOP), "Fullscreen did not reach the owned virtual desktop")
        require(full["entry"] == entry and full["pending_request"], "Fullscreen changed pending input")
        key("F11")
        restored = progress(lambda value: not value["fullscreen"] and value["handled_F11"] == toggles + 2
                            and value["surface_size"] == value["native_size"] == value["window_size"] == [760, 560])
        time.sleep(0.15)
        after = geometry()
        require(before == after, "Fullscreen did not restore exact native position and dimensions")
        pending(restored)
        require(len(restored["set_mode_calls"]) == calls + 2, "Unexpected redundant modes during fullscreen return")
        record("exact_fullscreen_position_and_dimensions", restored, cycle=cycle, before=before, after=after)
    key("Return")
    exit_code = player.wait(timeout=remaining(5))
    require(exit_code == 0, "Native probe did not exit successfully after Unicode submission")
    final = json.loads((output / "probe-result.json").read_text(encoding="utf-8"))
    require(final["probe_pid"] == player.pid and final["owner_pid"] == os.getpid(), "Native result belongs to another probe/owner")
    require(final["answers"] == [entry] and final["worker_joined"] and final["normal_pygame_quit"] and not final["errors"],
            "Native probe failed to submit Unicode or close its pending worker/display")
    return {"checks": checks, "external_commands": commands, "probe_exit_code": exit_code,
            "pending_unicode_entry": entry, "fullscreen_pairs": 6, "probe_result": final}


def check_native_display(output: Path, *, timeout: float = TIMEOUT, tool_path: str | None = None,
                         manager: str = "openbox", dedicated_owner: bool = False) -> dict:
    output = output.absolute()
    # Never reuse or delete old native evidence/control files.
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "failed", "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Owned virtual-X11 source integration with dummy audio; instrumented resize checks, not public gameplay or physical hardware.",
              "errors": [], "output_directory": str(output), "historical_MIT_SHM_crash_cause_remains_unproven": True}
    owner, display, environment = None, None, None
    read_fd, write_fd = None, None
    timeout = check_timeout(timeout)
    # Reserve cleanup time inside the 90-second upper bound.
    deadline = time.monotonic() + timeout - min(22, timeout / 2)
    try:
        require(sys.platform.startswith("linux"), "Real-X11 native display checks run only on Linux")
        tools, environment = find_tools(tool_path, manager)
        report.update(tools=tools, source=source_context())
        environment.update({"SDL_VIDEODRIVER": "x11", "SDL_AUDIODRIVER": "dummy", "PYGAME_HIDE_SUPPORT_PROMPT": "1",
                            "RBS_SAVE_DIR": str(output / "saves"), "XDG_CONFIG_HOME": str(output / "config"),
                            "XDG_CACHE_HOME": str(output / "cache"), "XDG_DATA_HOME": str(output / "data")})
        owner = OwnedProcesses(output, dedicated_owner=dedicated_owner)
        read_fd, write_fd = os.pipe()
        server = owner.launch("xvfb", [tools["Xvfb"], "-displayfd", str(write_fd), "-screen", "0", "1920x1200x24",
                                       "-nolisten", "tcp", "-noreset", "-fp", "built-ins"], environment, pass_fds=(write_fd,))
        os.close(write_fd)
        write_fd = None
        display = display_number(read_fd, server, min(deadline, time.monotonic() + 8))
        os.close(read_fd)
        read_fd = None
        environment["DISPLAY"] = ":" + str(display)
        report["owned_display"] = {"number": display, "server_pid": server.pid, "allocation": "Xvfb -displayfd"}
        if manager == "openbox":
            arguments = [tools[manager], "--sm-disable"]
        else:
            arguments = [tools["dbus-run-session"], "--", tools[manager], "--compositor=off", "--sm-client-disable"]
        wm = owner.launch("window-manager", arguments, environment)
        while time.monotonic() < deadline:
            require(server.poll() is None and wm.poll() is None, "Owned Xvfb/window manager exited during startup")
            observed = subprocess.run([tools["xprop"], "-root", "_NET_SUPPORTING_WM_CHECK"], env=environment,
                                      capture_output=True, text=True, timeout=min(5, max(0.1, deadline - time.monotonic())))
            if observed.returncode == 0 and re.search(r"window id # 0x[0-9a-f]+", observed.stdout):
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("Owned window manager did not become ready")
        report["integration"] = exercise_native_window(owner, output, tools, environment, deadline)
        require(server.poll() is None and wm.poll() is None, "Owned display services exited before integration completed")
        report["source_after_integration"] = source_context()
        require(report["source"]["files"] == report["source_after_integration"]["files"],
                "Source files changed during native integration")
        report["status"] = "passed"
    except BaseException:
        report["errors"].append(traceback.format_exc())
        (output / "owner-error.log").write_text(report["errors"][-1], encoding="utf-8")
    finally:
        for descriptor in (read_fd, write_fd):
            if descriptor is not None:
                os.close(descriptor)
        if owner is not None:
            if any(role == "probe" and process.poll() is None for role, process in owner.children):
                write_json(output / "control.json", {"operation": "quit"})
                time.sleep(0.1)
            report["cleanup"] = owner.close()
            report["errors"].extend(report["cleanup"]["errors"])
        if display is not None:
            socket = Path(f"/tmp/.X11-unix/X{display}")
            lock = Path(f"/tmp/.X{display}-lock")
            report["owned_display_socket_absent"] = not socket.exists()
            report["owned_display_lock_absent"] = not lock.exists()
            if socket.exists() or lock.exists():
                report["errors"].append("Owned display socket/lock remained after server cleanup")
        if report["errors"]:
            report["status"] = "failed"
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        report["logs"] = {path.name: sha256(path) for path in sorted(output.iterdir())
                          if path.is_file() and path.suffix in {".log", ".jsonl"}}
        write_json(output / "native-display-report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=lambda value: check_timeout(float(value)), default=TIMEOUT)
    parser.add_argument("--tool-path", help="Prepend standard tool directories to PATH (optional local toolchain)")
    parser.add_argument("--window-manager", choices=("openbox", "xfwm4"), default="openbox")
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.probe:
        raise SystemExit(run_probe(arguments.output_dir.absolute()))
    report = check_native_display(arguments.output_dir, timeout=arguments.timeout,
                                  tool_path=arguments.tool_path, manager=arguments.window_manager, dedicated_owner=True)
    print(json.dumps({"status": report["status"], "report": str(arguments.output_dir / "native-display-report.json"),
                      "fullscreen_pairs": report.get("integration", {}).get("fullscreen_pairs", 0)}))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
