"""Offline analysis of the memsearch2 dumps: play0=9 rounds, play1=8, play2=7,
empty=0; reloaded/reloaded3/late = continue screen; attract1/2 = attract."""
import os
import struct
import sys

import numpy as np

d = sys.argv[1]


def load(n):
    return np.fromfile(os.path.join(d, n + ".bin"), dtype=np.uint8)


A1, A2 = load("attract1"), load("attract2")
P0, P1, P2, E = load("play0"), load("play1"), load("play2"), load("empty")
R, R3, L = load("reloaded"), load("reloaded3"), load("late")
raw = P0.tobytes()
sections = []
nsec, = struct.unpack_from("<I", raw, 0x10000 + 0x11C)
secaddr, = struct.unpack_from("<I", raw, 0x10000 + 0x120)
for i in range(nsec):
    fl, va, vs, ro, rs, nameaddr = struct.unpack_from("<IIIIII", raw, secaddr + i * 0x38)
    nm = raw[nameaddr:nameaddr + 12].split(b"\0")[0].decode("ascii", "replace")
    sections.append((nm, va, vs))
print("sections:", ascii([(n, hex(v), hex(s)) for n, v, s in sections]))


def sec(pa):
    for n, va, vs in sections:
        if va <= pa < va + vs:
            return n
    return "other"


def show(label, idx, cols):
    print("\n%s: %d" % (label, len(idx)))
    for h in idx[:50]:
        print("  %08X %-8s " % (h, sec(h)) + " ".join("%3d" % a[h] for a in cols))


cols = (A1, A2, P0, P1, P2, E, R, R3, L)
print("columns: A1 A2 P0 P1 P2 E R R3 L")
ammo = (P0 == 9) & (P1 == 8) & (P2 == 7) & (E == 0)
show("AMMO 9/8/7/0", np.flatnonzero(ammo), cols)
# 16/32-bit little endian: the byte pattern already covers the low byte; also
# check the next byte is 0 for those
# status: attract steady, play steady (another value), continue steady (a third)
steady_a = A1 == A2
steady_p = (P0 == P1) & (P1 == P2) & (P2 == E)
steady_c = (R == R3) & (R3 == L)
st = steady_a & steady_p & steady_c & (A1 != P0) & (P0 != R)
idx = np.flatnonzero(st)
print("\nSTATUS three-valued candidates:", len(idx))
exact = idx[(P0[idx] == 2) & (R[idx] == 8)]
show("  play==2 and continue==8", exact, cols)
exact2 = idx[(P0[idx] == 2) & (A1[idx] == 128)]
show("  play==2 and attract==128", exact2, cols)
small = idx[(P0[idx] < 16) & (R[idx] < 16) & (A1[idx] < 130)]
img = [h for h in small if sec(h) != "other"]
show("  small values inside the image", np.array(img), cols)
