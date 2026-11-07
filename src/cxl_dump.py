#!/usr/bin/env python3
"""
cxl_dump.py - enumerate CXL devices and dump their Component / Device registers.

Reference: Compute Express Link Specification Rev 3.1, Ver 1.0 (2023-08-09)

Discovery chain implemented here:

  1. PCIe config space  ->  find DVSEC (Ext Cap ID 0023h) with
                            Vendor ID 1E98h, DVSEC ID 0008h (Register Locator, 8.1.9)
  2. Register Block      ->  BIR (which BAR) + 64 KB aligned offset
  3. mmap the BAR        ->  component_base = BAR[BIR].start + offset
  4. Table 8-21          ->  walk the 64 KB Component Register Block
                             0x0000  CXL.io (reserved, skipped)
                             0x1000  CXL.cachemem Primary Range
                             0x2000  Extended Range pool
                             0xE000  CXL ARB/MUX
  5. Table 8-23 / 8-22   ->  in each 4 KB cachemem range, follow the
                             CXL_Capability_Header pointer array

Read-only: this tool never writes a register.

Usage:
    sudo python3 cxl_dump.py                     # all CXL devices, summary
    sudo python3 cxl_dump.py -v                  # verbose, all structures
    sudo python3 cxl_dump.py -d 0000:3b:00.0     # one device
    sudo python3 cxl_dump.py -d 0000:3b:00.0 --hex 0x1000 0x40
    python3 cxl_dump.py --list                   # list only, no root needed
"""

import argparse
import mmap
import os
import struct
import subprocess
import sys

SYSFS_PCI = "/sys/bus/pci/devices"

CXL_VENDOR_ID = 0x1E98

# ---------------------------------------------------------------------------
# PCIe capability ids
# ---------------------------------------------------------------------------
# PCIe extended capability id for Designated Vendor-Specific (DVSEC) is 0023h.
# NOTE: 0003h is Device Serial Number, NOT DVSEC - a classic mix-up.
PCI_EXT_CAP_ID_DVSEC = 0x0023

# CXL DVSEC ids (Table 8-2)
DVSEC_DEVICE = 0x0000
DVSEC_PORT_EXT = 0x0003
DVSEC_FLEXBUS = 0x0007
DVSEC_REGLOC = 0x0008
DVSEC_MLD = 0x0009
DVSEC_TEST_CAP = 0x000A

DVSEC_NAME = {
    DVSEC_DEVICE: "PCIe DVSEC for CXL Devices (8.1.3)",
    DVSEC_PORT_EXT: "CXL Extensions DVSEC for Ports (8.1.5)",
    DVSEC_FLEXBUS: "PCIe DVSEC for Flex Bus Port (8.1.8)",
    DVSEC_REGLOC: "Register Locator DVSEC (8.1.9)",
    DVSEC_MLD: "MLD DVSEC (8.1.10)",
    DVSEC_TEST_CAP: "PCIe DVSEC for Test Capability (14.16.1)",
    0x0002: "Non-CXL Function Map DVSEC (8.1.4)",
    0x0004: "GPF DVSEC for CXL Ports (8.1.6)",
    0x0005: "GPF DVSEC for CXL Devices (8.1.7)",
}

# Register Block Identifier (8.1.9.1)
BLOCK_NAME = {
    0x00: "empty",
    0x01: "Component Registers (8.2.3)",
    0x02: "BAR Virtualization ACL (8.2.6)",
    0x03: "CXL Device Registers (8.2.8)",
    0x04: "CPMU Registers (8.2.7)",
    0xFF: "Vendor Specific",
}

# Table 8-21 - Component Register Block ranges
COMPONENT_RANGES = [
    (0x0000, 0x1000, "Reserved for CXL.io registers (undefined, skipped)"),
    (0x1000, 0x1000, "CXL.cachemem Primary Range"),
    (0x2000, 0xC000, "Implementation specific (Extended Range pool)"),
    (0xE000, 0x0400, "CXL ARB/MUX registers"),
    (0xE400, 0x1C00, "Reserved (F000-FFFFh may host an Extended Range)"),
]

# CXL_Capability_ID assignment (Table 8-22)
CM_CAP_NAME = {
    0x0000: "CXL NULL Capability",
    0x0001: "CXL Capability Header",
    0x0002: "CXL RAS Capability",
    0x0003: "CXL Security Capability",
    0x0004: "CXL Link Capability",
    0x0005: "CXL HDM Decoder Capability",
    0x0006: "CXL Extended Security Capability",
    0x0007: "CXL IDE Capability",
    0x0008: "CXL Snoop Filter Capability",
    0x0009: "CXL Timeout and Isolation Capability",
    0x000A: "CXL.cachemem Extended Register Capability",
    0x000B: "CXL BI Route Table Capability",
    0x000C: "CXL BI Decoder Capability",
    0x000D: "CXL Cache ID Route Table Capability",
    0x000E: "CXL Cache ID Decoder Capability",
    0x000F: "CXL Extended HDM Decoder Capability",
    0x0010: "CXL Extended Metadata Capability",
}

# Device capability ids (8.2.8.2.1)
DEV_CAP_NAME = {
    0x0001: "Device Status Registers",
    0x0002: "Primary Mailbox Registers",
    0x0003: "Secondary Mailbox Registers",
    0x4000: "Memory Device Status Registers",
}

# Interleave Ways decoding (8.2.4.20.7)
IW_MAP = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16, 8: 3, 9: 6, 0xA: 12}
IG_MAP = {0: "256B", 1: "512B", 2: "1KB", 3: "2KB", 4: "4KB", 5: "8KB", 6: "16KB"}

MEDIA_STATUS = {0: "Not Ready", 1: "Ready", 2: "Error", 3: "Disabled"}
RESET_NEEDED = {0: "none", 1: "Cold Reset", 2: "Warm Reset", 3: "Hot Reset",
                4: "CXL Reset"}
COMPONENT_TYPE = {0x00: "Switch", 0x03: "Type 3 Device", 0x04: "GFD"}

# ---------------------------------------------------------------------------
# CPMU event groups (Table 13-5) and their opcode mnemonics
# ---------------------------------------------------------------------------
CPMU_GROUP_NAME = {
    0x00: "Base",
    0x10: "CXL.cache D2H Req Channel",
    0x11: "CXL.cache D2H Rsp Channel",
    0x12: "CXL.cache H2D Req Channel",
    0x13: "CXL.cache H2D Rsp Channel",
    0x14: "CXL.cache Data",
    0x20: "CXL.mem M2S Req Channel",
    0x21: "CXL.mem M2S RwD Channel",
    0x22: "CXL.mem M2S BIRsp Channel",
    0x23: "CXL.mem S2M BISnp Channel",
    0x24: "CXL.mem S2M NDR Channel",
    0x25: "CXL.mem S2M DRS Channel",
    0x8000: "DDR Interface",
}

# Base group (Event Group 00h) has friendly event names instead of opcodes.
CPMU_BASE_EVENTS = {0: "Clock Ticks"}

CPMU_M2S_REQ = {
    0x0: "MemInv", 0x1: "MemRd", 0x2: "MemRdData", 0x3: "MemRdFwd",
    0x4: "MemWrFwd", 0x5: "MemRdTEE", 0x6: "MemRdDataTEE", 0x8: "MemSpecRd",
    0x9: "MemInvNT", 0xA: "MemClnEvct", 0xC: "MemSpecRdTEE", 0xD: "TEUpdate",
}

CPMU_M2S_RWD = {
    0x1: "MemWr", 0x2: "MemWrPtl", 0x4: "MemWrFwd(BISnp conflict)",
    0x5: "MemRdFill", 0x9: "MemWrTEE", 0xA: "MemWrPtlTEE", 0xD: "MemRdFillTEE",
}

CPMU_M2S_BIRSP = {
    0x0: "BIRspI", 0x1: "BIRspS", 0x2: "BIRspE",
    0x4: "BIRspIBlk", 0x5: "BIRspSBlk", 0x6: "BIRspEBlk",
}

