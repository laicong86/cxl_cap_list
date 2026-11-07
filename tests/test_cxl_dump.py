#!/usr/bin/env python3
"""
test_cxl_dump.py - offline self-test for the register decoding logic.

Builds a synthetic 64 KB Component Register Block + config space matching
spec rev 3.1 sec 8.2, then checks that cxl_dump decodes it correctly.

Run:  python3 tests/test_cxl_dump.py
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cxl_dump as C


class FakeMM(bytearray):
    """Minimal mmap stand-in: a bytearray that also supports close()."""

    def __init__(self, data):
        super().__init__(data)

    def close(self):
        pass


class FakeDev(C.PciDevice):
    def __init__(self, block, config, bars):
        super().__init__("0000:00:00.0")
        self._block = block
        self.config = config
        self._bars = bars

    def load_config(self):
        return True

    def bars(self):
        return self._bars

    def bar_start(self, index):
        for idx, start, end, flags in self._bars:
            if idx == index:
                return start
        return None

    def mmap_bar(self, index, size):
        return FakeMM(self._block)


def build_block():
    """
    Build a 64 KB Component Register Block:
      0x1000  primary range:
                +00h header  : id=1 ver=1 cm_ver=1 array_size=4
                +04h RAS hdr : id=2 ver=3 -> 0x100
                +08h Link hdr: id=4 ver=4 -> 0x200
                +0Ch HDM hdr : id=5 ver=3 -> 0x300
                +10h ExtRng  : id=0A ver=1 -> 0x400
      0x2000  extended range: header id=1 array_size=1, entry id=0x0C -> 0x2400
      0xE000  ARB/MUX: PM timeout = 1, weights
    """
    b = bytearray(0x10000)

    def wr32(off, val):
        struct.pack_into("<I", b, off, val)

    def wr64(off, val):
        struct.pack_into("<Q", b, off, val)

    # --- primary range header
    wr32(0x1000, (4 << 24) | (1 << 20) | (1 << 16) | 1)
    wr32(0x1004, (0x100 << 20) | (3 << 16) | 0x0002)   # RAS
    wr32(0x1008, (0x200 << 20) | (4 << 16) | 0x0004)   # Link
    wr32(0x100C, (0x300 << 20) | (3 << 16) | 0x0005)   # HDM
    wr32(0x1010, (0x400 << 20) | (1 << 16) | 0x000A)   # Extended ranges

    # --- RAS @ 0x1100
    wr32(0x1100, 0x00004001)   # UC status: Cache_Data_Parity + Internal_Error
    wr32(0x1104, 0x00000000)
    wr32(0x1108, 0x0001DFFF)
    wr32(0x110C, 0x00000002)   # CE status
    wr32(0x1110, 0x00000000)
    wr32(0x1114, 0x00002001)   # first err ptr = 1, poison enabled

    # --- Link @ 0x1200
    wr64(0x1200, 0x0400_0000_0000_0001)
    wr64(0x1208, 0b11_0000 | 0)    # INIT_DONE

    # --- HDM @ 0x1300: 2 decoders
    wr32(0x1300, (1 << 12) | (1 << 10) | (1 << 8) | (2 << 4) | 0x1)
    wr32(0x1304, 0x2)          # HDM decoder enable

    # decoder 0: base 0x0_0000_0000, size 0x0_4000_0000 (1 GB), 2-way, 1KB
    wr32(0x1310, 0x00000000)
    wr32(0x1314, 0x00000000)
    wr32(0x1318, 0x00000000)
    wr32(0x131C, 0x00000000)
    wr32(0x1320, (1 << 10) | (2 << 4) | 2)   # committed, 4way, 1KB

    # decoder 1: base 0x0_4000_0000
    wr32(0x1330, 0x40000000 >> 28 << 28)
    wr32(0x1334, 0x00000000)
    wr32(0x1338, 0x40000000 >> 28 << 28)
    wr32(0x133C, 0x00000000)
    wr32(0x1340, (1 << 10) | (0 << 4) | 0)

    # --- Extended ranges @ 0x1400: bitmap = bit2 | bit3 | bit15
    wr32(0x1400, (1 << 2) | (1 << 3) | (1 << 15))

    # --- extended range @ 0x2000 (bit 2): valid header
    wr32(0x2000, (1 << 24) | (1 << 20) | (1 << 16) | 1)
    wr32(0x2004, (0x100 << 20) | (1 << 16) | 0x000C)   # BI Decoder

    # --- extended range @ 0x3000 (bit 3): empty but valid header
    wr32(0x3000, (0 << 24) | (1 << 20) | (1 << 16) | 1)

    # --- extended range @ 0xF000 (bit 15): invalid header (id=0) -> should skip
    wr32(0xF000, 0x00000000)

    # --- ARB/MUX @ 0xE000
    wr32(0xE000, 0x1)          # PM timeout enable, 1ms
    wr32(0xE004, 0x0)
    wr32(0xE008, 0x3)
    wr32(0xE180, (5 << 4))
    wr32(0xE1C0, (3 << 4))

    return b


def build_config(bar_start=0x1000_0000):
    """Config space: vendor 1E98, DVSEC 0000h + DVSEC 0008h with 2 blocks."""
    cfg = bytearray(b"\x00" * 4096)
    struct.pack_into("<H", cfg, 0x00, C.CXL_VENDOR_ID)
    struct.pack_into("<H", cfg, 0x02, 0x1234)
    cfg[0x0B] = 0x05            # class: memory controller

    # extended capability list at 0x100: DVSEC 0000h
    def extcap(off, cap_id, ver, nxt, length=0x3C):
        struct.pack_into("<I", cfg, off,
                         ((nxt & 0xFFF) << 20) | ((ver & 0xF) << 16) | cap_id)
        # DVSEC header 1
        struct.pack_into("<I", cfg, off + 4,
                         ((length & 0xFFF) << 20) | ((ver & 0xF) << 16)
                         | C.CXL_VENDOR_ID)

    extcap(0x100, C.PCI_EXT_CAP_ID_DVSEC, 3, 0x140)
    struct.pack_into("<I", cfg, 0x108, 0x0000)        # DVSEC ID 0h
    # CXL Capability @ +0x0A: cache=1 mem=1 io=1, hdm_count=01b
    struct.pack_into("<H", cfg, 0x10A, 0x0017)        # bits 0,1,2,4
    struct.pack_into("<H", cfg, 0x10C, 0x0004)        # Mem_Enable
    # Range 1: size high @0x118, size low @0x11C, base hi @0x120, base lo @0x124
    struct.pack_into("<I", cfg, 0x118, 0x00000000)
    struct.pack_into("<I", cfg, 0x11C, 0x40000003)    # valid, active, 1GB @[31:28]
    struct.pack_into("<I", cfg, 0x120, 0x00000000)
    struct.pack_into("<I", cfg, 0x124, 0x00000000)

    # DVSEC 0008h - Register Locator, 2 blocks -> length 0x0C + 16 = 0x1C
    extcap(0x140, C.PCI_EXT_CAP_ID_DVSEC, 0, 0x000, length=0x1C)
    struct.pack_into("<I", cfg, 0x148, 0x0008)        # DVSEC ID 8h
    # block 0: BIR=0, id=01h (component), offset 0x10000
    struct.pack_into("<I", cfg, 0x14C, ((0x10000 >> 16) << 16) | (0x01 << 8) | 0)
    struct.pack_into("<I", cfg, 0x150, 0x0)
    # block 1: BIR=2, id=03h (device regs), offset 0x20000
    struct.pack_into("<I", cfg, 0x154, ((0x20000 >> 16) << 16) | (0x03 << 8) | 2)
    struct.pack_into("<I", cfg, 0x158, 0x0)
    return cfg


def check(cond, msg):
    if cond:
        print("  PASS  %s" % msg)
        return True
    print("  FAIL  %s" % msg)
    return False


def main():
    print("CXL register decoding self-test")
    print("=" * 60)

    ok = True
    block = build_block()
    cfg = build_config()
    # BAR0 spans 0x1000_0000 .. with the block at +0x10000
    bars = [(0, 0x1000_0000, 0x1000_0000 + 0x3FFFF, 0x4),
            (2, 0x2000_0000, 0x2000_0000 + 0x3FFFF, 0x4)]
    dev = FakeDev(block, cfg, bars)

    # --- PCIe side
    print("\n[1] PCIe configuration space")
    dvsecs = dev.find_cxl_dvsecs()
    ok &= check(len(dvsecs) == 2, "2 CXL DVSECs found (got %d)" % len(dvsecs))
    ok &= check(any(d["dvsec_id"] == 0x0008 for d in dvsecs),
                "Register Locator DVSEC present")

    print("\n[2] Register Locator DVSEC")
    blocks = dev.regloc_blocks()
    ok &= check(len(blocks) == 2, "2 register blocks (got %d)" % len(blocks))
    ok &= check(blocks[0]["bir"] == 0 and blocks[0]["block_id"] == 0x01,
                "block0 = BAR0 / Component Registers")
    ok &= check(blocks[0]["block_offset"] == 0x10000,
                "block0 offset = 0x10000 (got 0x%x)" % blocks[0]["block_offset"])
    ok &= check(blocks[1]["bir"] == 2 and blocks[1]["block_id"] == 0x03,
                "block1 = BAR2 / Device Registers")
    ok &= check(blocks[1]["block_offset"] == 0x20000,
                "block1 offset = 0x20000 (got 0x%x)" % blocks[1]["block_offset"])

    # --- Component block
    print("\n[3] Component Register Block (Table 8-21)")
    comp = C.ComponentBlock(dev, 0, 0x10000, 0x1000_0000)
    comp.mm = FakeMM(block)
    comp.mm_off = 0
    comp.map_len = 0x10000
    ok &= check(comp.base == 0x1001_0000, "base = BAR0 + 0x10000")

    prim = comp.parse_cachemem_range(0x1000, "primary")
    ok &= check(not prim["errors"], "no parse errors")
    ok &= check(prim["header_id"] == 1, "header ID = 1")
    ok &= check(prim["array_size"] == 4,
                "array_size = 4 (got %d)" % prim["array_size"])
    ids = [c["id"] for c in prim["caps"]]
    ok &= check(ids == [2, 4, 5, 0x0A], "cap IDs = %s" % [hex(i) for i in ids])

    # pointer must be used as-is (byte offset), no shift
    ras = prim["caps"][0]
    ok &= check(ras["pointer"] == 0x100 and ras["abs_offset"] == 0x1100,
                "RAS pointer 0x100 -> abs 0x1100 (no shift)")

    print("\n[4] Capability decode")
    ras_lines = comp.decode_capability(ras)
    ok &= check(any("0x00004001" in l for l in ras_lines),
                "RAS UC status decoded")
    ok &= check(any("Cache_Data_Parity" in l for l in ras_lines),
                "RAS UC bit names decoded")

    hdm = prim["caps"][2]
    hdm_lines = comp.decode_capability(hdm)
    ok &= check(any("2 decoders" in l for l in hdm_lines),
                "HDM decoder count = 2")
    ok &= check(any("HDM Decoder Enable  = 1" in l for l in hdm_lines),
                "HDM global enable = 1")
    ok &= check(any("Y    HDM-D" in l for l in hdm_lines),
                "committed decoder row rendered")
    ok &= check(any("0x000040000000" in l and "0x40000000" in l
                    for l in hdm_lines),
                "decoder 1 base/size decoded")

    ext = prim["caps"][3]
    ext_lines = comp.decode_capability(ext)
    ok &= check(any("bit2=0x2000-0x2fff" in l for l in ext_lines),
                "extended range bitmap bit2 decoded")
    ok &= check(any("bit15=0xf000-0xffff" in l for l in ext_lines),
                "extended range bitmap bit15 decoded")

    print("\n[5] Extended ranges + ARB/MUX")
    dbg = comp.dump(verbose=False)
    ok &= check(any("Extended Range @ 0x2000" in l for l in dbg),
                "extended range 0x2000 walked")
    ok &= check(any("Extended Range @ 0xf000" in l or
                    "extended range @ 0xf000" in l for l in dbg),
                "extended range 0xf000 attempted")
    ok &= check(any("ARB/MUX" in l for l in dbg), "ARB/MUX section present")
    ok &= check(any("weight=5" in l for l in dbg), "ARB weight decoded")

    print("\n[6] hdm_decoder_count encoding")
    for code, expect in [(0, 1), (1, 2), (2, 4), (3, 6), (4, 8), (5, 10),
                         (6, 12), (7, 14), (8, 16), (9, 20), (10, 24),
                         (11, 28), (12, 32)]:
        got = C.hdm_decoder_count(code)
        ok &= check(got == expect,
                    "code %2d -> %d (got %d)" % (code, expect, got))

    print("\n[7] CPMU decoding (8.2.7)")
    ok &= test_cpmu()

    print("\n" + "=" * 60)
    print("RESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


def build_cpmu():
    """Synthetic CPMU block matching the a8:00.0 shape we validated on hw."""
    buf = bytearray(b"\x00" * 0x10000)

    def w32(off, v):
        struct.pack_into("<I", buf, off, v & 0xFFFFFFFF)

    def w64(off, v):
        struct.pack_into("<Q", buf, off, v & 0xFFFFFFFFFFFFFFFF)

    # Capability: version=1, units code 0x14 (21 units), width 48,
    # event cap regs code 5 (6 regs), filters 0x03, imn 6, wr_frozen=1,
    # freeze=1, irq=1
    cap = ((1 << 60) | (0x14) | (48 << 8) | (5 << 20) | (0x03 << 32)
           | (6 << 44) | (1 << 48) | (1 << 49) | (1 << 50))
    w64(0x00, cap)

    # Event capabilities: Base/Clock, M2S Req, DDR Interface
    w64(0x100, (0x1E98 << 48) | (0x0000 << 32) | 0x1)
    w64(0x108, (0x1E98 << 48) | (0x0020 << 32) | 0x31F)
    w64(0x110, (0x1E98 << 48) | (0x8000 << 32) | 0x7F)

    # Unit 0: fixed-function, Clock Ticks, enabled
    w64(0x200, (1 << 0) | (1 << 8) | (1 << 16) | (0x1 << 24))
    # Unit 1: fixed-function, M2S MemRd (bit1), group index 1
    w64(0x208, (1 << 0) | (0 << 8) | (1 << 16) | (0x2 << 24) | (1 << 59))
    # Unit 2: fixed-function, DDR ACT (bit0), group index 2
    w64(0x210, (1 << 0) | (0 << 8) | (1 << 16) | (0x1 << 24) | (2 << 59))

    # Filters: leave reset default 0xFFFFFFFF (no filtering)
    for n in range(3):
        for fid in range(2):
            w32(0x400 + n * 0x20 + fid * 4, 0xFFFFFFFF)

    # Counter data: 0 enabled units -> small values
    w64(0xC00, 0x1234)
    w64(0xC08, 0)
    w64(0xC10, 0xFFFFFFFFFFFFFFFF)  # above 48-bit width
    return buf


def test_cpmu():
    ok = True
    block = build_cpmu()
    cfg = build_config()
    bars = [(0, 0x1000_0000, 0x1000_0000 + 0x3FFFF, 0x4)]
    dev = FakeDev(block, cfg, bars)

    blk = C.CpmuBlock(dev, 0, 0x0, 0x1000_0000)
    blk.mm = FakeMM(block)
    blk.mm_off = 0
    blk.map_len = 0x10000
    lines = blk.dump(verbose=False)
    text = "\n".join(lines)

    ok &= check("Version              = 1" in text, "CPMU version decoded")
    ok &= check("Counter Units        = 21" in text, "21 counter units")
    ok &= check("Counter Width        = 48 bits" in text, "48-bit counters")
    ok &= check("Event Cap Regs       = 6" in text, "6 event cap registers")
    ok &= check("Freeze Support       = 1" in text, "freeze supported")
    ok &= check("Clock Ticks" in text, "Base group event named")
    ok &= check("MemRd" in text, "M2S Req event named via opcode table")
    ok &= check("ACT Count" in text, "DDR Interface event named")
    ok &= check("DDR Interface" in text, "DDR event group labelled")
    ok &= check(any("0x%016x" % 0x1234 in l for l in lines),
                "counter 0 data rendered")
    ok &= check("bits above 48 set" in text,
                "counter 3 flagged for bits above width")

    # 0x8000 group must use Filter ID 1, CXL.mem groups Filter ID 0
    ok &= check(text.count("Filter[0] HDM decoder mask") >= 1,
                "M2S unit uses Filter ID 0")
    ok &= check(text.count("Filter[1] Channel") >= 1,
                "DDR unit uses Filter ID 1")
    return ok


if __name__ == "__main__":
    sys.exit(main())
