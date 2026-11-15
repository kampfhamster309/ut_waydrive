#!/usr/bin/env python3
"""aa-gps-bridge: give Android apps in Waydroid (Waze, Maps ...) the phone's real position.

Waydroid has no GNSS HAL, so Android has no location source. This daemon

  1. reads fixes from Ubuntu Touch's location service through a small headless QML
     client (gps/pos.qml, QtPositioning "lomiri" source), run as the phablet user, and
  2. injects them into Android as a test provider named "gps", through one long-lived
     root shell inside the container:
         cmd location providers set-test-provider-location gps --location LAT,LON --accuracy M

Limits: the shell command carries position and accuracy only, not speed or bearing.

Run as root:  python3 aa-gps-bridge.py [--keep-provider]   (Ctrl-C / SIGTERM stops it cleanly)
--keep-provider leaves the Android test provider registered on exit (used by aa-bridge.py).
"""
import json, os, pwd, signal, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
QML = os.path.join(HERE, "gps", "pos.qml")
STOP_FILE = "/tmp/aa-gps-stop"          # pos.qml polls this and exits cleanly when it appears
USER = "phablet"
LXC = ["lxc-attach", "-P", "/var/lib/waydroid/lxc", "-n", "waydroid", "--clear-env", "--"]
MIN_INTERVAL = 1.0                       # seconds between injections

stop = threading.Event()


def log(*a):
    print("[aa-gps]", *a, flush=True)


class AndroidShell:
    """One persistent root shell in the container; re-created when Waydroid restarts."""

    def __init__(self):
        self.p = None
        self.lock = threading.Lock()

    def alive(self):
        return self.p is not None and self.p.poll() is None

    def open(self):
        with self.lock:
            if self.alive():
                return True
            return self._open()

    def _open(self):
        self.p = subprocess.Popen(LXC + ["/system/bin/sh"], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        setup = [
            "cmd location set-location-enabled true",
            "cmd appops set root android:mock_location allow",
            "cmd location providers add-test-provider gps --supportsAltitude --supportsSpeed --supportsBearing",
            "cmd location providers set-test-provider-enabled gps true",
        ]
        self.send("\n".join(setup))
        time.sleep(1.5)
        if not self.alive():
            self.p = None
            return False
        log("Android test provider 'gps' ready")
        return True

    def send(self, line):
        try:
            self.p.stdin.write(line + "\n")
            self.p.stdin.flush()
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def close(self, remove_provider=True):
        if self.alive():
            if remove_provider:
                self.send("cmd location providers remove-test-provider gps")
            self.send("exit")
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.p = None


def start_reader():
    """Start the QML location client as the phablet user; returns the Popen."""
    try:
        os.unlink(STOP_FILE)
    except FileNotFoundError:
        pass
    uid = pwd.getpwnam(USER).pw_uid
    run = f"/run/user/{uid}"
    cmd = ["runuser", "-u", USER, "--", "env", f"XDG_RUNTIME_DIR={run}",
           f"DBUS_SESSION_BUS_ADDRESS=unix:path={run}/bus", "QT_QPA_PLATFORM=offscreen",
           "QML_XHR_ALLOW_FILE_READ=1", "qmlscene", QML]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def stop_reader(p):
    """Ask pos.qml to stop its PositionSource and quit; kill only as a last resort."""
    if p.poll() is None:
        with open(STOP_FILE, "w") as f:
            f.write("stop\n")
        os.chmod(STOP_FILE, 0o644)
        try:
            p.wait(timeout=6)
        except subprocess.TimeoutExpired:
            log("reader did not exit on request, terminating it")
            p.terminate()
    try:
        os.unlink(STOP_FILE)
    except FileNotFoundError:
        pass


def main():
    if os.geteuid() != 0:
        sys.exit("run as root")
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    shell = AndroidShell()
    reader = start_reader()
    log("reading location from Ubuntu Touch ...")
    last_sent = 0.0
    count = 0
    warned = False

    def read_loop():
        nonlocal last_sent, count, warned
        for line in reader.stderr:
            if stop.is_set():
                break
            line = line.strip()
            if line.startswith("qml: ERR"):
                log("location source error:", line[8:].strip())
                continue
            if not line.startswith("qml: POS "):
                continue
            now = time.monotonic()
            if now - last_sent < MIN_INTERVAL:
                continue            # the source reports position/speed/heading changes separately
            try:
                f = json.loads(line[9:])
            except ValueError:
                continue
            if not shell.alive() and not shell.open():
                if not warned:
                    log("Waydroid is not running; waiting for it")
                    warned = True
                last_sent = now + 4     # retry in ~5 s
                continue
            warned = False
            acc = f.get("acc") or 20
            ok = shell.send("cmd location providers set-test-provider-location gps "
                            f"--location {f['lat']:.7f},{f['lon']:.7f} --accuracy {acc:.1f}")
            if not ok:
                shell.close(remove_provider=False)
                continue
            last_sent = now
            count += 1
            if count == 1:
                log("first fix injected into Android")
            elif count % 300 == 0:
                log(f"{count} fixes injected")

    t = threading.Thread(target=read_loop, daemon=True)
    t.start()
    while not stop.is_set():
        # Register the provider as soon as Waydroid is up, even before the first fix: apps
        # that start while Android has no enabled GPS provider report "location disabled".
        if not shell.alive() and shell.open():
            warned = False
        if reader.poll() is not None:
            log("location reader exited; restarting in 5 s")
            if stop.wait(5):
                break
            reader = start_reader()
            t = threading.Thread(target=read_loop, daemon=True)
            t.start()
        stop.wait(1)

    log("stopping")
    stop_reader(reader)
    shell.close(remove_provider="--keep-provider" not in sys.argv)
    log(f"stopped after {count} fixes")


if __name__ == "__main__":
    main()