CPMU_S2M_NDR = {
    0x0: "Cmp", 0x1: "Cmp-S", 0x2: "Cmp-E", 0x3: "Cmp-M",
    0x4: "BI-ConflictAck", 0x5: "CmpTEE",
}

CPMU_S2M_DRS = {0x0: "MemData", 0x1: "MemData-NXM", 0x2: "MemDataTEE"}

# Event Group 8000h - DDR Interface (Table 13-5, JEDEC DDR5 command counting)
CPMU_DDR_IF = {
    0x0: "ACT Count", 0x1: "PRE Count", 0x2: "CAS Rd", 0x3: "CAS Wr",
    0x4: "Refresh", 0x5: "Self Refresh Entry", 0x6: "RFM",
}

CPMU_OPCODE_TABLE = {
    0x20: CPMU_M2S_REQ,
    0x21: CPMU_M2S_RWD,
    0x22: CPMU_M2S_BIRSP,
    0x24: CPMU_S2M_NDR,
    0x25: CPMU_S2M_DRS,
    0x8000: CPMU_DDR_IF,
}

CPMU_COUNTER_TYPE = {
    0: "free-running", 1: "fixed-function", 2: "configurable", 3: "reserved",
}

CPMU_FILTER_NAME = {
    0: "HDM decoder mask",
    1: "Channel/Rank/BankGroup/Bank",
}

# Number of CPMU Counter Units field is 0-based (8.2.7.1.1).
def cpmu_count(v):
    return (v & 0x3F) + 1



def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def u64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


