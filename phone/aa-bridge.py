#!/usr/bin/env python3
"""aa-bridge: wired Android Auto for Ubuntu Touch.

The car is the USB host. It talks AOAP (Android Open Accessory Protocol) to the phone
and then speaks the Android Auto protocol over two bulk endpoints. Google's Android
Auto app runs inside Waydroid, where it cannot see the USB port, but its developer
"head unit server" listens on TCP 5277 and speaks the same protocol. This daemon
joins the two:

  car --USB/AOAP--> f_accessory (/dev/usb_accessory) <--bytes--> Waydroid:5277

Gadget handling (configfs):
  * The accessory function is created inside the normal gadget g1 (managed by
    usb-moded) but not linked into its configuration. The kernel then answers the
    car's AOAP control requests and, on ACCESSORY_START, sends uevent ACCESSORY=START.
  * On that uevent we freeze usb-moded (SIGSTOP), swap g1's functions for the
    accessory function, set 18d1:2d00 and re-bind. This takes a few milliseconds.
  * When the car goes away we put g1 back exactly as it was and thaw usb-moded.

Android Auto handling:
  * The head unit server accepts ONE client per process, and stale connections crash
    it. So a fresh server is "armed" (force-stop + start the service) when the daemon
    starts and again after every session; it is never probed.
  * debug.stagefright.c2inputsurface=-1 is set when arming (needed for video).
  * Android's 'gps' test provider is registered when arming (it must exist before
    Android Auto starts the navigation app); aa-gps-bridge.py feeds real fixes during
    a session only, so the GPS receiver is off otherwise.
  * A keeper thread starts the Waydroid session after a reboot and re-arms when needed.

Android's screen on the phone:
  * For a car it has not seen before, Android Auto wants a confirmation on the phone
    ("check your phone"). The daemon watches Android's log during a session and opens
    the Android window when that happens (show_android_ui).
  * The same can be requested by hand, without root: create the file
    /run/user/<uid>/aa-show-android (see show-android.sh).

Run as root. Log goes to stdout (journal when run as a service).
"""
import fcntl, json, os, pwd, re, select, signal, socket, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = "/sys/kernel/config/usb_gadget"
NORMAL = f"{CFG}/g1"
OLD_AA = f"{CFG}/aa"
CONF = f"{NORMAL}/configs/c.1"
ACC_FUNC = f"{NORMAL}/functions/accessory.gs2"
SAVED = "/run/aa-bridge.saved"
ACC_DEV = "/dev/usb_accessory"
WAYDROID_PORT = 5277
CONNECT_TIMEOUT = 30      # seconds to wait for the head unit server
CHUNK = 16384
CAR_SILENCE_TIMEOUT = 20  # seconds without any data from the car before the session is ended
PKG = "com.google.android.projection.gearhead"
SERVICE = PKG + "/.companion.DeveloperHeadUnitNetworkService"
LXC = ["lxc-attach", "-P", "/var/lib/waydroid/lxc", "-n", "waydroid", "--clear-env", "--"]
GPS_BRIDGE = os.path.join(HERE, "aa-gps-bridge.py")
LOG_DIR = os.path.join(HERE, "diag")

# f_accessory ioctls (include/uapi/linux/usb/f_accessory.h)
# (_IOW('M', nr, char[256]): direction bits = 1)
ACCESSORY_GET_STRING = {name: (1 << 30) | (256 << 16) | (ord('M') << 8) | nr
                        for nr, name in enumerate(
                            ["manufacturer", "model", "description", "version", "uri", "serial"], 1)}

USER = "phablet"
KEEP_SESSION_LOGS = 6     # Android logs of the last sessions kept in diag/
# Android Auto log lines that mean "the user has to do something on the phone".
PHONE_PROMPT = re.compile(r"PREFLIGHT_UI_STARTING")
PHONE_PROMPT_NOTE = re.compile(r"preflight|\bfrx", re.I)     # logged, to learn what a car triggers
T0 = time.monotonic()
armed = False             # a fresh, unused head unit server is waiting
arm_lock = threading.RLock()        # arming and connecting never overlap
session_active = threading.Event()
ui_lock = threading.Lock()


def log(*a):
    print(f"[aa-bridge {time.monotonic() - T0:9.3f}]", *a, flush=True)


