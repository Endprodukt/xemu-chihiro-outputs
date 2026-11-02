"""Virtua Cop 3: get into play (mission select, skip the briefing), then diff
memory dumps around shots to find the magazine counter and the status byte."""
import os
import struct
import sys
import time

import numpy as np

from xemudrv import Xemu, RAM

image = sys.argv[1] if len(sys.argv) > 1 else r"D:\Xemu Chihiro\Virtua Cop 3.bin"
boot_wait = int(sys.argv[2]) if len(sys.argv) > 2 else 75
P2 = True
extra = [("chihiro.jvs_p2", "pointer_device", "'mouse'"), ("chihiro.jvs_p2", "start", "31"),
         ("chihiro.jvs_p2", "vc3_trigger", "27"), ("chihiro.jvs_p2", "vc3_reload", "6")]
x = Xemu(image, "vc3", "memsearch-p2", extra_toml=extra)
dumps = {}
try:
    x.say("monitor %s" % x.connect())
    time.sleep(boot_wait)
    dumps["attract1"] = x.dump("attract1")
    time.sleep(2)
    dumps["attract2"] = x.dump("attract2")
    x.focus()
    x.tap("2", 0.15)
    time.sleep(1)
    x.tap("2", 0.15)
    x.say("start; mission select in 4s, shoot the middle one")
    time.sleep(4)
    x.focus()
    x.screenshot("10_mission_select")
    x.tap("x", 0.1)
    time.sleep(2)
    x.say("skipping briefing with Start every 4s")
    for i in range(10):
        time.sleep(4)
        x.tap("2", 0.15)
    time.sleep(3)
    x.focus()
    x.screenshot("11_play_check")
    dumps["play0"] = x.dump("play0")
    x.tap("x", 0.1)
    time.sleep(0.7)
    dumps["play1"] = x.dump("play1")
    x.tap("x", 0.1)
    time.sleep(0.7)
    dumps["play2"] = x.dump("play2")
    x.screenshot("12_after_2_shots")
    for i in range(10):
        x.tap("x", 0.1)
        time.sleep(0.4)
    time.sleep(0.5)
    dumps["empty"] = x.dump("empty")
    x.screenshot("13_after_12_shots")
    x.key("c", True)
    time.sleep(0.3)
    x.tap("x")
    time.sleep(0.5)
    x.tap("x")
    x.key("c", False)
    time.sleep(1.5)
    dumps["reloaded"] = x.dump("reloaded")
    x.screenshot("14_after_reload")
    for i in range(3):
        x.tap("x", 0.1)
        time.sleep(0.4)
    time.sleep(0.5)
    dumps["reloaded3"] = x.dump("reloaded3")
    time.sleep(2)
    dumps["late"] = x.dump("late")
    x.screenshot("15_end")
finally:
    x.stop()

if not all(dumps.values()):
    sys.exit("dump failed")


def load(n):
    return np.fromfile(dumps[n], dtype=np.uint8)


A1, A2 = load("attract1"), load("attract2")
P0, P1, P2 = load("play0"), load("play1"), load("play2")
E, R, R3, L = load("empty"), load("reloaded"), load("reloaded3"), load("late")
hdr = P0[0x10000:0x10200].tobytes()
sections = []
try:
    nsec, = struct.unpack_from("<I", hdr, 0x11C)
    secaddr, = struct.unpack_from("<I", hdr, 0x120)
    raw = P0.tobytes()
    for i in range(nsec):
        fl, va, vs, ro, rs, nameaddr = struct.unpack_from("<IIIIII", raw, secaddr + i * 0x38)
        nm = raw[nameaddr:nameaddr + 12].split(b"\0")[0].decode("ascii", "replace")
        sections.append((nm, va, vs))
    print("sections:", [(n, hex(v), hex(s)) for n, v, s in sections])
except Exception as e:
    print("sections:", e)


def sec(pa):
    for n, va, vs in sections:
        if va <= pa < va + vs:
            return n
    return "other"


i16 = lambda a: a.astype(np.int16)
strict = (i16(P0) - i16(P1) == 1) & (i16(P1) - i16(P2) == 1) & (E < P2) & \
         (R > E) & (i16(R) - i16(R3) == 3) & (P0 <= 60)
hits = np.flatnonzero(strict)
print("\nAMMO strict (P0 P1 P2 E R R3 L):", len(hits))
for h in hits[:40]:
    print("  %08X %-8s %3d %3d %3d %3d %3d %3d %3d" % (h, sec(h), P0[h], P1[h], P2[h], E[h], R[h], R3[h], L[h]))
loose = (P0 > P1) & (P1 >= P2) & (P2 >= E) & (R > E) & (R >= R3) & (P0 <= 60) & ~strict
hits2 = np.flatnonzero(loose)
print("\nAMMO loose:", len(hits2))
for h in hits2[:40]:
    print("  %08X %-8s %3d %3d %3d %3d %3d %3d %3d" % (h, sec(h), P0[h], P1[h], P2[h], E[h], R[h], R3[h], L[h]))
same = (P0 == P1) & (P1 == P2) & (P2 == E) & (E == R) & (R == R3) & (R3 == L)
status = (A1 == A2) & same & (A1 != P0)
hits3 = np.flatnonzero(status)
print("\nSTATUS candidates:", len(hits3))
strong = [h for h in hits3 if P0[h] == 2 and A1[h] in (128, 0, 9) and sec(h) != "other"]
print("  in the image, play==2, attract in {128,0,9}:", len(strong))
for h in strong[:60]:
    print("  %08X %-8s attract=%3d play=%3d" % (h, sec(h), A1[h], P0[h]))
np.save(os.path.join(x.log_dir, "status_hits.npy"), hits3)
print("logs in", x.log_dir)
