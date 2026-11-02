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
P2 = "--p2" in sys.argv
CLICK = "--click" in sys.argv          # trigger on the left mouse button (binding 1001)
# player 2 on keys: Start 2, trigger X, reload C, action O / mode P, aim from the mouse too
START, TRIG, RELOAD = ("2", "x", "c") if P2 else ("1", "space", "r")
extra = []
if P2:
    extra += [("chihiro.jvs_p2", "pointer_device", "'mouse'"),
              ("chihiro.jvs_p2", "start", "31"),
              ("chihiro.jvs_p2", profile + "_trigger", "1001" if CLICK else "27"),
              ("chihiro.jvs_p2", profile + "_reload", "6"),
              ("chihiro.jvs_p2", "gs_body_button", "18"),
              ("chihiro.jvs_p2", "gs_change", "19")]
if profile == "gs":
    # the action button (o) and the mode change (p) on keys, to skip the intro
    extra += [("chihiro.jvs.gs", "body_button", "18"), ("chihiro.jvs.gs", "change", "19")]
x = Xemu(images[profile], profile, "listen-p2" if P2 else "listen", network=True, extra_toml=extra)
listener_log = open(os.path.join(x.log_dir, "listener.log"), "w")
listener = subprocess.Popen([sys.executable, "-I",
                             os.path.join(HERE, "outputs_listener.py"),
                             "--tcp", "8000"],
                            stdout=listener_log, stderr=subprocess.STDOUT)


def note(msg):
    x.say(msg)
    listener_log.write(time.strftime("%H:%M:%S") + ".000 DRIVER: " + msg + "\n")
    listener_log.flush()


def pull(hold=0.1):
    if CLICK:
        x.click(True)
        time.sleep(hold)
        x.click(False)
    else:
        x.tap(TRIG, hold)


def shots(n, gap=0.45):
    for _ in range(n):
        pull()
        time.sleep(gap)


def reload():
    x.key(RELOAD, True)
    time.sleep(0.3)
    pull()
    time.sleep(0.5)
    pull()
    time.sleep(0.2)
    x.key(RELOAD, False)


try:
    x.say("monitor %s" % x.connect())
    time.sleep(boot_wait)
    x.focus()
    x.screenshot("01_attract")
    # Ghost Squad wants the Start button held (a 0.3 s tap is not seen)
    for _ in range(3):
        x.tap(START, 1.0 if profile == "gs" else 0.3)
        time.sleep(1)
    note("Start pressed (player %d)" % (2 if P2 else 1))
    if profile == "vc3":
        time.sleep(4)
        x.focus()
        pull()                                   # mission select
        note("mission chosen, skipping the briefing")
        for i in range(10):
            time.sleep(4)
            x.tap(START, 0.15)
        time.sleep(3)
    elif profile == "hotd3":
        time.sleep(3)
        x.tap(START, 0.15)                       # skip the intro
        note("intro skipped")
        time.sleep(10)
    elif P2:
        # Ghost Squad, player 2: Start is only taken on some attract screens,
        # so press until the status byte says in play; then the card screen
        # ("Start game without card" at about 72 % / 67 %), the tutorial, the
        # mission select.
        for i in range(50):
            v = x.read(0x00465A28 + 0x1AC, 1)
            if v == b"":
                break
            x.tap(START, 1.0)
            time.sleep(2)
        note("P2 status now %s after %d presses" % ((x.read(0x00465A28 + 0x1AC, 1) or b"").hex(), i))
        x.screenshot("01b_p2_accepted")
        time.sleep(2)
        x.focus(aim=(0.72, 0.67))
        pull()                                   # start game without card
        time.sleep(4)
        x.tap(START, 1.0)                        # skip the tutorial
        time.sleep(5)
        x.focus()
        pull()                                   # mission select
        note("mission chosen; skipping the intro with the action button")
        for i in range(6):
            time.sleep(4)
            x.tap("o", 0.15)
            time.sleep(0.5)
            x.tap("p", 0.15)
        time.sleep(6)
    else:
        time.sleep(3)
        x.tap(START, 1.0)                        # skip the tutorial
        time.sleep(5)
        x.focus()
        pull()                                   # mission select
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
