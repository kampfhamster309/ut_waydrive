#!/usr/bin/env python3
"""waydroid-volume-sync: keep Ubuntu Touch's and Android's (Waydroid) volume in step.

Android's sound reaches the phone as one PulseAudio stream without a role, so Ubuntu
Touch's volume and its silent mode do not apply to it. This daemon copies the settings
instead; Android then attenuates its own sound.

There is one volume: the one Ubuntu Touch's slider shows (the volume keys change it).

  Ubuntu Touch volume       <->  Android media, ring/notification and alarm volume
  Ubuntu Touch silent mode   ->  Android ring/notification volume 0 (media keeps playing)
  Ubuntu Touch mute          ->  Android ring/notification and media volume 0

Moving any of Android's three sliders sets Ubuntu Touch's volume, and the other two
follow. (Ubuntu Touch itself keeps a volume per role and shows the one in use; mapping
Android's media volume to the "multimedia" role alone would leave it unreachable from
the slider, because Android's stream never makes that role the active one.)

Run as root (it needs a shell inside the container). The Ubuntu Touch side runs as the
phone user in a helper process (this file with --host-helper), which talks to the sound
indicator over D-Bus.

While the relay has a car session (file /run/aa-bridge.session) nothing is synced, because
Android's volume commands then act on the car's audio route.
"""
import json, os, pwd, re, subprocess, sys, threading, time

USER = "phablet"
LXC = ["lxc-attach", "-P", "/var/lib/waydroid/lxc", "-n", "waydroid", "--clear-env", "--"]
SESSION_FLAG = "/run/aa-bridge.session"
RING, MUSIC, ALARM = 2, 3, 4
MAXIMUM = {RING: 7, MUSIC: 15, ALARM: 7}
MINIMUM = {RING: 0, MUSIC: 0, ALARM: 1}
NAME = {RING: "ring", MUSIC: "media", ALARM: "alarm"}
OUR_CALLER = "com.android.server.media"    # what 'cmd media_session volume' reports as caller
T0 = time.monotonic()


def log(*a):
    print(f"[volume-sync {time.monotonic() - T0:8.1f}]", *a, flush=True)


# ------------------------------------------------------------ Ubuntu Touch side (helper)

def host_helper():
    """Runs as the phone user. Prints one JSON line with the whole state whenever it
    changes; reads 'set <0..1>' lines on stdin."""
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    ACTIONS = "org.gtk.Actions"
    IND = ("org.ayatana.indicator.sound", "/org/ayatana/indicator/sound")
    KEYS = {"volume": float, "silent-mode": bool, "mute": bool}
    session = dbus.SessionBus()
    state = {"volume": None, "silent-mode": False, "mute": False}

    def emit():
        print(json.dumps({"volume": state["volume"], "silent": state["silent-mode"],
                          "mute": state["mute"]}), flush=True)

    def take(key, value):
        value = KEYS[key](value)
        if state[key] != value:
            state[key] = value
            return True
        return False

    def refresh(*_):
        changed = False
        try:
            ind = session.get_object(*IND)
            for key in KEYS:
                _, _, st = ind.Describe(key, dbus_interface=ACTIONS)
                if len(st):
                    changed |= take(key, st[0])
        except dbus.DBusException:
            return
        if changed:
            emit()

    def on_actions_changed(removed, enabled, states, added):
        changed = False
        for key in KEYS:
            if key in states:
                changed |= take(key, states[key])
        if changed:
            emit()

    def on_stdin(source, condition):
        line = sys.stdin.readline()
        if not line:
            loop.quit()
            return False
        parts = line.split()
        if len(parts) == 2 and parts[0] == "set":
            value = min(1.0, max(0.0, float(parts[1])))
            try:
                session.get_object(*IND).SetState(
                    "volume", dbus.Double(value, variant_level=1),
                    dbus.Dictionary(signature="sv"), dbus_interface=ACTIONS)
            except dbus.DBusException:
                pass
        return True

    session.add_signal_receiver(on_actions_changed, signal_name="Changed",
                                dbus_interface=ACTIONS, path=IND[1])
    refresh()
    if state["volume"] is None:
        emit()
    loop = GLib.MainLoop()
    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, on_stdin)
    GLib.timeout_add_seconds(30, lambda: (refresh(), True)[1])     # safety net
    loop.run()


# ------------------------------------------------------------------ Android side (root)

