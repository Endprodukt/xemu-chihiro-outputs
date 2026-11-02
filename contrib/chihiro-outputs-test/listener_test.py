"""Full output test of one game with the MAME-output listener: boot, get into
play, shoot, empty the magazine, reload, shoot again; print what arrived.

    python listener_test.py vc3|hotd3|gs [boot_wait]
"""
import os
import subprocess
import sys
import time

from xemudrv import Xemu, HERE

profile = sys.argv[1]
boot_wait = int(sys.argv[2]) if len(sys.argv) > 2 else 75
images = {
    "vc3": r"D:\Xemu Chihiro\Virtua Cop 3.bin",
    "hotd3": r"D:\Xemu Chihiro\The House of the Dead 3.bin",
    "gs": r"D:\Xemu Chihiro\Ghost Squad.bin",
}
extra = []
if profile == "gs":
    # the action button (o) and the mode change (p) on keys, to skip the intro
    extra = [("chihiro.jvs.gs", "body_button", "18"), ("chihiro.jvs.gs", "change", "19")]
x = Xemu(images[profile], profile, "listen", network=True, extra_toml=extra)
listener_log = open(os.path.join(x.log_dir, "listener.log"), "w")
listener = subprocess.Popen([sys.executable, "-I",
                             os.path.join(HERE, "outputs_listener.py"),
                             "--tcp", "8000"],
                            stdout=listener_log, stderr=subprocess.STDOUT)


def note(msg):
    x.say(msg)
    listener_log.write(time.strftime("%H:%M:%S") + ".000 DRIVER: " + msg + "\n")
    listener_log.flush()


def shots(n, gap=0.45):
    for _ in range(n):
        x.tap("space", 0.1)
        time.sleep(gap)


def reload():
    x.key("r", True)
    time.sleep(0.3)
    x.tap("space")
    time.sleep(0.5)
    x.tap("space")
    time.sleep(0.2)
    x.key("r", False)


try:
    x.say("monitor %s" % x.connect())
    time.sleep(boot_wait)
    x.focus()
    x.screenshot("01_attract")
    x.tap("1", 0.15)
    time.sleep(1)
    x.tap("1", 0.15)
    note("Start pressed")
    if profile == "vc3":
        time.sleep(4)
        x.focus()
        x.tap("space", 0.1)                      # mission select
        note("mission chosen, skipping the briefing")
        for i in range(10):
            time.sleep(4)
            x.tap("1", 0.15)
        time.sleep(3)
    elif profile == "hotd3":
        time.sleep(3)
        x.tap("1", 0.15)                         # skip the intro
        note("intro skipped")
        time.sleep(10)
    else:
        time.sleep(3)
        x.tap("1", 0.15)                         # skip the tutorial
        time.sleep(5)
        x.focus()
        x.tap("space", 0.1)                      # mission select
        note("mission chosen; skipping the intro with the action button")
        for i in range(6):
            time.sleep(4)
            x.tap("o", 0.15)
            time.sleep(0.5)
            x.tap("p", 0.15)
        time.sleep(6)
    x.focus()
    x.screenshot("02_in_play")
    note("12 shots")
    shots(12)
    time.sleep(1.5)
    x.screenshot("03_after_12_shots")
    note("reload")
    reload()
    time.sleep(1.5)
    x.screenshot("04_after_reload")
    note("5 shots")
    shots(5)
    time.sleep(1.5)
    x.screenshot("05_after_5_more")
    note("idle 6s")
    time.sleep(6)
finally:
    x.stop()
    listener.terminate()
    listener_log.close()

print("==== xemu stderr: outputs lines")
for line in open(os.path.join(x.log_dir, "xemu-stderr.log"), errors="replace"):
    if "Chihiro outputs" in line:
        print("   ", line.rstrip())
print("==== listener: everything but the lamps")
for line in open(os.path.join(x.log_dir, "listener.log"), errors="replace"):
    if "Lmp" in line or "CardLock" in line:
        continue
    print("   ", line.rstrip())
print("logs in", x.log_dir)