def write(path, value):
    with open(path, "w") as f:
        f.write(value)


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def udc_name():
    return os.listdir("/sys/class/udc")[0]


# ---------------------------------------------------------------- USB gadget
#
# The accessory function must live in the phone's ONE normal gadget (g1). Android (in
# Waydroid) watches /sys/class/android_usb/android0, which belongs to g1; Android Auto
# ends a session ~3 s after that reports "disconnected". A separate gadget would be
# android1, and android0 would stay disconnected for the whole session.

def check_no_second_gadget():
    """NEVER create or remove a second gadget on this kernel. Android's configfs code
    creates every androidN state device with dev_t 0:0, and removing a gadget calls
    device_destroy(class, 0:0), which destroys android0 (the MAIN gadget's device)
    instead of its own. The next USB connect/disconnect then panics the kernel in
    kobject_uevent_env (seen 2026-11-15). A leftover second gadget is harmless as long
    as it is left alone; it disappears with the next reboot."""
    if os.path.isdir(OLD_AA):
        log("note: old second gadget 'aa' exists; leaving it alone (gone after a reboot)")


def setup_gadget():
    """Create the accessory function inside g1 (not linked into the config yet). That
    also creates /dev/usb_accessory and makes the kernel answer the car's AOAP requests."""
    check_no_second_gadget()
    if os.path.exists(SAVED):
        log("found saved gadget state from an interrupted session; restoring")
        switch_to_normal()
    if not read(f"{NORMAL}/UDC"):
        # g1 is normally always bound. An unbound gadget (e.g. after a failed restore)
        # means no host can see the phone at all.
        time.sleep(5)
        if not read(f"{NORMAL}/UDC"):
            log("the USB gadget is not bound; asking usb-moded to rebuild it")
            usb_moded_signal(signal.SIGCONT)
            usb_moded_reapply(usb_moded_call("mode_request") or "mtp_adb")
    os.makedirs(ACC_FUNC, exist_ok=True)
    for _ in range(20):
        if os.path.exists(ACC_DEV):
            break
        time.sleep(0.1)
    log("accessory function ready" if os.path.exists(ACC_DEV) else "WARNING: no /dev/usb_accessory")


def usb_moded_signal(sig):
    """Freeze / thaw usb-moded so it does not touch g1 during a session."""
    try:
        pid = int(subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", "usb-moded"],
                                 capture_output=True, text=True).stdout.strip() or 0)
        if pid > 0:
            os.kill(pid, sig)
    except (OSError, ValueError):
        pass