# ---------------------------------------------------------------------------
# PCI device
# ---------------------------------------------------------------------------
class PciDevice:
    def __init__(self, bdf):
        self.bdf = bdf
        self.path = os.path.join(SYSFS_PCI, bdf)
        self.config = None
        self.config_error = None

    def read_attr(self, name, default=None):
        try:
            with open(os.path.join(self.path, name)) as f:
                return f.read().strip()
        except OSError:
            return default

    @property
    def vendor(self):
        v = self.read_attr("vendor")
        return int(v, 16) if v else None

    @property
    def device(self):
        v = self.read_attr("device")
        return int(v, 16) if v else None

    @property
    def class_code(self):
        v = self.read_attr("class")
        return int(v, 16) if v else None

    def load_config(self):
        """Read 4 KB of config space (needs root). Falls back to lspci -xxx."""
        self.config = None
        self.config_error = None
        cfg_path = os.path.join(self.path, "config")
        try:
            with open(cfg_path, "rb") as f:
                data = f.read(4096)
            if len(data) >= 64:
                self.config = bytearray(data)
                if len(self.config) < 4096:
                    self.config.extend(b"\xff" * (4096 - len(self.config)))
                return True
        except PermissionError:
            self.config_error = "permission denied reading %s (need root)" % cfg_path
        except OSError as e:
            self.config_error = "%s: %s" % (cfg_path, e)

        # Fallback: lspci can dump config without keeping the file open as root
        try:
            out = subprocess.run(
                ["lspci", "-s", self.bdf, "-xxx"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout:
                data = bytearray()
                for line in out.stdout.splitlines():
                    line = line.strip()
                    if not line or ":" not in line:
                        continue
                    head, _, rest = line.partition(":")
                    try:
                        int(head, 16)
                    except ValueError:
                        continue
                    for tok in rest.split():
                        data.append(int(tok, 16))
                if len(data) >= 64:
                    if len(data) < 4096:
                        data.extend(b"\xff" * (4096 - len(data)))
                    self.config = data
                    self.config_error = None
                    return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass

        return False

    # -- resource / BAR ----------------------------------------------------
    def bars(self):
        """
        Parse /sys/.../resource -> list of (index, start, end, flags).
        Line format: "<start> <end> <flags>"
        """
        out = []
        raw = self.read_attr("resource")
        if not raw:
            return out
        for idx, line in enumerate(raw.splitlines()):
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                start = int(parts[0], 16)
                end = int(parts[1], 16)
                flags = int(parts[2], 16)
            except ValueError:
                continue
            if end < start:
                continue
            out.append((idx, start, end, flags))
        return out

    def bar_start(self, index):
        for idx, start, end, flags in self.bars():
            if idx == index:
                return start
        return None

    def mmap_bar(self, index, size):
        """mmap BAR #index, at least `size` bytes. Returns (mm, file_obj)."""
        p = os.path.join(self.path, "resource%d" % index)
        if not os.path.exists(p):
            raise OSError("no such resource: %s" % p)
        fd = os.open(p, os.O_RDONLY | os.O_SYNC)
        try:
            mm = mmap.mmap(fd, size, mmap.MAP_SHARED,
                           mmap.PROT_READ)
        except Exception:
            os.close(fd)
            raise
        return mm

    # -- capability walk ---------------------------------------------------
    def extended_capabilities(self):
        """
        Walk the PCIe extended capability list starting at 0x100.
        Returns list of dicts: {offset, id, version, next, raw}
        """
        caps = []
        if not self.config:
            return caps
        off = 0x100
        seen = set()
        while 0x100 <= off <= 0xFFC and off not in seen:
            seen.add(off)
            hdr = u32(self.config, off)
            if hdr in (0x00000000, 0xFFFFFFFF):
                break
            cap_id = hdr & 0xFFFF
            cap_ver = (hdr >> 16) & 0xF
            nxt = (hdr >> 20) & 0xFFF
            caps.append({
                "offset": off,
                "id": cap_id,
                "version": cap_ver,
                "next": nxt,
                "hdr": hdr,
            })
            if nxt == 0 or nxt == off:
                break
            off = nxt
        return caps

    def find_cxl_dvsecs(self):
        """Return list of (offset, dvsec_id, revision, length) for CXL DVSECs."""
        found = []
        for cap in self.extended_capabilities():
            if cap["id"] != PCI_EXT_CAP_ID_DVSEC:
                continue
            off = cap["offset"]
            h1 = u32(self.config, off + 0x04)
            h2 = u32(self.config, off + 0x08)
            vendor = h1 & 0xFFFF
            if vendor != CXL_VENDOR_ID:
                continue
            revision = (h1 >> 16) & 0xF
            length = (h1 >> 20) & 0xFFF
            dvsec_id = h2 & 0xFFFF
            found.append({
                "offset": off,
                "dvsec_id": dvsec_id,
                "revision": revision,
                "length": length,
            })
        return found

    def regloc_blocks(self):
        """
        Parse the Register Locator DVSEC (8.1.9).

        Layout:
          +00h ext cap header
          +04h vendor[15:0] rev[19:16] len[31:20]
          +08h dvsec id[15:0]
          +0Ch register block 1 offset low
          +10h register block 1 offset high
          ...  8 bytes per entry
        """
        dvs = None
        for d in self.find_cxl_dvsecs():
            if d["dvsec_id"] == DVSEC_REGLOC:
                dvs = d
                break
        if dvs is None:
            return []

        blocks = []
        length = dvs["length"] or 0x0C
        n_entries = max(0, (length - 0x0C) // 8)
        for i in range(n_entries):
            off = dvs["offset"] + 0x0C + i * 8
            if off + 8 > len(self.config):
                break
            lo = u32(self.config, off)
            hi = u32(self.config, off + 4)
            bir = lo & 0x7
            block_id = (lo >> 8) & 0xFF
            blk_off = (((lo >> 16) & 0xFFFF) << 16) | (hi << 32)
            blocks.append({
                "index": i,
                "bir": bir,
                "block_id": block_id,
                "block_name": BLOCK_NAME.get(block_id, "Unknown"),
                "block_offset": blk_off,
                "vendor_specific": (block_id not in BLOCK_NAME) or block_id == 0xFF,
                "raw_lo": lo,
                "raw_hi": hi,
            })
        return blocks

    def cxl_device_dvsec(self):
        """DVSEC 0000h - PCIe DVSEC for CXL Devices (8.1.3)."""
        for d in self.find_cxl_dvsecs():
            if d["dvsec_id"] == DVSEC_DEVICE:
                return d
        return None

    def flexbus_dvsec(self):
        for d in self.find_cxl_dvsecs():
            if d["dvsec_id"] == DVSEC_FLEXBUS:
                return d
        return None

    def describe(self):
        return {
            "bdf": self.bdf,
            "vendor": self.vendor,
            "device": self.device,
            "class": self.class_code,
        }


# ---------------------------------------------------------------------------
# Component register decoding
# ---------------------------------------------------------------------------
def hdm_decoder_count(cap):
    v = cap & 0xF
    if v == 0:
        return 1
    if v <= 8:
        return v * 2
    if v <= 12:
        return (v - 4) * 4
    return -1


class ComponentBlock:
    """A 64 KB Component Register Block mapped from a BAR."""

    def __init__(self, dev, bir, block_offset, bar_start):
        self.dev = dev
        self.bir = bir
        self.block_offset = block_offset
        self.bar_start = bar_start
        self.base = bar_start + block_offset
        self.mm = None
        self.map_len = 0

    def open(self):
        # Map the whole BAR region from block_offset onward, need at least 64 KB
        if self.bar_start is None:
            raise OSError("BAR%d not assigned" % self.bir)
        span = 0
        for idx, start, end, flags in self.dev.bars():
            if idx == self.bir:
                span = end - start + 1
                break
        if span == 0:
            raise OSError("BAR%d has zero size" % self.bir)
        if self.block_offset >= span:
            raise OSError("block offset 0x%x beyond BAR%d size 0x%x"
                          % (self.block_offset, self.bir, span))
        need = min(0x10000, span - self.block_offset)
        self.mm = self.dev.mmap_bar(self.bir, span)
        self.map_len = need
        self.mm_off = self.block_offset
        return self

    def close(self):
        if self.mm is not None:
            try:
                self.mm.close()
            except Exception:
                pass
            self.mm = None

    def read32(self, off):
        """Read a 32-bit Component register at block-relative offset.

        Per 8.2.3, 32-bit registers must be accessed as a 4-byte quantity.
        """
        if off + 4 > self.map_len:
            return None
        return struct.unpack_from("<I", self.mm, self.mm_off + off)[0]

    def read64(self, off):
        if off + 8 > self.map_len:
            return None
        return struct.unpack_from("<Q", self.mm, self.mm_off + off)[0]

    def hexdump(self, off, length=0x40):
        lines = []
        for row in range(0, length, 16):
            vals = []
            for c in range(16):
                v = self.read32(off + row + c) if (off + row + c + 4) <= self.map_len else None
                vals.append("--------" if v is None else "%08x" % v)
            lines.append("  0x%04x  %s" % (off + row, " ".join(vals)))
        return lines

    # -- cachemem range parsing -------------------------------------------
    def parse_cachemem_range(self, range_off, label):
        """
        Parse a 4 KB CXL.cachemem range.

        8.2.4.1 / Table 8-23:
          range_off + 0x00 : CXL_Capability_Header
          range_off + 0x04 : capability header[1] ... [Array_Size]
        """
        result = {"range_offset": range_off, "label": label, "caps": [],
                  "errors": []}

        hdr = self.read32(range_off + 0x00)
        if hdr is None:
            result["errors"].append("cannot read capability header")
            return result

        cap_id = hdr & 0xFFFF
        if cap_id != 0x0001:
            result["errors"].append(
                "capability header ID is 0x%04x, expected 0x0001 "
                "(not a valid CXL.cachemem range)" % cap_id)
            return result

        result["header_id"] = cap_id
        result["header_version"] = (hdr >> 16) & 0xF
        result["cm_version"] = (hdr >> 20) & 0xF
        array_size = (hdr >> 24) & 0xFF
        result["array_size"] = array_size

        for i in range(1, array_size + 1):
            elem_off = range_off + i * 4
            v = self.read32(elem_off)
            if v is None:
                result["errors"].append("array element %d out of range" % i)
                break
            eid = v & 0xFFFF
            ever = (v >> 16) & 0xF
            ptr = (v >> 20) & 0xFFF
            # Pointer is a BYTE offset relative to CXL_Capability_Header.
            abs_off = range_off + ptr
            result["caps"].append({
                "elem_index": i,
                "elem_offset": elem_off,
                "id": eid,
                "name": CM_CAP_NAME.get(eid, "Reserved/Undefined (0x%04x)" % eid),
                "version": ever,
                "pointer": ptr,
                "abs_offset": abs_off,
            })
        return result

    def decode_capability(self, cap, verbose=True):
        """Decode one capability structure into key/value lines."""
        out = []
        eid = cap["id"]
        off = cap["abs_offset"]

        if eid == 0x0000:
            return out  # NULL capability: nothing to decode

        if eid == 0x0002:  # RAS, 8.2.4.17
            ucs = self.read32(off + 0x00)
            ucm = self.read32(off + 0x04)
            ucv = self.read32(off + 0x08)
            cst = self.read32(off + 0x0C)
            cmd = self.read32(off + 0x10)
            ctl = self.read32(off + 0x14)
            if ucs is not None:
                out.append("Uncorrectable Status  = 0x%08x" % ucs)
                out.append("Uncorrectable Mask    = 0x%08x" % (ucm or 0))
                out.append("Uncorrectable Severity= 0x%08x" % (ucv or 0))
                out.append("Correctable Status    = 0x%08x" % (cst or 0))
                out.append("Correctable Mask      = 0x%08x" % (cmd or 0))
                if ctl is not None:
                    out.append("First Error Pointer   = %d" % (ctl & 0x3F))
                    out.append("Multiple Header Rec   = %d" % ((ctl >> 9) & 1))
                    out.append("Poison Enabled        = %d" % ((ctl >> 13) & 1))
                if ucs:
                    names = {
                        0: "Cache_Data_Parity", 1: "Cache_Address_Parity",
                        2: "Cache_BE_Parity", 3: "Cache_Data_ECC",
                        4: "Mem_Data_ECC", 5: "Mem_Address_Parity",
                        6: "Mem_BE_Parity", 7: "Mem_Data_Parity",
                        8: "ATA_Parity", 14: "Internal_Error",
                        15: "IDE_Tx_Error", 16: "IDE_Rx_Error",
                    }
                    hit = [n for b, n in names.items() if ucs & (1 << b)]
                    if hit:
                        out.append("  set UC bits: " + ", ".join(hit))

        elif eid == 0x0004:  # Link, 8.2.4.19
            lcap = self.read64(off + 0x00)
            lctl = self.read64(off + 0x08)
            if lcap is not None:
                out.append("Link Capability       = 0x%016x" % lcap)
                out.append("  Version Supported   = %d (deprecated)"
                           % (lcap & 0xF))
                out.append("  Version Received    = %d (deprecated)"
                           % ((lcap >> 4) & 0xF))
                out.append("  No_LL_Reset_Support = %d" % ((lcap >> 58) & 1))
            if lctl is not None:
                init_state = (lctl >> 3) & 0x3
                out.append("Link Control/Status   = 0x%016x" % lctl)
                out.append("  LL_Reset            = %d" % (lctl & 1))
                out.append("  LL_Init_Stall       = %d" % ((lctl >> 1) & 1))
                out.append("  LL_Crd_Stall        = %d" % ((lctl >> 2) & 1))
                out.append("  INIT_State          = %db (%s)" % (
                    init_state,
                    ["NOT_RDY_FOR_INIT", "PARAM_EX",
                     "CRD_RETURN_STALL", "INIT_DONE"][init_state]))

        elif eid == 0x0005:  # HDM Decoder, 8.2.4.20
            hcap = self.read32(off + 0x00)
            gctl = self.read32(off + 0x04)
            if hcap is not None:
                ndec = hdm_decoder_count(hcap)
                tgt = (hcap >> 4) & 0xF
                out.append("Decoder Count code    = 0x%x -> %s decoders"
                           % (hcap & 0xF, ndec if ndec > 0 else "invalid"))
                out.append("Target Count          = %d%s"
                           % (tgt, " (N/A for devices; USP/HB only)" if tgt == 0 else ""))
                out.append("A11to8 Interleave     = %d" % ((hcap >> 8) & 1))
                out.append("A14to12 Interleave    = %d" % ((hcap >> 9) & 1))
                out.append("Poison On Decode Err  = %d" % ((hcap >> 10) & 1))
                out.append("3/6/12-Way Capable    = %d" % ((hcap >> 11) & 1))
                out.append("16-Way Capable        = %d" % ((hcap >> 12) & 1))
                out.append("UIO Capable           = %d" % ((hcap >> 13) & 1))
                out.append("MemData-NXM Capable   = %d" % ((hcap >> 20) & 1))
                out.append("Coherency Models      = %db"
                           % ((hcap >> 21) & 0x3))
            if gctl is not None:
                out.append("Global Control        = 0x%08x" % gctl)
                out.append("  Poison On Dec Err En= %d" % (gctl & 1))
                out.append("  HDM Decoder Enable  = %d" % ((gctl >> 1) & 1))

            if ndec > 0:
                out.append("")
                out.append("  %-3s %-14s %-12s %-6s %-4s %-4s %-6s %s"
                           % ("n", "Base", "Size", "IG", "IW", "Cmt", "Type", "Notes"))
                for n in range(ndec):
                    # Decoder n registers are relative to this capability's base
                    bl = self.read32(off + 0x20 * n + 0x10)
                    bh = self.read32(off + 0x20 * n + 0x14)
                    sl = self.read32(off + 0x20 * n + 0x18)
                    sh = self.read32(off + 0x20 * n + 0x1C)
                    ctl = self.read32(off + 0x20 * n + 0x20)
                    if None in (bl, bh, sl, sh, ctl):
                        continue
                    base = ((bh << 32) | (bl & 0xF0000000))
                    size = ((sh << 32) | (sl & 0xF0000000))
                    ig = IG_MAP.get(ctl & 0xF, "?")
                    iw = IW_MAP.get((ctl >> 4) & 0xF, "?")
                    committed = (ctl >> 10) & 1
                    committed_err = (ctl >> 11) & 1
                    trt = (ctl >> 12) & 1
                    notes = []
                    if committed_err:
                        notes.append("ERROR_NOT_COMMITTED")
                    if not committed:
                        notes.append("inactive")
                    if ctl & (1 << 13):
                        notes.append("BI")
                    out.append("  %-3d 0x%012x 0x%-10x %-6s %-4s %-4s %-6s %s"
                               % (n, base, size, ig, iw,
                                  "Y" if committed else "n",
                                  "HDM-H" if trt else "HDM-D",
                                  " ".join(notes)))

        elif eid == 0x000A:  # CXL.cachemem Extended Ranges, 8.2.4.25.1
            bm = self.read32(off + 0x00)
            if bm is not None:
                bm &= 0xFFFF
                listed = []
                for bit in range(16):
                    if bm & (1 << bit):
                        if bit in (0, 1, 14):
                            listed.append("bit%d(reserved!)" % bit)
                        else:
                            base = bit * 0x1000
                            listed.append("bit%d=0x%04x-0x%04x"
                                          % (bit, base, base + 0xFFF))
                out.append("Extended Range Bitmap = 0x%04x" % bm)
                out.append("  ranges: " + (", ".join(listed) if listed else "none"))

        elif eid == 0x0007:  # IDE, 8.2.4.22
            icap = self.read32(off + 0x00)
            if icap is not None:
                out.append("CXL IDE Capable       = %d" % (icap & 1))
                out.append("Skid Mode             = %d" % ((icap >> 1) & 1))
                out.append("Containment Mode      = %d" % ((icap >> 2) & 1))
                out.append("Supported Algorithms  = 0x%02x"
                           % ((icap >> 17) & 0x1F))

        elif eid == 0x0003:  # Security, 8.2.4.18
            pol = self.read32(off + 0x00)
            if pol is not None:
                tl = pol & 0x3
                out.append("Trust Level           = %db (%s)" % (
                    tl, ["Trusted", "Device-attached only", "Untrusted",
                         "reserved"][tl]))
                out.append("Block CXL.cache HDM-DB= %d" % ((pol >> 2) & 1))

        elif eid == 0x0008:  # Snoop filter, 8.2.4.23
            gid = self.read32(off + 0x00)
            cap = self.read32(off + 0x04)
            if gid is not None:
                out.append("Group ID              = 0x%04x" % (gid & 0xFFFF))
            if cap is not None:
                out.append("Capacity              = %d x 64K" % cap)

        elif eid == 0x0009:  # Timeout and Isolation, 8.2.4.24
            tc = self.read32(off + 0x08)
            ts = self.read32(off + 0x0C)
            if tc is not None:
                out.append("Control               = 0x%08x" % tc)
            if ts is not None:
                out.append("Status                = 0x%08x" % ts)

        elif eid == 0x000F:  # Extended HDM decoder, 8.2.4.30
            ecap = self.read32(off + 0x00)
            if ecap is not None:
                out.append("Decoder Count code    = 0x%x -> %s decoders"
                           % (ecap & 0xF, hdm_decoder_count(ecap)))

        return out

    def dump_arbmux(self):
        out = ["CXL ARB/MUX registers (base 0xE000, 8.2.5)"]
        pm = self.read32(0xE000)
        ucs = self.read32(0xE004)
        ucm = self.read32(0xE008)
        arb_io = self.read32(0xE180)
        arb_cm = self.read32(0xE1C0)
        if pm is not None:
            pval = (pm >> 1) & 0x3
            # 00b = 1 ms, all other encodings reserved (8.2.5.1)
            pstr = "1ms" if pval == 0 else "reserved(%db)" % pval
            out.append("  PM Timeout Control  = 0x%08x  enable=%d val=%s"
                       % (pm, pm & 1, pstr))
        if ucs is not None:
            out.append("  UC Error Status     = 0x%08x" % ucs)
        if ucm is not None:
            out.append("  UC Error Mask       = 0x%08x" % ucm)
        if arb_io is not None:
            out.append("  Arb Ctrl CXL.io     = 0x%08x  weight=%d"
                       % (arb_io, (arb_io >> 4) & 0xF))
        if arb_cm is not None:
            out.append("  Arb Ctrl cache/mem  = 0x%08x  weight=%d"
                       % (arb_cm, (arb_cm >> 4) & 0xF))
        return out

    def dump(self, verbose=False):
        """Full walk of the 64 KB block per Table 8-21."""
        lines = []
        lines.append("Component Register Block @ phys 0x%x (BAR%d + 0x%x)"
                     % (self.base, self.bir, self.block_offset))
        lines.append("  mapped 0x%x bytes" % self.map_len)
        lines.append("")

        # --- Table 8-21 overview
        lines.append("Table 8-21 ranges:")
        for start, size, desc in COMPONENT_RANGES:
            lines.append("  0x%04x - 0x%04x  %-5s  %s"
                         % (start, start + size - 1,
                            "%dK" % (size // 1024), desc))
        lines.append("")

        # --- Primary range
        prim = self.parse_cachemem_range(0x1000, "CXL.cachemem Primary Range")
        lines.extend(self._render_range(prim, verbose))

        # --- Extended ranges, discovered through cap ID 000Ah
        ext_bits = []
        for c in prim["caps"]:
            if c["id"] == 0x000A:
                bm = self.read32(c["abs_offset"])
                if bm is not None:
                    for bit in range(16):
                        if bm & (1 << bit) and bit not in (0, 1, 14):
                            ext_bits.append(bit)

        if ext_bits:
            lines.append("Extended Ranges advertised: %d"
                         % len(ext_bits))
            for bit in ext_bits:
                rng = bit * 0x1000
                res = self.parse_cachemem_range(rng, "Extended Range @ 0x%04x" % rng)
                lines.append("")
                lines.extend(self._render_range(res, verbose))
        else:
            lines.append("Extended Ranges advertised: none")
        lines.append("")

        # --- ARB/MUX
        lines.extend(self.dump_arbmux())
        return lines

    def _render_range(self, res, verbose):
        lines = []
        lines.append("=== %s (offset 0x%04x) ===" % (res["label"], res["range_offset"]))
        if res["errors"]:
            for e in res["errors"]:
                lines.append("  [skip] %s" % e)
            return lines
        lines.append("  CXL_Capability_Header: ID=0x%04x ver=%d cm_ver=%d array_size=%d"
                     % (res["header_id"], res["header_version"],
                        res["cm_version"], res["array_size"]))
        if not res["caps"]:
            lines.append("  (empty capability array)")
            return lines
        lines.append("")
        lines.append("  %-3s %-6s %-6s %-9s %-4s %s"
                     % ("#", "ID", "Ptr", "AbsOff", "Ver", "Name"))
        for c in res["caps"]:
            lines.append("  %-3d 0x%04x 0x%03x  0x%06x   %-4d %s"
                         % (c["elem_index"], c["id"], c["pointer"],
                            c["abs_offset"], c["version"], c["name"]))
        lines.append("")
        for c in res["caps"]:
            detail = self.decode_capability(c, verbose)
            if detail:
                lines.append("  [%s @ 0x%04x]" % (c["name"], c["abs_offset"]))
                for d in detail:
                    lines.append("    " + d)
                lines.append("")
        return lines


# ---------------------------------------------------------------------------
# CPMU Register Interface (8.2.7)
# ---------------------------------------------------------------------------
class CpmuBlock(ComponentBlock):
    """CPMU register block. Layout is Table 8-32 (Version=1).

    Offsets are relative to the CPMU block base given by the Register Locator
    DVSEC entry with Register Block Identifier 04h.
    """

    def event_name(self, gidx, ev_index, groups):
        """Map an Event Group ID Index + bit position to a readable name."""
        if gidx >= len(groups):
            return "bit%d" % ev_index
        gid = groups[gidx]["group"]
        if gid == 0x00:
            return CPMU_BASE_EVENTS.get(ev_index, "ev%d" % ev_index)
        table = CPMU_OPCODE_TABLE.get(gid)
        if table is None:
            # Channel groups whose Event ID is just the opcode encoding.
            if gid in (0x10, 0x11, 0x12, 0x13):
                return "opcode%d" % ev_index
            if gid == 0x14:
                return {0: "D2H Data", 1: "H2D Data"}.get(ev_index,
                                                          "ev%d" % ev_index)
            return "ev%d" % ev_index
        return table.get(ev_index, "reserved%d" % ev_index)

    def dump(self, verbose=False):
        lines = ["CPMU Register Block @ phys 0x%x (BAR%d + 0x%x, 8.2.7)"
                 % (self.base, self.bir, self.block_offset)]

        cap = self.read64(0x00)
        if cap is None:
            lines.append("  [!] cannot read CPMU Capability")
            return lines

        version = (cap >> 60) & 0xF
        nunits = cpmu_count(cap)
        width = (cap >> 8) & 0xFF
        nevcaps = ((cap >> 20) & 0x1F) + 1
        filters = (cap >> 32) & 0xFF
        imn = (cap >> 44) & 0xF
        wr_frozen = (cap >> 48) & 1
        freeze_sup = (cap >> 49) & 1
        irq_sup = (cap >> 50) & 1

        lines.append("  CPMU Capability        = 0x%016x" % cap)
        lines.append("    Version              = %d" % version)
        lines.append("    Counter Units        = %d" % nunits)
        lines.append("    Counter Width        = %d bits" % width)
        lines.append("    Event Cap Regs       = %d" % nevcaps)
        lines.append("    Filters Supported    = 0x%02x%s"
                     % (filters,
                        " (%s)" % ", ".join(
                            "%d:%s" % (i, CPMU_FILTER_NAME.get(i, "?"))
                            for i in range(8) if filters & (1 << i))
                        if filters else " (none)"))
        lines.append("    Interrupt Msg Number = %d" % imn)
        lines.append("    Writable while Frozen= %d" % wr_frozen)
        lines.append("    Freeze Support       = %d" % freeze_sup)
        lines.append("    Interrupt on Overflow= %d" % irq_sup)

        # -- Overflow Status (10h) / Freeze (18h)
        over = self.read64(0x10)
        if over is not None:
            lines.append("  Overflow Status        = 0x%016x%s"
                         % (over, "  [OVF]" if over else "  (none)"))
        if freeze_sup:
            fz = self.read64(0x18)
            if fz is not None:
                lines.append("  Freeze                 = 0x%016x%s"
                             % (fz, "  [FROZEN]" if fz else "  (running)"))

        # -- Event Capabilities (100h + n*8)
        groups = []
        for i in range(nevcaps):
            lo = self.read32(0x100 + i * 8)
            hi = self.read32(0x104 + i * 8)
            if lo is None or hi is None:
                break
            v = (hi << 32) | lo
            vendor = (v >> 48) & 0xFFFF
            group = (v >> 32) & 0xFFFF
            events = v & 0xFFFFFFFF
            if v == 0 and i > 0:
                break
            groups.append({"group": group, "vendor": vendor,
                           "events": events})

        lines.append("")
        lines.append("  Event Groups (Table 13-5): %d" % len(groups))
        for i, g in enumerate(groups):
            name = CPMU_GROUP_NAME.get(g["group"],
                                       "Vendor/Reserved 0x%04x" % g["group"])
            lines.append("    [%d] vendor=0x%04x group=0x%04x %-28s events=0x%08x"
                         % (i, g["vendor"], g["group"], name, g["events"]))
            mn = []
            for bit in range(32):
                if not (g["events"] >> bit) & 1:
                    continue
                mn.append(self.event_name(i, bit, groups))
            if mn:
                lines.append("         %s" % ", ".join(mn))

        # -- Counter Units: Configuration (200h + n*8), Filter, Data (C00h)
        lines.append("")
        lines.append("  %-4s %-15s %-4s %-3s %-3s %-4s %-4s %-6s %s"
                     % ("n", "Type", "En", "IE", "GF", "Thr", "Edge", "Group",
                        "Events"))
        nfilter_ids = bin(filters).count("1")
        any_enabled = False
        for n in range(nunits):
            lo = self.read32(0x200 + n * 8)
            hi = self.read32(0x204 + n * 8)
            if lo is None or hi is None:
                break
            v = (hi << 32) | lo
            ctype = v & 0x3
            en = (v >> 8) & 1
            if en or ctype == 0:
                any_enabled = True
            ie = (v >> 9) & 1
            gf = (v >> 10) & 1
            edge = (v >> 11) & 1
            inv = (v >> 12) & 1
            thr = (v >> 16) & 0xFF
            events = (v >> 24) & 0xFFFFFFFF
            gidx = (v >> 59) & 0x1F
            names = []
            if events:
                for bit in range(32):
                    if (events >> bit) & 1:
                        names.append(self.event_name(gidx, bit, groups))
            else:
                names.append("(none)")
            lines.append("  %-4d %-15s %-4d %-3d %-3d %-4d %-4d %-6d %s"
                         % (n, CPMU_COUNTER_TYPE.get(ctype, "?"), en, ie, gf,
                            thr, edge, gidx, ", ".join(names) if names else "-"))

            if verbose and inv:
                lines.append("       Invert=1 (threshold compares <=)")

            # Filter registers: Filter ID 0 at 400h + n*0x20, ID 1 at +4.
            # Table 13-5 assigns Filter ID=0 to every CXL.mem group
            # (20h..25h) and Filter ID=1 to the DDR Interface group (8000h).
            gid = groups[gidx]["group"] if gidx < len(groups) else None
            if gid == 0x8000:
                applicable = [1]
            elif gid is not None and 0x20 <= gid <= 0x25:
                applicable = [0]
            else:
                applicable = []
            for fid in applicable:
                if fid >= nfilter_ids:
                    continue
                foff = 0x400 + n * 0x20 + fid * 4
                fv = self.read32(foff)
                if fv is None:
                    continue
                if fv == 0xFFFFFFFF:
                    lines.append("       Filter[%d] %-24s = 0xffffffff "
                                 "(reset default, no filtering)"
                                 % (fid, CPMU_FILTER_NAME.get(fid, "?")))
                    continue
                desc = self.describe_filter(fid, fv)
                lines.append("       Filter[%d] %-24s = 0x%08x"
                             % (fid, CPMU_FILTER_NAME.get(fid, "?"), fv))
                if desc:
                    lines.append("         %s" % desc)

        # -- Counter Data (C00h + n*8), read as 8-byte quantities (8.2.7.2.3)
        data = []
        for n in range(nunits):
            d = self.read64(0xC00 + n * 8)
            if d is None:
                break
            data.append(d)
        lines.append("")
        lines.append("  Counter Data (8.2.7.2.3)")
        if not any_enabled:
            lines.append("  NOTE: no Counter Unit is enabled (Counter Enable=0),"
                         " so every counter reads 0 by")
            lines.append("        design. Counting starts only after software"
                         " sets Counter Enable; this")
            lines.append("        tool is read-only and never writes registers.")
        lines.append("  %-4s %-18s %-18s %s" % ("n", "Raw", "Value", "Note"))
        mask = (1 << width) - 1 if width else None
        for n, d in enumerate(data):
            note = ""
            if mask is not None and d & ~mask:
                note = "bits above %d set" % width
            lines.append("  %-4d 0x%016x 0x%-16x %s" % (n, d, d, note))

        return lines

    @staticmethod
    def describe_filter(fid, v):
        if fid == 0:
            decs = ["HDM%d" % i for i in range(32) if (v >> i) & 1]
            return "decoders: %s" % (", ".join(decs) if decs else "none")
        if fid == 1:
            bank = v & 0xFF
            bgroup = (v >> 8) & 0xFF
            rank = (v >> 16) & 0xFF
            chan = (v >> 24) & 0xFF
            def f(x):
                return "all" if x == 0xFF else str(x)
            return ("Bank=%s BankGroup=%s Rank=%s Channel=%s"
                    % (f(bank), f(bgroup), f(rank), f(chan)))
        return ""


# ---------------------------------------------------------------------------
# CXL Device Register Block (8.2.8)
# ---------------------------------------------------------------------------
class DeviceBlock:
    def __init__(self, dev, bir, block_offset, bar_start):
        self.dev = dev
        self.bir = bir
        self.block_offset = block_offset
        self.bar_start = bar_start
        self.base = bar_start + block_offset
        self.mm = None
        self.mm_off = 0
        self.map_len = 0

    def open(self):
        span = 0
        for idx, start, end, flags in self.dev.bars():
            if idx == self.bir:
                span = end - start + 1
                break
        if span == 0:
            raise OSError("BAR%d has zero size" % self.bir)
        self.mm = self.dev.mmap_bar(self.bir, span)
        self.mm_off = self.block_offset
        self.map_len = span - self.block_offset
        return self

    def close(self):
        if self.mm is not None:
            try:
                self.mm.close()
            except Exception:
                pass
            self.mm = None

    def read32(self, off):
        if off + 4 > self.map_len:
            return None
        return struct.unpack_from("<I", self.mm, self.mm_off + off)[0]

    def read64(self, off):
        if off + 8 > self.map_len:
            return None
        return struct.unpack_from("<Q", self.mm, self.mm_off + off)[0]

    def dump(self, verbose=False):
        lines = ["CXL Device Register Block @ phys 0x%x (BAR%d + 0x%x, 8.2.8)"
                 % (self.base, self.bir, self.block_offset)]
        arr_lo = self.read64(0x00)
        if arr_lo is None:
            lines.append("  [skip] cannot read capabilities array")
            return lines
        arr_hi = self.read64(0x08) or 0
        cap_id = arr_lo & 0xFFFF
        version = (arr_lo >> 16) & 0xFF
        dtype = (arr_lo >> 24) & 0xF
        count = (arr_lo >> 32) & 0xFFFF
        if cap_id != 0:
            lines.append("  [skip] array cap id 0x%04x != 0" % cap_id)
            return lines
        tname = {0: "inferred from Class Code", 1: "Memory Device",
                 2: "Switch Mailbox CCI"}.get(dtype, "reserved")
        lines.append("  Array: version=%d type=%d (%s) count=%d"
                     % (version, dtype, tname, count))

        for i in range(1, min(count, 32) + 1):
            off = i * 0x10
            lo = self.read64(off)
            hi = self.read64(off + 8) or 0
            if lo is None:
                break
            cid = lo & 0xFFFF
            cver = (lo >> 16) & 0xFF
            cptr = (lo >> 32) & 0xFFFFFFFF
            clen = hi & 0xFFFFFFFF
            name = DEV_CAP_NAME.get(cid, "Unknown/Reserved (0x%04x)" % cid)
            lines.append("")
            lines.append("  [%s] id=0x%04x ver=%d off=0x%x len=0x%x"
                         % (name, cid, cver, cptr, clen))
            if cid == 0x0001:      # Device Status (8.2.8.3.1)
                es = self.read32(cptr)
                if es is not None:
                    logs = [n for b, n in
                            [(0, "Informational"), (1, "Warning"),
                             (2, "Failure"), (3, "Fatal"), (4, "DCD")]
                            if es & (1 << b)]
                    lines.append("    Event Status       = 0x%08x  %s"
                                 % (es, ",".join(logs) if logs else "clear"))
            elif cid == 0x4000:    # Memory Device Status (8.2.8.5.1.1)
                st = self.read64(cptr)
                if st is not None:
                    media = (st >> 2) & 0x3
                    reset = (st >> 5) & 0x7
                    lines.append("    Device Fatal       = %d" % (st & 1))
                    lines.append("    FW Halt            = %d" % ((st >> 1) & 1))
                    lines.append("    Media Status       = %s"
                                 % MEDIA_STATUS.get(media, "?"))
                    lines.append("    Mailbox Ready      = %d" % ((st >> 4) & 1))
                    lines.append("    Reset Needed       = %s"
                                 % RESET_NEEDED.get(reset, "?"))
            elif cid in (0x0002, 0x0003):   # Mailbox (8.2.8.4)
                caps = self.read32(cptr + 0x00)
                mctl = self.read32(cptr + 0x04)
                stat_lo = self.read32(cptr + 0x10)
                stat_hi = self.read32(cptr + 0x14)
                if caps is not None:
                    psz = caps & 0x1F
                    lines.append("    Payload Size       = 2^%d = %d bytes"
                                 % (psz, 1 << psz))
                    lines.append("    Doorbell IRQ Cap   = %d" % ((caps >> 5) & 1))
                    lines.append("    BG Cmd IRQ Cap     = %d" % ((caps >> 6) & 1))
                    lines.append("    IRQ Msg Number     = %d" % ((caps >> 7) & 0xF))
                if mctl is not None:
                    lines.append("    Doorbell           = %d" % (mctl & 1))
                if stat_lo is not None and stat_hi is not None:
                    rc = stat_hi & 0xFFFF
                    lines.append("    Return Code        = 0x%04x" % rc)
        return lines


# ---------------------------------------------------------------------------
# Device-level driver
# ---------------------------------------------------------------------------
def dump_vendor_block(dev, b, bar_start, verbose):
    """Render a Register Block whose ID is not defined by the CXL spec.

    8.1.9.1 only says the block identifier and the block contents are vendor
    defined; there is no standard layout to decode. So this reports verified
    facts (window address, vendor id match, signature strings) and explicitly
    refuses to invent field meanings.
    """
    lines = []
    try:
        blk = ComponentBlock(dev, b["bir"], b["block_offset"], bar_start).open()
    except OSError as e:
        return ["Vendor Specific block id=0x%02x: %s" % (b["block_id"], e)]

    try:
        lines.append("Vendor Specific block id=0x%02x @ phys 0x%x (BAR%d + 0x%x)"
                     % (b["block_id"], bar_start + b["block_offset"],
                        b["bir"], b["block_offset"]))

        w0 = blk.read32(0x00)
        if w0 is not None:
            vid = w0 & 0xFFFF
            match = ""
            if dev.vendor is not None:
                match = ("  (= PCI vendor 0x%04x)" % dev.vendor
                         if vid == dev.vendor
                         else "  (PCI vendor is 0x%04x)" % dev.vendor)
            lines.append("  +0000 vendor id        = 0x%04x%s" % (vid, match))

        for row in range(0, 0x40 if not verbose else 0x100, 16):
            v = [blk.read32(row + i) for i in range(0, 16, 4)]
            if all(x is None for x in v):
                continue
            lines.append("  +0x%04x: %s"
                         % (row, " ".join("--------" if x is None
                                          else "%08x" % x for x in v)))

        # Printable ASCII runs in the first 4 KB. Vendor headers frequently
        # carry an ASCII build/signature string; report it verbatim, no guess.
        def byte_at(off):
            w = blk.read32(off & ~3)
            if w is None:
                return 0
            return (w >> (8 * (off & 3))) & 0xFF

        runs = []
        cur = []
        for o in range(0, 0x1000):
            ch = byte_at(o)
            if 32 <= ch < 127:
                cur.append(chr(ch))
            else:
                if len(cur) >= 8:
                    runs.append((o - len(cur), "".join(cur)))
                cur = []
        if len(cur) >= 8:
            runs.append((0x1000 - len(cur), "".join(cur)))

        if runs:
            lines.append("  ASCII signature strings (first 4 KB):")
            for off, s in runs[:8]:
                lines.append("    +0x%04x  \"%s\"" % (off, s))

        lines.append("  Layout: vendor defined (8.1.9.1); fields not interpreted.")
        return lines
    finally:
        blk.close()


def hdm_decoder_enabled(dev, blocks):
    """Best-effort probe of HDM Decoder Global Control[1] (8.2.4.20.2).

    Returns True/False, or None when the component block is not reachable.
    Used only to annotate the DVSEC Range registers, whose Base fields stop
    being meaningful once HDM decoding is enabled (8.1.3.8.4).
    """
    for b in blocks:
        if b["block_id"] != 0x01:
            continue
        bar_start = dev.bar_start(b["bir"])
        if not bar_start:
            return None
        try:
            blk = ComponentBlock(dev, b["bir"], b["block_offset"], bar_start).open()
        except OSError:
            return None
        try:
            prim = blk.parse_cachemem_range(0x1000, "probe")
            for cap in prim["caps"]:
                if cap["id"] != 0x0005:
                    continue
                gctl = blk.read32(cap["abs_offset"] + 0x04)
                if gctl is None:
                    return None
                return bool((gctl >> 1) & 1)
        finally:
            blk.close()
        return None
    return None


def dump_pcie_side(dev, verbose):
    lines = []
    blocks = dev.regloc_blocks()
    devs = dev.find_cxl_dvsecs()
    lines.append("CXL DVSECs found: %d" % len(devs))
    for d in devs:
        lines.append("  +0x%03x  ID=0x%04x rev=%d len=0x%02x  %s"
                     % (d["offset"], d["dvsec_id"], d["revision"],
                        d["length"], DVSEC_NAME.get(d["dvsec_id"], "?")))

    # DVSEC 0000h - CXL device capability summary
    dv = dev.cxl_device_dvsec()
    if dv is not None:
        off = dv["offset"]
        cap = u32(dev.config, off + 0x0A)
        hdm_count = (cap >> 4) & 0x3
        lines.append("")
        lines.append("DVSEC 0000h CXL Capability = 0x%04x" % (cap & 0xFFFF))
        lines.append("  Cache_Capable   = %d" % (cap & 1))
        lines.append("  IO_Capable      = %d" % ((cap >> 1) & 1))
        lines.append("  Mem_Capable     = %d" % ((cap >> 2) & 1))
        lines.append("  Mem_HwInit_Mode = %d" % ((cap >> 3) & 1))
        lines.append("  HDM_Count       = %d" % hdm_count)
        lines.append("  CXL Reset Cap   = %d" % ((cap >> 7) & 1))

        ctrl = u16(dev.config, off + 0x0C)
        lines.append("  Mem_Enable      = %d" % ((ctrl >> 2) & 1))

        # DVSEC Range Base registers lose their meaning once the HDM decoders
        # are enabled (8.1.3.8.4); they then sit at their 0h default while the
        # real mapping is in the HDM decoders.
        hdm_enabled = hdm_decoder_enabled(dev, blocks)

        for rng in range(hdm_count):
            base_lo_off = off + 0x24 + rng * 0x10
            size_lo_off = off + 0x1C + rng * 0x10
            if base_lo_off + 4 > len(dev.config):
                continue
            size_hi = u32(dev.config, size_lo_off - 4)
            size_lo = u32(dev.config, size_lo_off)
            base_hi = u32(dev.config, base_lo_off - 4)
            base_l = u32(dev.config, base_lo_off)
            info = size_lo & 1
            active = (size_lo >> 1) & 1
            media = (size_lo >> 2) & 0x7
            base = (base_hi << 32) | (base_l & 0xF0000000)
            size = (size_hi << 32) | (size_lo & 0xF0000000)
            note = ""
            if base == 0 and hdm_enabled:
                # 8.1.3.8.4: once HDM Decoder Enable=1, these Base registers no
                # longer take part in CXL.mem address decode and stay at their
                # 0h default. The live mapping lives in the HDM decoders.
                note = "  (not used: HDM Decoder Enable=1, see HDM decoders)"
            lines.append("  Range%d: base=0x%010x size=0x%-10x valid=%d active=%d media=%db%s"
                         % (rng + 1, base, size, info, active, media, note))

    fb = dev.flexbus_dvsec()
    if fb is not None:
        off = fb["offset"]
        cap = u32(dev.config, off + 0x0A)
        ctrl = u32(dev.config, off + 0x0C)
        lines.append("")
        lines.append("DVSEC 0007h Flex Bus Port Capability = 0x%04x" % (cap & 0xFFFF))
        lines.append("  Cache_Capable   = %d" % (cap & 1))
        lines.append("  Mem_Capable     = %d" % ((cap >> 2) & 1))
        lines.append("  68B Flit + VH   = %d" % ((cap >> 5) & 1))
        lines.append("  MLD Capable     = %d" % ((cap >> 6) & 1))
        lines.append("  256B Flit Cap   = %d" % ((cap >> 13) & 1))
        lines.append("  Cache_Enable    = %d" % (ctrl & 1))
        lines.append("  Mem_Enable      = %d" % ((ctrl >> 2) & 1))

    lines.append("")
    lines.append("Register Locator DVSEC blocks: %d" % len(blocks))
    for b in blocks:
        lines.append("  [%d] BIR=%d (BAR%02xh) id=0x%02x %-32s offset=0x%x"
                     % (b["index"], b["bir"], 0x10 + b["bir"] * 4,
                        b["block_id"], b["block_name"], b["block_offset"]))
    return lines, blocks


def dump_device(bdf, verbose=False, hexoff=None, hexlen=0x40):
    dev = PciDevice(bdf)
    out = []
    out.append("=" * 78)
    out.append("Device %s  vendor=0x%04x device=0x%04x class=0x%06x"
               % (bdf, dev.vendor or 0, dev.device or 0, dev.class_code or 0))
    out.append("=" * 78)

    if not dev.load_config():
        out.append("  [!] %s" % (dev.config_error or "cannot read config space"))
        out.append("  [!] run as root, or install pciutils (lspci)")
        return "\n".join(out), 1

    pcie_lines, blocks = dump_pcie_side(dev, verbose)
    out.extend(pcie_lines)

    for b in blocks:
        if b["block_id"] == 0x00:
            continue
        bar_start = dev.bar_start(b["bir"])
        if bar_start is None or bar_start == 0:
            out.append("")
            out.append("[skip] block %d: BAR%d not assigned"
                       % (b["index"], b["bir"]))
            continue

        out.append("")
        if b["block_id"] == 0x01:
            try:
                blk = ComponentBlock(dev, b["bir"], b["block_offset"], bar_start).open()
            except OSError as e:
                out.append("[skip] component block: %s" % e)
                continue
            try:
                out.extend(blk.dump(verbose))
                if hexoff is not None:
                    out.append("")
                    out.append("hexdump @ 0x%04x, %d bytes:" % (hexoff, hexlen))
                    out.extend(blk.hexdump(hexoff, hexlen))
            finally:
                blk.close()

        elif b["block_id"] == 0x03:
            try:
                blk = DeviceBlock(dev, b["bir"], b["block_offset"], bar_start).open()
            except OSError as e:
                out.append("[skip] device block: %s" % e)
                continue
            try:
                out.extend(blk.dump(verbose))
                if hexoff is not None:
                    out.append("")
                    out.append("hexdump @ 0x%04x, %d bytes:" % (hexoff, hexlen))
                    for row in range(0, hexlen, 16):
                        vals = []
                        for c in range(16):
                            v = blk.read32(hexoff + row + c)
                            vals.append("--------" if v is None else "%08x" % v)
                        out.append("  0x%04x  %s" % (hexoff + row, " ".join(vals)))
            finally:
                blk.close()

        elif b["block_id"] == 0x04:
            try:
                blk = CpmuBlock(dev, b["bir"], b["block_offset"], bar_start).open()
            except OSError as e:
                out.append("[skip] CPMU block: %s" % e)
                continue
            try:
                out.extend(blk.dump(verbose))
            finally:
                blk.close()
        elif b["block_id"] == 0x02:
            out.append("BAR Virtualization ACL (8.2.6) @ BAR%d + 0x%x  [not decoded]"
                       % (b["bir"], b["block_offset"]))
        else:
            out.append("")
            if b.get("vendor_specific"):
                out.extend(dump_vendor_block(dev, b, bar_start, verbose))
            else:
                out.append("Vendor Specific block id=0x%02x @ BAR%d + 0x%x"
                           % (b["block_id"], b["bir"], b["block_offset"]))

    out = annotate_vendor_aliases(out, dev, blocks)
    return "\n".join(out), 0


def annotate_vendor_aliases(out, dev, blocks):
    """Flag vendor blocks that resolve to the same physical window.

    Seen on real hardware: two 0xFF blocks at different BAR offsets returned
    byte-identical contents. Reporting this saves a reader from assuming they
    are independent register banks. Purely informational.
    """
    rz = [b for b in blocks if b.get("vendor_specific")]
    if len(rz) < 2:
        return out
    bar_start = dev.bar_start(rz[0]["bir"])
    if bar_start is None:
        return out
    try:
        mm = dev.mmap_bar(rz[0]["bir"], 0x1000000)
    except OSError:
        return out
    try:
        CMP_LEN = 0x4000
        wins = []
        for b in rz:
            vals = []
            for page in range(0, CMP_LEN, 4):
                off = b["block_offset"] + page
                try:
                    vals.append(struct.unpack_from("<I", mm, off)[0])
                except (struct.error, ValueError):
                    vals.append(None)
            wins.append(vals)

        notes = []
        for i in range(len(wins)):
            for j in range(i + 1, len(wins)):
                a, c = wins[i], wins[j]
                ndiff = sum(1 for x, y in zip(a, c) if x != y)
                ndwords = len(a)
                if ndiff == 0:
                    notes.append((rz[i]["block_offset"], rz[j]["block_offset"],
                                  0, None))
                elif ndiff * 100 <= ndwords:
                    first = next(k * 4 for k, (x, y) in enumerate(zip(a, c))
                                 if x != y)
                    notes.append((rz[i]["block_offset"], rz[j]["block_offset"],
                                  ndiff, first))
        if not notes:
            return out
        out.append("")
        out.append("NOTE: the following vendor block pairs read back essentially")
        out.append("      identical over %d KB, so they are very likely aliases"
                   % (CMP_LEN // 1024))
        out.append("      of one physical window rather than independent banks:")
        for off_a, off_c, ndiff, first in notes:
            if ndiff == 0:
                out.append("        BAR+0x%-8x == BAR+0x%-8x  (byte identical)"
                           % (off_a, off_c))
            else:
                out.append("        BAR+0x%-8x ~= BAR+0x%-8x  (%d dword differs,"
                           " first at +0x%x)"
                           % (off_a, off_c, ndiff, first))
        return out
    finally:
        try:
            mm.close()
        except Exception:
            pass


def enumerate_cxl():
    """List PCI devices that expose a CXL DVSEC (vendor 1E98)."""
    found = []
    if not os.path.isdir(SYSFS_PCI):
        return found
    for bdf in sorted(os.listdir(SYSFS_PCI)):
        dev = PciDevice(bdf)
        if not dev.load_config():
            # Without config access we can still guess from vendor id
            continue
        dvsecs = dev.find_cxl_dvsecs()
        if dvsecs:
            found.append((bdf, dev, dvsecs))
    return found


def main():
    ap = argparse.ArgumentParser(
        description="Dump CXL Component / Device registers (spec rev 3.1, sec 8.2)")
    ap.add_argument("-d", "--device", help="BDF, e.g. 0000:3b:00.0")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true", help="list CXL devices only")
    ap.add_argument("--hex", nargs="+", metavar="OFF",
                    help="hexdump block offset(s), e.g. --hex 0x1000 0xE000")
    ap.add_argument("--len", type=lambda s: int(s, 0), default=0x40,
                    help="bytes per hexdump (default 0x40)")
    args = ap.parse_args()

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sys.stderr.write(
            "warning: not running as root - config space and BAR mmap will "
            "likely fail\n\n")

    targets = []
    if args.device:
        targets = [args.device]
    else:
        found = enumerate_cxl()
        if not found:
            print("No CXL device found (no DVSEC with vendor 0x%04x)." % CXL_VENDOR_ID)
            print("Hints: run as root; check 'lspci -vv | grep -i cxl'.")
            return 1
        targets = [bdf for bdf, _, _ in found]

    if args.list:
        print("%-16s %-6s %-6s %-10s %s"
              % ("BDF", "Vendor", "Device", "Class", "CXL DVSECs"))
        for bdf in targets:
            dev = PciDevice(bdf)
            dev.load_config()
            dvs = dev.find_cxl_dvsecs() if dev.config else []
            ids = ",".join("0x%04x" % d["dvsec_id"] for d in dvs) or "-"
            print("%-16s 0x%04x 0x%04x 0x%06x   %s"
                  % (bdf, dev.vendor or 0, dev.device or 0,
                     dev.class_code or 0, ids))
        return 0

    rc = 0
    hexoffs = None
    if args.hex:
        hexoffs = [int(x, 0) for x in args.hex]

    for bdf in targets:
        if hexoffs:
            for ho in hexoffs:
                text, r = dump_device(bdf, args.verbose, ho, args.len)
                print(text)
                print()
                rc |= r
        else:
            text, r = dump_device(bdf, args.verbose)
            print(text)
            print()
            rc |= r
    return rc


if __name__ == "__main__":
    sys.exit(main())
