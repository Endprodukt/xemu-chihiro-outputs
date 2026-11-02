"""Why does player 2 not start in Ghost Squad? Try: a long P2 Start in attract,
quick repeated presses, P2 joining after P1 started, P2 Start at mission
select; a screenshot after each, and the P2 status byte."""
import time

from xemudrv import Xemu

extra = [("chihiro.jvs_p2", "pointer_device", "'mouse'"), ("chihiro.jvs_p2", "start", "31"),
         ("chihiro.jvs_p2", "gs_trigger", "27"), ("chihiro.jvs_p2", "coin", "32"),   # coin on '3'
         ("chihiro.jvs_p2", "gs_body_button", "18"), ("chihiro.jvs_p2", "gs_change", "19")]
x = Xemu(r"D:\Xemu Chihiro\Ghost Squad.bin", "gs", "gsp2", extra_toml=extra)
x.SC["3"] = 0x04


def st():
    p1 = x.read(0x00465A28, 1)
    p2 = x.read(0x00465A28 + 0x1AC, 1)
    return "P1 status %s, P2 status %s" % (p1.hex() if p1 else "--", p2.hex() if p2 else "--")


try:
    x.say("monitor %s" % x.connect())
    time.sleep(80)
    x.focus()
    x.screenshot("00_attract")
    x.say("A: P2 start held 1.0s; " + st())
    x.tap("2", 1.0)
    time.sleep(4)
    x.screenshot("01_after_long_p2_start")
    x.say(st())
    x.say("B: P2 start x6 quick")
    for _ in range(6):
        x.tap("2", 0.12)
        time.sleep(0.3)
    time.sleep(4)
    x.screenshot("02_after_quick_p2_starts")
    x.say(st())
    x.say("C: P2 trigger + start")
    x.key("x", True)
    time.sleep(0.2)
    x.tap("2", 0.4)
    x.key("x", False)
    time.sleep(4)
    x.screenshot("03_after_trigger_start")
    x.say(st())
    x.say("D: P1 starts, then P2 joins 3s later")
    x.tap("1", 0.3)
    time.sleep(3)
    x.tap("2", 0.4)
    time.sleep(3)
    x.screenshot("04_p1_started_p2_join")
    x.say(st())
    x.tap("1", 0.3)          # skip tutorial
    time.sleep(5)
    x.focus()
    x.screenshot("05_mission_select")
    x.tap("2", 0.4)
    time.sleep(3)
    x.screenshot("06_p2_start_at_mission_select")
    x.say(st())
    x.tap("space", 0.1)      # P1 picks the mission
    time.sleep(6)
    x.tap("2", 0.4)
    time.sleep(4)
    x.screenshot("07_p2_start_in_intro")
    x.say(st())
finally:
    x.stop()