def usb_moded_call(method, *args, timeout=5):
    """Call usb-moded over D-Bus (it must not be frozen). Returns the reply string or None."""
    cmd = ["gdbus", "call", "--system", "--dest", "com.meego.usb_moded", "--object-path",
           "/com/meego/usb_moded", "--method", f"com.meego.usb_moded.{method}"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip().strip("(),'")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def wait_bound(seconds):
    for _ in range(int(seconds * 5)):
        if read(f"{NORMAL}/UDC"):
            return True
        time.sleep(0.2)
    return False


def usb_moded_reapply(mode):
    """Let usb-moded rebuild its own USB configuration. Its helper daemons (umtprd, adbd)
    stop when their functions are unbound, and binding g1 by hand then fails with EBUSY;
    a mode change makes usb-moded restart them and bind the gadget itself."""
    known = (usb_moded_call("get_modes") or "").replace(" ", "").split(",")
    if mode not in known:
        mode = "mtp_adb" if "mtp_adb" in known else (known[0] if known and known[0] else "mtp_adb")
    inter = "charging_only" if mode != "charging_only" else "mtp"
    usb_moded_call("set_mode", inter)
    wait_bound(5)
    time.sleep(0.5)
    usb_moded_call("set_mode", mode)
    time.sleep(1)
    ok = wait_bound(10)
    log(f"usb-moded re-applied mode '{mode}'" + ("" if ok else " (gadget still not bound)"))
    return ok


def config_links():
    return [n for n in os.listdir(CONF) if os.path.islink(f"{CONF}/{n}")]


def bind_gadget(udc, tries=24):
    """Bind g1 to the UDC, retrying: right after an unbind the kernel can answer EBUSY."""
    err = None
    for i in range(tries):
        if read(f"{NORMAL}/UDC"):
            return True
        try:
            write(f"{NORMAL}/UDC", udc)
            if i:
                log(f"gadget bound after {i + 1} attempts")
            return True
        except OSError as e:
            err = e
            time.sleep(0.25)
    log(f"COULD NOT BIND THE USB GADGET: {err}")
    return False


def switch_to_accessory():
    mode = usb_moded_call("mode_request", timeout=2)
    usb_moded_signal(signal.SIGSTOP)
    udc = read(f"{NORMAL}/UDC") or udc_name()
    state = {"vid": read(f"{NORMAL}/idVendor"), "pid": read(f"{NORMAL}/idProduct"),
             "links": [n for n in config_links() if n != "accessory.gs2"], "udc": udc,
             "mode": mode or "mtp_adb"}
    with open(SAVED, "w") as f:
        json.dump(state, f)
    try:
        write(f"{NORMAL}/UDC", "\n")     # unbind (an empty string would write nothing)
    except OSError:
        pass
    for n in config_links():
        os.unlink(f"{CONF}/{n}")
    write(f"{NORMAL}/idVendor", "0x18d1")
    write(f"{NORMAL}/idProduct", "0x2d00")
    os.symlink(ACC_FUNC, f"{CONF}/accessory.gs2")
    bind_gadget(udc)
    log(f"gadget re-enumerated as accessory 18d1:2d00 on {udc}")


def switch_to_normal():
    try:
        with open(SAVED) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = None
    try:
        write(f"{NORMAL}/UDC", "\n")
    except OSError:
        pass
    time.sleep(0.3)                 # let blocked readers/writers of /dev/usb_accessory return
    for _ in range(10):
        try:
            os.unlink(f"{CONF}/accessory.gs2")
            break
        except FileNotFoundError:
            break
        except OSError:
            time.sleep(0.2)
    if state:
        try:
            write(f"{NORMAL}/idVendor", state["vid"])
            write(f"{NORMAL}/idProduct", state["pid"])
        except OSError as e:
            log(f"restoring the gadget ids: {e}")
    usb_moded_signal(signal.SIGCONT)
    time.sleep(0.3)
    if not usb_moded_reapply((state or {}).get("mode") or "mtp_adb"):
        # last resort: put the old function links back and bind by hand
        try:
            for n in (state or {}).get("links", []):
                if not os.path.islink(f"{CONF}/{n}"):
                    os.symlink(f"{NORMAL}/functions/{n}", f"{CONF}/{n}")
        except OSError as e:
            log(f"restoring the function links: {e}")
        bind_gadget((state or {}).get("udc") or udc_name())
    try:
        os.unlink(SAVED)
    except OSError:
        pass
    log("normal USB mode restored" if read(f"{NORMAL}/UDC") else "WARNING: USB gadget is not bound")


# ---------------------------------------------------------------- Android side

def android(*cmd, timeout=20):
    try:
        return subprocess.run(LXC + list(cmd), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def as_user(*cmd, timeout=30):
    """Run a command as the phone user inside their session (for 'waydroid' commands)."""
    uid = pwd.getpwnam(USER).pw_uid
    run = f"/run/user/{uid}"
    full = ["runuser", "-u", USER, "--", "env", f"XDG_RUNTIME_DIR={run}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={run}/bus"] + list(cmd)
    try:
        return subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def android_booted():
    r = android("/system/bin/getprop", "sys.boot_completed", timeout=8)
    return bool(r and r.returncode == 0 and r.stdout.strip() == "1")


_waydroid_note = ""


def ensure_waydroid():
    """Make sure the Waydroid session is running (start it after a reboot). True when
    Android has finished booting."""
    global _waydroid_note
    if android_booted():
        _waydroid_note = ""
        return True
    uid = pwd.getpwnam(USER).pw_uid
    if not os.path.exists(f"/run/user/{uid}/wayland-0"):
        if _waydroid_note != "nosession":
            log("the phone's graphical session is not up yet; waiting")
            _waydroid_note = "nosession"
        return False
    r = as_user("waydroid", "status", timeout=15)
    if r is None or "RUNNING" not in (r.stdout.split("\n")[0] if r.stdout else ""):
        log("starting the Waydroid session")
        as_user("systemd-run", "--user", f"--unit=waydroid-session-{int(time.time())}",
                "waydroid", "session", "start")
    for _ in range(60):
        time.sleep(3)
        if android_booted():
            as_user("waydroid", "prop", "set", "persist.waydroid.suspend", "false")
            log("Waydroid is up")
            _waydroid_note = ""
            return True
    if _waydroid_note != "noboot":
        log("Waydroid did not finish booting")
        _waydroid_note = "noboot"
    return False


def register_gps_provider():
    """Android must have an enabled 'gps' provider BEFORE Android Auto starts the
    navigation app, or Waze shows 'Location disabled'. Fixes are fed by aa-gps-bridge.py
    only during a session."""
    android("/system/bin/cmd", "location", "set-location-enabled", "true")
    android("/system/bin/cmd", "appops", "set", "root", "android:mock_location", "allow")
    android("/system/bin/cmd", "location", "providers", "add-test-provider", "gps",
            "--supportsAltitude", "--supportsSpeed", "--supportsBearing")
    android("/system/bin/cmd", "location", "providers", "set-test-provider-enabled", "gps", "true")


def android_prop(name):
    r = android("/system/bin/getprop", name, timeout=8)
    return r.stdout.strip() if r and r.returncode == 0 else ""


def refresh_android_display():
    """Make Android draw a few frames. Waydroid's compositor only looks at
    waydroid.active_apps when it composes a frame."""
    android("/system/bin/cmd", "statusbar", "expand-notifications", timeout=8)
    time.sleep(0.5)
    android("/system/bin/cmd", "statusbar", "collapse", timeout=8)
    time.sleep(0.3)


def show_android_ui(why):
    """Open Android's screen as a window on the phone. Like 'waydroid show-full-ui',
    but it first closes a window Waydroid still believes to be open: if Lomiri has
    dropped that window, a plain show request does nothing. Closing through the
    property does not remove Android tasks."""
    with ui_lock:
        if not android_booted():
            log(f"cannot show Android ({why}): Android is not running")
            return False
        if android_prop("waydroid.open_windows") not in ("", "0"):
            android("/system/bin/setprop", "waydroid.active_apps", "none")
            for _ in range(6):
                refresh_android_display()
                if android_prop("waydroid.open_windows") in ("", "0"):
                    break
        android("/system/bin/setprop", "waydroid.active_apps", "Waydroid")
        android("/system/bin/settings", "put", "global", "policy_control", "null*")
        for _ in range(6):
            refresh_android_display()
            if android_prop("waydroid.open_windows") == "1":
                log(f"Android window opened on the phone ({why})")
                return True
        log(f"could not open the Android window ({why})")
        return False


def ui_request_file():
    return f"/run/user/{pwd.getpwnam(USER).pw_uid}/aa-show-android"


def ui_requests():
    """Background: the phone user asks for the Android window by creating a file."""
    path = ui_request_file()
    while True:
        time.sleep(1)
        try:
            if not os.path.lexists(path):
                continue
            os.unlink(path)
        except OSError:
            continue
        show_android_ui("requested")


def watch_phone_prompt(stop):
    """During a session: open the Android window when Android Auto asks for something
    on the phone (first connection to a car)."""
    try:
        p = subprocess.Popen(LXC + ["/system/bin/logcat", "-T", "1", "-b", "main,system",
                                    "-v", "brief"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                             errors="replace")
    except OSError:
        return
    def closer():
        stop.wait()
        p.terminate()
    threading.Thread(target=closer, daemon=True).start()
    shown = 0.0
    seen = 0
    for line in p.stdout:
        if stop.is_set():
            break
        if seen < 12 and PHONE_PROMPT_NOTE.search(line):
            seen += 1
            log(f"Android: {line.strip()[:170]}")
        if PHONE_PROMPT.search(line) and time.monotonic() - shown > 60:   # at most once a minute
            shown = time.monotonic()
            threading.Thread(target=show_android_ui, args=("Android Auto needs a confirmation",),
                             daemon=True).start()
    p.wait()


def server_starts():
    r = android("/system/bin/logcat", "-d", "-s", "GH.DHUService")
    return r.stdout.count("Network server running") if r and r.returncode == 0 else None


def aa_alive():
    r = android("/system/bin/pidof", PKG + ":projection", timeout=8)
    return bool(r and r.returncode == 0 and r.stdout.strip())


def arm_android_auto():
    """Fresh Android Auto process with an unused head unit server. True on success."""
    global armed
    with arm_lock:
        armed = False
        if not ensure_waydroid():
            return False
        before = server_starts()
        if before is None:
            return False
        register_gps_provider()
        android("/system/bin/setprop", "debug.stagefright.c2inputsurface", "-1")
        android("/system/bin/am", "force-stop", PKG)
        time.sleep(1)
        android("/system/bin/am", "start-foreground-service", "-n", SERVICE)
        for _ in range(40):
            time.sleep(0.5)
            n = server_starts()
            if n is not None and n > before:
                armed = True
                log("Android Auto head unit server armed")
                return True
        log("head unit server did not start (is developer mode enabled in Android Auto?)")
        return False


def keeper():
    """Background: keep Waydroid running and a fresh head unit server armed, so a car
    can connect at any time (also after a reboot or if Android Auto was killed)."""
    global armed
    while True:
        time.sleep(30)
        if session_active.is_set():
            continue
        with arm_lock:
            if session_active.is_set():
                continue
            if armed and aa_alive():
                continue
            if armed:
                log("Android Auto is no longer running; arming again")
            arm_android_auto()


def save_android_log(name):
    """Keep Android's log of the last session where the phablet user can read it."""
    r = android("/system/bin/logcat", "-d", "-b", "all", timeout=30)
    if not r or r.returncode != 0:
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, name)
        with open(path, "w") as f:
            f.write(r.stdout)
        # also keep it under a dated name, so a later session does not overwrite it
        dated = os.path.join(LOG_DIR, time.strftime("aa-session-%Y%m%d-%H%M%S.txt"))
        with open(dated, "w") as f:
            f.write(r.stdout)
        old_logs = sorted(f for f in os.listdir(LOG_DIR) if f.startswith("aa-session-"))
        for f in old_logs[:-KEEP_SESSION_LOGS]:
            os.unlink(os.path.join(LOG_DIR, f))
        st = os.stat(HERE)
        for q in (path, dated, LOG_DIR):
            os.chown(q, st.st_uid, st.st_gid)
        log(f"Android log saved to {path} (copy: {os.path.basename(dated)})")
    except OSError as e:
        log(f"could not save Android log: {e}")


def waydroid_ip():
    try:
        out = subprocess.run(["waydroid", "status"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "IP address" in line:
                ip = line.split(":", 1)[1].strip()
                if ip and ip[0].isdigit():
                    return ip
    except Exception:
        pass
    return "192.168.240.112"


def connect_head_unit_server():
    with arm_lock:
        return _connect_head_unit_server()


def _connect_head_unit_server():
    global armed
    if not armed and not arm_android_auto():
        return None
    ip = waydroid_ip()
    deadline = time.time() + CONNECT_TIMEOUT
    rearmed = False
    while time.time() < deadline:
        try:
            s = socket.create_connection((ip, WAYDROID_PORT), timeout=3)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(None)
            armed = False       # this server is used up now
            log(f"connected to Android Auto head unit server at {ip}:{WAYDROID_PORT}")
            return s
        except OSError as e:
            if not rearmed:
                log(f"head unit server not reachable ({e}); arming again")
                rearmed = True
                if not arm_android_auto():
                    return None
            else:
                time.sleep(0.5)
    return None


# ---------------------------------------------------------------- session

def accessory_strings(fd):
    info = {}
    for name, req in ACCESSORY_GET_STRING.items():
        buf = bytearray(256)
        try:
            fcntl.ioctl(fd, req, buf)
            info[name] = buf.split(b"\0", 1)[0].decode(errors="replace")
        except OSError:
            pass
    return info


def pump(acc_fd, sock):
    """Copy bytes both ways until either side closes."""
    stop = threading.Event()
    stats = {"car->phone": 0, "phone->car": 0}
    last_rx = [time.monotonic()]    # a live head unit sends pings and video acks all the time

    def usb_to_tcp():
        try:
            while not stop.is_set():
                data = os.read(acc_fd, CHUNK)
                if not data:
                    time.sleep(0.01)
                    continue
                if stats["car->phone"] == 0:
                    log(f"first bytes from car: {data[:12].hex()}")
                last_rx[0] = time.monotonic()
                sock.sendall(data)
                stats["car->phone"] += len(data)
        except OSError as e:
            log(f"USB read ended: {e}")
        stop.set()

    def tcp_to_usb():
        try:
            while not stop.is_set():
                r, _, _ = select.select([sock], [], [], 0.5)
                if not r:
                    continue
                data = sock.recv(CHUNK)
                if not data:
                    log("head unit server closed the connection")
                    break
                if stats["phone->car"] == 0:
                    log(f"first bytes from phone: {data[:12].hex()}")
                view = memoryview(data)
                while view:
                    n = os.write(acc_fd, view)
                    view = view[n:]
                stats["phone->car"] += len(data)
        except OSError as e:
            log(f"USB write / TCP read ended: {e}")
        stop.set()

    for fn in (usb_to_tcp, tcp_to_usb):
        threading.Thread(target=fn, daemon=True).start()
    try:
        _pump_wait(stop, stats, last_rx)
    finally:
        stop.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        log(f"session ended, bytes {stats}")


def _pump_wait(stop, stats, last_rx):
    n = 0
    while not stop.is_set():
        stop.wait(2)
        n += 1
        if read(f"/sys/class/udc/{udc_name()}/state") in ("not attached", ""):
            log("USB cable disconnected")
            stop.set()
        elif time.monotonic() - last_rx[0] > CAR_SILENCE_TIMEOUT:
            # e.g. the head unit shut down but keeps the USB port powered
            log(f"nothing from the car for {CAR_SILENCE_TIMEOUT} s; ending the session")
            stop.set()
        elif n % 30 == 0:
            log(f"session running, bytes {stats}")


def session():
    session_active.set()
    gps = None
    watch_stop = threading.Event()
    try:
        switch_to_accessory()
        for _ in range(100):        # wait for the car to enumerate the accessory gadget
            if read(f"/sys/class/udc/{udc_name()}/state") == "configured":
                break
            time.sleep(0.1)
        log(f"gadget state: {read(f'/sys/class/udc/{udc_name()}/state')}")
        acc_fd = os.open(ACC_DEV, os.O_RDWR)
        try:
            log(f"car identifies as {accessory_strings(acc_fd)}")
            sock = connect_head_unit_server()
            if sock is None:
                log("giving up: no head unit server")
                return
            if os.path.exists(GPS_BRIDGE):
                gps = subprocess.Popen([sys.executable, "-u", GPS_BRIDGE, "--keep-provider"])
            threading.Thread(target=watch_phone_prompt, args=(watch_stop,), daemon=True).start()
            pump(acc_fd, sock)
        finally:
            os.close(acc_fd)
    finally:
        watch_stop.set()
        if gps is not None:
            gps.terminate()         # SIGTERM = clean stop of the location client
            try:
                gps.wait(timeout=12)
            except subprocess.TimeoutExpired:
                gps.kill()
        switch_to_normal()
        session_active.clear()


class AccessoryMonitor:
    """Kernel uevent listener, kept open for the daemon's whole life so that no
    ACCESSORY=START is missed between sessions."""

    def __init__(self):
        self.p = subprocess.Popen(
            ["udevadm", "monitor", "--kernel", "--property", "--subsystem-match=misc"],
            stdout=subprocess.PIPE, text=True)

    def wait_for_start(self):
        for line in self.p.stdout:
            if line.strip() == "ACCESSORY=START":
                return True
        return False            # monitor died


def main():
    if os.geteuid() != 0:
        sys.exit("run as root")
    def on_term(*_):                # service stop: unwind like Ctrl-C so the gadget is restored
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_term)
    setup_gadget()
    monitor = AccessoryMonitor()
    time.sleep(0.5)
    arm_android_auto()
    threading.Thread(target=keeper, daemon=True).start()
    threading.Thread(target=ui_requests, daemon=True).start()
    try:
        while True:
            log("waiting for a car (AOAP handshake) ...")
            if not monitor.wait_for_start():
                sys.exit("udevadm monitor exited")
            log("car sent ACCESSORY_START")
            try:
                session()
            except Exception as e:
                log(f"session error: {e!r}")
                session_active.clear()
            save_android_log("aa-last-session.txt")
            time.sleep(1)
            arm_android_auto()
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    main()
