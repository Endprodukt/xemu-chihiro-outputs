"""Shared driver for xemu-chihiro-outputs tests on this PC: test toml, xemu
with a monitor, keys, screenshots, memory dumps."""
import ctypes
import ctypes.wintypes as wt
import os
import re
import shutil
import socket
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOML = r"C:\Users\ocare\AppData\Roaming\xemu\xemu\xemu.toml"
XEMU = r"D:\Xemu Chihiro\xemu.exe"
RAM = 128 * 1024 * 1024
user32 = ctypes.windll.user32
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]


def set_key(text, section, key, value):
    sec_re = re.compile(r"^\[" + re.escape(section) + r"\]\s*$", re.M)
    m = sec_re.search(text)
    if not m:
        return text.rstrip("\n") + "\n\n[%s]\n%s = %s\n" % (section, key, value)
    start = m.end()
    nxt = re.compile(r"^\[", re.M).search(text, start)
    end = nxt.start() if nxt else len(text)
    body = text[start:end]
    key_re = re.compile(r"^" + re.escape(key) + r"\s*=.*$", re.M)
    if key_re.search(body):
        body = key_re.sub("%s = %s" % (key, value), body, count=1)
    else:
        body = "\n%s = %s" % (key, value) + body
    return text[:start] + body + text[end:]


