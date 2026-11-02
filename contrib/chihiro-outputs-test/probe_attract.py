"""Watch the status/ammo bytes of a game through its whole attract cycle
(title and demo play) without touching it, to see what the demo does.

    python probe_attract.py vc3|hotd3|gs [boot_wait] [watch_seconds]
"""
import sys
import time

from xemudrv import Xemu

profile = sys.argv[1]
boot_wait = int(sys.argv[2]) if len(sys.argv) > 2 else 60
watch = int(sys.argv[3]) if len(sys.argv) > 3 else 150
images = {
    "vc3": r"D:\Xemu Chihiro\Virtua Cop 3.bin",
    "hotd3": r"D:\Xemu Chihiro\The House of the Dead 3.bin",
    "gs": r"D:\Xemu Chihiro\Ghost Squad.bin",
}
# name -> (va, n)
PROBES = {
    "vc3": {"mode(-4..)": (0x003F3F64, 4), "P1 status": (0x003F3F68, 1), "P1 life": (0x003F3F74, 1),
            "P2 status": (0x003F4018, 1), "P2 life": (0x003F4024, 1),
            "P1 ammo": (0x003DE432, 1), "P2 ammo": (0x003DE50A, 1)},
    "hotd3": {"P1 status": (0x00276708, 1), "P2 status": (0x00276934, 1), "P1 life": (0x00276714, 1),
              "P2 life": (0x00276940, 1), "P1 ammo": (0x00276760, 1), "P2 ammo": (0x0027698C, 1),
              "credits": (0x004CBA38, 1)},
    "gs": {"P1 status": (0x00465A28, 1), "P2 status": (0x00465BD4, 1), "credits": (0x004B9EA0, 1),
           "lifeptr P1": (0x00465B14, 4), "ammoptr": (0x00451828, 4)},
}[profile]
x = Xemu(images[profile], profile, "attract")
try:
    x.say("monitor %s" % x.connect())
    time.sleep(boot_wait)
    last = {}
    t0 = time.time()
    shot = 0
    while time.time() - t0 < watch:
        line = []
        for name, (va, n) in PROBES.items():
            v = x.read(va, n)
            s = v.hex(" ") if v else "--"
            if last.get(name) != s:
                line.append("%s=%s" % (name, s))
                last[name] = s
        if line:
            x.say("t+%3ds " % (time.time() - t0) + "  ".join(line))
        if int(time.time() - t0) // 30 > shot:
            shot += 1
            x.find_window()
            x.screenshot("t%03d" % int(time.time() - t0))
        time.sleep(1.0)
finally:
    x.stop()