def android(*cmd, timeout=15):
    try:
        return subprocess.run(LXC + list(cmd), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def android_booted():
    r = android("/system/bin/getprop", "sys.boot_completed", timeout=8)
    return bool(r and r.returncode == 0 and r.stdout.strip() == "1")


def android_get(stream):
    r = android("/system/bin/cmd", "media_session", "volume", "--stream", str(stream), "--get")
    m = re.search(r"volume is (\d+) in range", r.stdout) if r and r.returncode == 0 else None
    return int(m.group(1)) if m else None


def android_set(stream, index):
    r = android("/system/bin/cmd", "media_session", "volume", "--stream", str(stream),
                "--set", str(index))
    return bool(r and r.returncode == 0)


class Sync:
    def __init__(self):
        self.lock = threading.Lock()
        self.ut = None                  # last state line from the helper
        self.android = {}               # stream -> index, as far as known
        self.echo = []                  # (value we wrote to Ubuntu Touch, time)
        self.own = []                   # (stream, index, time) of our own writes to Android
        self.helper = None
        self.wake = threading.Event()
        self.in_session = os.path.exists(SESSION_FLAG)

    def silenced(self, stream):
        return self.ut["mute"] and stream != ALARM or (stream == RING and self.ut["silent"])

    # what Android should have for the current Ubuntu Touch state
    def target(self, stream):
        ut = self.ut
        if ut is None or ut.get("volume") is None:
            return None
        if self.silenced(stream):
            return 0
        value = ut["volume"]
        index = round(value * MAXIMUM[stream])
        if value > 0.001:
            index = max(1, index)
        return max(MINIMUM[stream], index)

    def start_helper(self):
        uid = pwd.getpwnam(USER).pw_uid
        run = f"/run/user/{uid}"
        while not os.path.exists(f"{run}/bus") or not os.path.exists(f"{run}/pulse/native"):
            time.sleep(5)
        self.helper = subprocess.Popen(
            ["runuser", "-u", USER, "--", "env", f"XDG_RUNTIME_DIR={run}",
             f"DBUS_SESSION_BUS_ADDRESS=unix:path={run}/bus",
             sys.executable, "-u", os.path.abspath(__file__), "--host-helper"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self.read_helper, daemon=True).start()

    def read_helper(self):
        for line in self.helper.stdout:
            try:
                state = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                self.ut = state
            self.wake.set()
        log("Ubuntu Touch helper ended")
        os._exit(1)                     # the service that started us starts us again

    def set_ut(self, value):
        with self.lock:
            self.echo.append((value, time.monotonic()))
        try:
            self.helper.stdin.write(f"set {value:.4f}\n")
            self.helper.stdin.flush()
        except OSError:
            pass

    def is_echo(self, value):
        """True when Ubuntu Touch's volume is one we wrote a moment ago, i.e. the change
        came from Android. While a slider is dragged in Android several are under way."""
        now = time.monotonic()
        with self.lock:
            self.echo = [e for e in self.echo if now - e[1] < 3]
            return any(abs(value - e[0]) < 0.005 for e in self.echo)

    def ut_to_android(self, why, source=None):
        """Write Ubuntu Touch's state to Android where it differs. 'source' is the
        Android stream a change came from; it is left alone."""
        if self.in_session or self.ut is None or self.ut.get("volume") is None:
            return
        from_android = self.is_echo(self.ut["volume"])
        for stream in (RING, MUSIC, ALARM):
            want = self.target(stream)
            if want is None or stream == source:
                continue
            if from_android and stream == self.last_source and not self.silenced(stream):
                continue                # the slider that is being moved in Android
            have = self.android.get(stream)
            if have is None:
                have = android_get(stream)
                if have is None:
                    return              # Android is not answering
                self.android[stream] = have
            if have != want:
                self.own.append((stream, want, time.monotonic()))
                if android_set(stream, want):
                    log(f"{why}: Android {NAME[stream]} volume {have} -> {want} of {MAXIMUM[stream]}")
                    self.android[stream] = want

    last_source = None

    def android_event(self, stream, index, caller):
        """Android's volume changed (volume_changed event)."""
        if stream not in MAXIMUM:
            return
        now = time.monotonic()
        self.own = [o for o in self.own if now - o[2] < 5]
        mine = [o for o in self.own if o[0] == stream and o[1] == index]
        if mine or caller == OUR_CALLER:
            # The echo of one of our own writes. While a slider is dragged, Ubuntu
            # Touch has usually moved on by the time it arrives; it must never be
            # taken for a change made in Android.
            if mine:
                self.own.remove(mine[0])
            return
        self.android[stream] = index
        if self.in_session or self.ut is None or self.ut.get("volume") is None:
            return
        if index == self.target(stream) or self.silenced(stream):
            return                      # already in step, or Ubuntu Touch is silenced
        value = index / MAXIMUM[stream]
        log(f"Android {NAME[stream]} volume set to {index} of {MAXIMUM[stream]}: "
            f"Ubuntu Touch volume -> {round(value * 100)}%")
        self.last_source = stream
        self.set_ut(value)

    def watch_android(self):
        """Follow Android's event log for volume changes; restarts with Android."""
        pattern = re.compile(r"volume_changed.*\[(\d+),(-?\d+),(-?\d+),(\d+),([^\]]*)\]")
        while True:
            if not android_booted():
                time.sleep(10)
                continue
            self.android.clear()
            self.wake.set()             # Android (re)started: write our state to it
            try:
                p = subprocess.Popen(LXC + ["/system/bin/logcat", "-b", "events", "-T", "1",
                                            "-v", "brief", "-s", "volume_changed"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, errors="replace")
            except OSError:
                time.sleep(10)
                continue
            for line in p.stdout:
                m = pattern.search(line)
                if m:
                    self.android_event(int(m.group(1)), int(m.group(3)), m.group(5).strip())
            p.wait()
            time.sleep(5)

    def run(self):
        self.start_helper()
        threading.Thread(target=self.watch_android, daemon=True).start()
        log("running")
        while True:
            fired = self.wake.wait(2)
            session = os.path.exists(SESSION_FLAG)
            if session != self.in_session:
                self.in_session = session
                log("car session: sync paused" if session else "car session over: sync resumed")
                if not session:
                    self.android.clear()
                    fired = True
            if not fired:
                continue
            time.sleep(0.15)            # let a slider drag settle
            self.wake.clear()
            self.ut_to_android("Ubuntu Touch")


def main():
    if "--host-helper" in sys.argv:
        host_helper()
        return
    if os.geteuid() != 0:
        sys.exit("run as root")
    Sync().run()


if __name__ == "__main__":
    main()
