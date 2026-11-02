"""Map physical addresses found in a dump back to guest virtual addresses by
walking the x86 page tables inside the dump (Xbox: page directory at 0xF000),
and print the bytes around them in every dump.

    python pa2va.py <dumpdir> <pa> [<pa> ...]
"""
import os
import struct
import sys

import numpy as np

d = sys.argv[1]
pas = [int(a, 16) for a in sys.argv[2:]]
names = ["attract1", "attract2", "play0", "play1", "play2", "empty",
         "reloaded", "reloaded3", "late"]
dumps = {n: np.fromfile(os.path.join(d, n + ".bin"), dtype=np.uint8) for n in names}
mem = dumps["play0"].tobytes()


def u32(off):
    return struct.unpack_from("<I", mem, off)[0]


def walk(pd, va):
    pde = u32(pd + ((va >> 22) << 2))
    if not pde & 1:
        return None
    if pde & 0x80:
        return (pde & 0xFFC00000) | (va & 0x3FFFFF)
    pt = pde & 0xFFFFF000
    if pt + 0x1000 > len(mem):
        return None
    pte = u32(pt + (((va >> 12) & 0x3FF) << 2))
    if not pte & 1:
        return None
    return (pte & 0xFFFFF000) | (va & 0xFFF)


cands = []
for off in [0xF000] + list(range(0, 0x2000000, 0x1000)):
    pa = walk(off, 0x10000)
    if pa is not None and pa + 4 <= len(mem) and mem[pa:pa + 4] == b"XBEH":
        cands.append(off)
        break
print("page directory:", [hex(c) for c in cands])
pd = cands[0]
pa2va = {}
for i in range(1024):
    pde = u32(pd + i * 4)
    if not (pde & 1):
        continue
    va_base = i << 22
    if pde & 0x80:
        pa_base = pde & 0xFFC00000
        for pa in pas:
            if pa_base <= pa < pa_base + 0x400000:
                pa2va.setdefault(pa, []).append(va_base + (pa - pa_base))
        continue
    pt = pde & 0xFFFFF000
    if pt + 0x1000 > len(mem):
        continue
    for j in range(1024):
        pte = u32(pt + j * 4)
        if not (pte & 1):
            continue
        page = pte & 0xFFFFF000
        for pa in pas:
            if page <= pa < page + 0x1000:
                pa2va.setdefault(pa, []).append(va_base + (j << 12) + (pa & 0xFFF))

for pa in pas:
    print("PA %08X -> VA %s" % (pa, ", ".join("%08X" % v for v in pa2va.get(pa, [])) or "unmapped"))
    print("   bytes PA-0x10 .. PA+0x1F per dump:")
    for n in names:
        a = dumps[n]
        lo = max(pa - 0x10, 0)
        print("   %-9s %s | %s" % (n, " ".join("%02x" % b for b in a[lo:pa]),
                                   " ".join("%02x" % b for b in a[pa:pa + 0x20])))
