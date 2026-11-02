"""Minimal MAME-output listener for testing xemu-chihiro-outputs on Windows.

Acts like MameHooker: owns a hidden window, listens for MAMEOutputStart
broadcasts, registers with the emulator, asks the names of ids it sees and
prints every MAMEOutputUpdateState. Also (optionally) connects to the TCP
server and prints its lines.

    python -I outputs_listener.py [--tcp 8000]
"""
import ctypes
import ctypes.wintypes as wt
import socket
import sys
import threading
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, wt.HMENU,
                                   wt.HINSTANCE, wt.LPVOID]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]

WM_COPYDATA = 0x004A
WM_DESTROY = 0x0002
HWND_BROADCAST = 0xFFFF
CLIENT_ID = 0x5EAD

om = {}
for name in ("MAMEOutputStart", "MAMEOutputStop", "MAMEOutputUpdateState",
             "MAMEOutputRegister", "MAMEOutputUnregister",
             "MAMEOutputGetIDString"):
    om[name] = user32.RegisterWindowMessageW(name)

emu_hwnd = None
names = {}


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t),
                ("cbData", wt.DWORD),
                ("lpData", ctypes.c_void_p)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT,
                             wt.WPARAM, wt.LPARAM)


def ts():
    return time.strftime("%H:%M:%S") + ".%03d" % int((time.time() % 1) * 1000)


def ask_name(my_hwnd, oid):
    user32.PostMessageW(emu_hwnd, om["MAMEOutputGetIDString"], my_hwnd, oid)


def wndproc(hwnd, msg, wp, lp):
    global emu_hwnd
    if msg == om["MAMEOutputStart"]:
        emu_hwnd = wp
        print(ts(), "MAMEOutputStart from hwnd 0x%X -> registering" % wp)
        user32.PostMessageW(emu_hwnd, om["MAMEOutputRegister"], hwnd,
                            CLIENT_ID)
        ask_name(hwnd, 0)
        return 0
    if msg == om["MAMEOutputStop"]:
        print(ts(), "MAMEOutputStop from hwnd 0x%X" % wp)
        return 0
    if msg == om["MAMEOutputUpdateState"]:
        oid, value = int(wp), int(lp)
        if oid not in names and emu_hwnd:
            names[oid] = "?"
            ask_name(hwnd, oid)
        print(ts(), "update id=%d %s = %d" % (oid, names.get(oid, "?"),
                                              value))
        return 0
    if msg == WM_COPYDATA:
        cd = ctypes.cast(lp, ctypes.POINTER(COPYDATASTRUCT)).contents
        if cd.dwData == 1 and cd.cbData >= 4:
            raw = ctypes.string_at(cd.lpData, cd.cbData)
            oid = int.from_bytes(raw[:4], "little")
            name = raw[4:].split(b"\0")[0].decode(errors="replace")
            if oid == 0:
                print(ts(), "ROM name = '%s'" % name)
            else:
                names[oid] = name
                print(ts(), "id %d is '%s'" % (oid, name))
        return 1
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


def tcp_thread(port):
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(1)
            continue
        print(ts(), "TCP connected on", port)
        s.settimeout(None)
        buf = b""
        try:
            while True:
                data = s.recv(4096)
                if not data:
                    break
                buf += data
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    print(ts(), "TCP:", line.decode(errors="replace"))
        except OSError:
            pass
        print(ts(), "TCP closed")
        s.close()
        time.sleep(1)


def main():
    port = None
    if "--tcp" in sys.argv:
        port = int(sys.argv[sys.argv.index("--tcp") + 1])
    proc = WNDPROC(wndproc)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = "XemuOutputsListener"
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "listener", 0, 0, 0, 1,
                                  1, None, None, wc.hInstance, None)
    print(ts(), "listener window 0x%X; waiting for MAMEOutputStart "
          "(start this before the game boots)" % hwnd)
    if port:
        threading.Thread(target=tcp_thread, args=(port,), daemon=True).start()
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