class Xemu:
    def __init__(self, image, profile, tag, extra_toml=(), pointer="mouse",
                 network=False):
        self.image, self.profile = image, profile
        self.stamp = time.strftime("%Y%m%d-%H%M%S")
        self.log_dir = os.path.join(HERE, "%s-%s-%s" % (tag, profile, self.stamp))
        os.makedirs(self.log_dir)
        self.backup = TOML + ".bak-%s-%s" % (tag, self.stamp)
        shutil.copy2(TOML, self.backup)
        t = open(TOML, encoding="utf-8").read()
        t = set_key(t, "display.window", "fullscreen_on_startup", "false")
        t = set_key(t, "display.window", "fullscreen_exclusive", "false")
        t = set_key(t, "display.window", "startup_size", "'1280x960'")
        t = set_key(t, "chihiro.outputs", "enable", "true")
        t = set_key(t, "chihiro.outputs", "network", "true" if network else "false")
        t = set_key(t, "chihiro.jvs." + profile, "trigger", "44")   # Space
        t = set_key(t, "chihiro.jvs." + profile, "reload", "21")    # R
        t = set_key(t, "chihiro.jvs", "profile", "'%s'" % profile)
        t = set_key(t, "chihiro.jvs", "pointer_device", "'%s'" % pointer)
        t = set_key(t, "chihiro.settings", "freeplay", "true")
        t = set_key(t, "chihiro.settings", "lightgun_mode", "false")
        for sec, k, v in extra_toml:
            t = set_key(t, sec, k, v)
        open(TOML, "w", encoding="utf-8", newline="\n").write(t)
        self.xemu_log = open(os.path.join(self.log_dir, "xemu-stderr.log"), "w")
        self.proc = subprocess.Popen(
            [XEMU, "-dvd_path", image, "-monitor",
             "tcp:127.0.0.1:4444,server,nowait"],
            cwd=os.path.dirname(XEMU), stdout=self.xemu_log,
            stderr=subprocess.STDOUT)
        self.mon = None
        self.hwnd = None
        self.say("xemu pid %d, %s" % (self.proc.pid, image))

    def say(self, msg):
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    # ---- monitor
    def connect(self):
        for _ in range(30):
            try:
                self.mon = socket.create_connection(("127.0.0.1", 4444), timeout=5)
                self.mon.settimeout(2)
                time.sleep(0.5)
                try:
                    self.mon.recv(65536)
                except socket.timeout:
                    pass
                return True
            except OSError:
                time.sleep(1)
        return False

    def cmd(self, cmd, wait=20):
        self.mon.sendall((cmd + "\n").encode())
        out = b""
        t0 = time.time()
        while time.time() - t0 < wait:
            try:
                chunk = self.mon.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            out += chunk
            if out.rstrip().endswith(b"(qemu)"):
                break
        return out.decode(errors="replace")

    def read(self, va, n):
        """n bytes at a guest virtual address, or None."""
        out = self.cmd("x/%dxb 0x%08X" % (n, va))
        vals = re.findall(r"0x([0-9a-fA-F]{2})\b", out)
        if len(vals) < n:
            return None
        return bytes(int(v, 16) for v in vals[-n:])

    def dump(self, name):
        path = os.path.join(self.log_dir, name + ".bin").replace("\\", "/")
        t0 = time.time()
        out = self.cmd("pmemsave 0 %d %s" % (RAM, path), wait=60)
        time.sleep(0.2)
        ok = os.path.exists(path) and os.path.getsize(path) == RAM
        self.say("dump %-10s %s (%.1fs)%s" % (name, "ok" if ok else "FAILED",
                                              time.time() - t0,
                                              "" if ok else " " + out.strip()[-200:]))
        return path if ok else None

    # ---- keys
    SC = {"1": 0x02, "2": 0x03, "5": 0x06, "space": 0x39, "r": 0x13,
          "alt": 0x38, "o": 0x18, "p": 0x19, "esc": 0x01}

    def key(self, name, down):
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _U(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
            _anonymous_ = ("u",)
            _fields_ = [("type", wt.DWORD), ("u", _U)]
        inp = INPUT(type=1)
        inp.ki = KEYBDINPUT(0, self.SC[name], 0x0008 | (0 if down else 0x0002), 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def tap(self, name, hold=0.08):
        self.key(name, True)
        time.sleep(hold)
        self.key(name, False)

    def click(self, down):
        """Left mouse button, for a trigger bound to the mouse."""
        user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)

    def find_window(self):
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(h, lp):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == self.proc.pid and user32.IsWindowVisible(h):
                n = user32.GetWindowTextLengthW(h)
                if n > 0:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(h, buf, n + 1)
                    if "MAMEOutput" not in buf.value:
                        found.append(h)
            return True
        user32.EnumWindows(cb, 0)
        self.hwnd = found[0] if found else None
        return self.hwnd

    def client_rect(self):
        r = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        p = wt.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(p))
        return p.x, p.y, r.right, r.bottom

    def focus(self, aim=(0.5, 0.55)):
        if not self.find_window():
            self.say("no xemu window")
            return
        self.tap("alt", 0.02)
        user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.3)
        x, y, w, h = self.client_rect()
        cx, cy = x + int(w * aim[0]), y + int(h * aim[1])
        user32.SetCursorPos(cx - 8, cy - 8)
        time.sleep(0.1)
        user32.SetCursorPos(cx, cy)
        time.sleep(0.2)

    def aim(self, fx, fy):
        x, y, w, h = self.client_rect()
        user32.SetCursorPos(x + int(w * fx), y + int(h * fy))
        time.sleep(0.15)

    def screenshot(self, name):
        if not self.hwnd and not self.find_window():
            return None
        x, y, w, h = self.client_rect()
        path = os.path.join(self.log_dir, name + ".png")
        ps = (
            "Add-Type -AssemblyName System.Drawing; "
            "$b = New-Object System.Drawing.Bitmap(%d, %d); "
            "$g = [System.Drawing.Graphics]::FromImage($b); "
            "$g.CopyFromScreen(%d, %d, 0, 0, $b.Size); "
            "$b.Save('%s', [System.Drawing.Imaging.ImageFormat]::Png)"
            % (w, h, x, y, path.replace("'", "''")))
        subprocess.call(["powershell", "-NoProfile", "-Command", ps],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.say("screenshot %s" % name)
        return path

    def stop(self):
        subprocess.call(["taskkill", "/PID", str(self.proc.pid), "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        self.xemu_log.close()
        shutil.copy2(self.backup, TOML)
        self.say("xemu stopped, toml restored; logs in " + self.log_dir)
