# CXL Component Register 配置空间梳理

> 依据：*Compute Express Link Specification* Rev 3.1, Ver 1.0（2023-08-09）
> 主要章节：**8.2 Memory Mapped Registers → 8.2.3 Component Register Layout and Definition**
> 截图对应：**Table 8-21. CXL Subsystem Component Register Ranges**

---

## 0. 先澄清一个容易混淆的概念

截图里的这张表**不是 PCIe 配置空间**（0x000–0xFFF 那 4 KB），而是 **MMIO 内存映射的 "Component Register Block"**，一个 **64 KB** 的地址窗口。

两套空间的关系是：

```
PCIe 配置空间 (每 Function 4KB, 通过 ECAM/CF8-CFC 访问)
  └─ 扩展能力链 (0x100 起)
       └─ DVSEC, DVSEC ID = 0008h  ← Register Locator DVSEC (8.1.9)
            └─ 只存 "BIR + 64KB 对齐偏移"
                 │
                 ▼ 解引用
MMIO: BARn_base + block_offset  →  Component Register Block (64 KB)
                                     └─ 内部再按 Table 8-21 划分：
                                        0x0000 / 0x1000 / 0x2000.. / 0xE000
```

所以写代码时分两步：**先读配置空间找到基址，再 mmap BAR 按偏移读寄存器**。

---

## 1. 截图表格原文与解读（Table 8-21）

| Range | Size | Description |
|---|---|---|
| `0000 0000h` – `0000 0FFFh` | 4 KB | Reserved for CXL.io registers. 本规范未定义任何 CXL.io 寄存器，因此整个区间视为保留。 |
| `0000 1000h` – `0000 1FFFh` | 4 KB | **CXL.cachemem Primary Range** |
| `0000 2000h` – `0000 DFFFh` | 48 KB | 实现相关。可容纳 0 个或多个 **CXL.cachemem Extended Range** 实例。 |
| `0000 E000h` – `0000 E3FFh` | 1 KB | **CXL ARB/MUX registers** |
| `0000 E400h` – `0000 FFFFh` | 7 KB | 保留。其中 `F000h–FFFFh` 可承载一个 CXL.cachemem Extended Range。 |

**关键点：所有偏移都是相对于 Component Register Block 的基址（即 MEMBAR0 指向的地址），不是 BAR 起始地址。**

逐段说明：

### 1.1 `0x0000–0x0FFF` — CXL.io 保留区

规范明说 *"This specification does not define any CXL.io registers, hence the entire range is considered reserved."*

也就是说：CXL.io 的寄存器并不在这里，而是复用 PCIe 自身的标准寄存器（配置空间、AER、DVSEC 等）。**这段纯属地址空间占位，不要读。**

### 1.2 `0x1000–0x1FFF` — CXL.cachemem Primary Range（最关键的一段）

CXL.cache 与 CXL.mem 的架构寄存器都在这里（8.2.4）。这 4 KB 内部用**指针数组**做自描述发现：

```
0x1000 + 0x00 : CXL_Capability_Header       (32-bit)
0x1000 + 0x04 : Capability Header [1]       (32-bit)
0x1000 + 0x08 : Capability Header [2]
        ...
0x1000 + n*4  : Capability Header [n]       n <= Array_Size
```

**CXL_Capability_Header（偏移 0x00，RO）**

| Bits | 字段 | 说明 |
|---|---|---|
| 15:0 | `CXL_Capability_ID` | 固定为 `0001h` |
| 19:16 | `CXL_Capability_Version` | 本版规范为 `1h` |
| 23:20 | `CXL_Cache_Mem_Version` | 本版规范为 `1h` |
| 31:24 | `Array_Size` | 后续能力头个数（**不含**本头，每项 1 DWORD） |

**每个 Capability Header 元素（32-bit，RO）**

| Bits | 字段 | 说明 |
|---|---|---|
| 15:0 | `CXL_Capability_ID` | 见下方 ID 表 |
| 19:16 | `CXL_Capability_Version` | 结构版本 |
| 31:20 | `xxx_Capability_Pointer` | **相对 `CXL_Capability_Header` 起始（即 0x1000）的字节偏移，直接相加，不移位** |

> ⚠️ **最容易写错的地方**：Pointer 字段就是字节偏移，`target = 0x1000 + pointer`。Linux 内核 `cxl_probe_component_regs()` 里也是直接 `base + offset`，没有 `<< 2`。唯一的乘 4 是数组步长 `cap * 4`。

**CXL_Capability_ID 分配（Table 8-22，本版已定义部分）**

| ID | 能力结构 | 说明 |
|---|---|---|
| `0000h` | CXL NULL Capability | 跳过，继续下一项 |
| `0001h` | CXL Capability Header | 数组头自身 |
| `0002h` | CXL RAS Capability | 8.2.4.17 |
| `0003h` | CXL Security Capability | 8.2.4.18，仅 RCH Downstream Port |
| `0004h` | CXL Link Capability | 8.2.4.19 |
| `0005h` | CXL HDM Decoder Capability | 8.2.4.20 |
| `0006h` | CXL Extended Security Capability | 8.2.4.21，仅 CHBCR |
| `0007h` | CXL IDE Capability | 8.2.4.22 |
| `0008h` | CXL Snoop Filter Capability | 8.2.4.23 |
| `0009h` | CXL Timeout and Isolation Capability | 8.2.4.24 |
| `000Ah` | **CXL.cachemem Extended Register Capability** | 8.2.4.25，**仅 Primary Range** |
| `000Bh` | CXL BI Route Table Capability | 8.2.4.26 |
| `000Ch` | CXL BI Decoder Capability | 8.2.4.27 |
| `000Dh` | CXL Cache ID Route Table Capability | 8.2.4.28 |
| `000Eh` | CXL Cache ID Decoder Capability | 8.2.4.29 |
| `000Fh` | CXL Extended HDM Decoder Capability | 8.2.4.30 |
| `0010h` | CXL Extended Metadata Capability | 8.2.4.31 |

**重要约束（8.2.4 原文）**：ID `0001h`–`000Ah` 的结构**不允许**出现在 Extended Range 中；`000Ah` 本身用来标识 Extended Range。ID `0000h` 与 `>000Ah` 的结构可以出现在任何 4 KB 区。

### 1.3 `0x2000–0xDFFF` — 实现相关的 Extended Range 池（48 KB）

这里**没有固定布局**，可能一个扩展区都没有。要发现它们，必须去读 Primary Range 里的 `000Ah` 能力（8.2.4.25）：

**CXL.cachemem Extended Ranges Register（偏移 `0x2000 + pointer + 0x00`，RO，16-bit 位图）**

| Bit | 对应 4 KB 区间 |
|---|---|
| 0, 1, 14 | Reserved |
| 2 | `2000h–2FFFh` |
| 3 | `3000h–3FFFh` |
| 4 | `4000h–4FFFh` |
| 5 | `5000h–5FFFh` |
| 6 | `6000h–6FFFh` |
| 7 | `7000h–7FFFh` |
| 8 | `8000h–8FFFh` |
| 9 | `9000h–9FFFh` |
| 10 | `A000h–AFFFh` |
| 11 | `B000h–BFFFh` |
| 12 | `C000h–CFFFh` |
| 13 | `D000h–DFFFh` |
| 15 | `F000h–FFFFh` |

即：**bit n → 区间 `(n * 0x1000) – (n * 0x1000 + 0xFFF)`**，bit ∈ [2,13] ∪ {15}。

每个被置位的 4 KB 区间，其布局与 Primary Range **完全一致**（同样以 `CXL_Capability_Header` 开头，ID 必须是 `0001h`，`Array_Size` 同样有效）。

### 1.4 `0xE000–0xE3FF` — CXL ARB/MUX 寄存器（1 KB）

8.2.5 独立定义，内部偏移从 ARB/MUX 区自身算起（即绝对 `0xE000 + reg_offset`）：

| 偏移 | 寄存器 |
|---|---|
| `00h` | ARB/MUX PM Timeout Control |
| `04h` | ARB/MUX Uncorrectable Error Status |
| `08h` | ARB/MUX Uncorrectable Error Mask |
| `180h` | ARB/MUX Arbitration Control for CXL.io |
| `1C0h` | ARB/MUX Arbitration Control for CXL.cache and CXL.mem |

### 1.5 `0xE400–0xFFFF` — 保留（7 KB）

除 `F000h–FFFFh` 可能作为 Extended Range（见 1.3 bit15）外，其余无定义。

> 注：`0000E400h` 到 `0000FFFFh` 正好 0x1C00 = 7 KB，表格的 Size 列是准确的。

---

## 2. 基址怎么来？三条路径（8.2.2 / 8.1.9）

Table 8-21 只说了"相对基址的偏移"，基址来源分三种情况：

### 2.1 普通 CXL 设备 / Root Port / Switch Port → Register Locator DVSEC

8.1.9 规定 root port、DSP、USP、非 RCD 设备**必须**实现 Register Locator DVSEC。

**DVSEC 头（PCIe 扩展能力，Ext Cap ID = `0023h`）**

| 位置 | 字段 | 值 |
|---|---|---|
| `+00h` | PCIe Extended Capability Header | ext_cap_id=`0023h`（DVSEC） |
| `+04h` | DVSEC Vendor ID | `1E98h`（CXL） |
| `+04h[19:16]` | DVSEC Revision | `0h` |
| `+04h[31:20]` | DVSEC Length | `0Ch + n*8` |
| `+08h[15:0]` | **DVSEC ID** | **`0008h`** = Register Locator |

> **易错点**：PCIe 扩展能力里 DVSEC 的 ID 是 **`0023h`**（Designated Vendor-Specific）。`0003h` 是 Device Serial Number，`0001h` 是 AER，都不是 DVSEC。按 `0003h` 去匹配会一个 DVSEC 都找不到。

**Register Block 条目（从 `+0Ch` 开始，每条 8 字节）**

`Register Offset Low`（32-bit）：

| Bits | 字段 | 说明 |
|---|---|---|
| 2:0 | `Register BIR` | BAR 编号：`0`→BAR10h, `1`→BAR14h … `5`→BAR24h。64-bit BAR 取低 DWORD |
| 7:3 | Reserved | |
| 15:8 | `Register Block Identifier` | `00h`=空条目, **`01h`=Component Registers**, `02h`=BAR Virtualization ACL, `03h`=CXL Device Registers, `04h`=CPMU, `FFh`=Vendor Specific |
| 31:16 | `Register Block Offset Low` | BAR 偏移 `A[31:16]`，**64 KB 对齐**（故 `A[15:0]=0000h`） |

`Register Offset High`（32-bit）= 偏移的 `A[63:32]`，空条目时为 0。

于是：

```
component_base = BAR[BIR].start + ((offset_low >> 16) | (offset_high << 16))
```

### 2.2 RCD / RCH → RCRB 里的 MEMBAR0

- RCD Upstream Port 实现 RCRB 时：基址 = RCRB 偏移 `10h/14h` 处的 64-bit `MEMBAR0`
- RCH Downstream Port：同理，用 Downstream Port RCRB 的 `MEMBAR0`

RCRB 本身是 4 KB 区域，`MEMBAR0` 指向 Component Register Block（Table 8-17）。

### 2.3 CXL Host Bridge → ACPI CEDT 的 CHBCR

CXL Host Bridge 的组件寄存器叫 **CHBCR**，基址从 **ACPI CEDT（Section 9.18.1.2）** 里取。ACPI HID = `ACPI0016`。

> 用户态下 CHBCR 的枚举最麻烦，通常从 `/sys/firmware/acpi/tables/CEDT` 解析。本工具先覆盖 2.1/2.2，CHBCR 留 TODO。

---

## 3. 访问宽度规则（8.2.3，硬性要求）

> "Software shall use CXL.io Memory Reads and Writes to access CXL Component registers"

- **32-bit 寄存器必须用 4 字节访问**，禁止部分读
- **64-bit 寄存器必须用 8 字节访问**，禁止部分读
- 访问必须映射到连续字节

违反则行为未定义。这比 8.2 对普通 MMIO 寄存器的通用要求更严格。

> 实践含义：在用户态 mmap 后用 `volatile uint32_t*` / `uint64_t*` 对齐访问，不要用 `memcpy` 拼接，也不要用 `read()` 分段读。

---

## 4. Linux 用户态落地路径

| 需求 | 途径 | 权限 |
|---|---|---|
| 枚举 CXL 设备 | `/sys/bus/pci/devices/*/`，按 DVSEC `0008h` 过滤 | 普通用户可读 |
| 读 PCIe 配置空间 | `/sys/bus/pci/devices/<BDF>/config`（4096 B，含扩展能力链） | **root** |
| 获取 BAR 物理基址 | `/sys/bus/pci/devices/<BDF>/resource`（文本：`idx start end flags`） | 普通用户可读 |
| mmap 寄存器 | `open("/sys/bus/pci/devices/<BDF>/resource<N>")` + `mmap` | **root**（或 `CAP_SYS_RAWIO`） |
| 备选 | `/dev/mem` + 物理地址 | **root** + `CONFIG_STRICT_DEVMEM` 需关闭，不推荐 |

**注意事项：**

1. `resource<N>` 文件大小 = `end - start + 1`，可直接整体 mmap，用 `block_offset + 内部偏移` 索引。
2. 若 BAR 是 64-bit，`resource` 文件里低 DWORD 那一行给出的是合并后的完整地址，直接用即可。
3. 务必先确认设备处于 CXL 模式（DVSEC `0007h` Flex Bus Port 的 `Mem_Enabled`/`Cache_Enabled`），否则寄存器可能是死的。
4. 读 RAS/HDM 等寄存器是纯读取，但 **HDM Decoder Control / Commit、Mailbox doorbell 是写敏感的**，只读工具不要碰。
5. 别对同一 BAR 同时跑 `cxl` 内核驱动和用户态 mmap 做写操作，会打架。

---

## 5. 常用偏移速查（Component Register Block 内）

```
0x0000  保留 (CXL.io)                         4 KB
0x1000  CXL.cachemem Primary Range            4 KB
0x2000  Extended Range 池 (实现相关)          48 KB   → 0xDFFF
0xE000  CXL ARB/MUX                           1 KB
0xE400  保留                                  7 KB    → 0xFFFF

Primary Range (0x1000) 内:
  +0x00  CXL_Capability_Header
  +0x04  Capability Header[1] ...
  +ptr   RAS Capability            (ID 0002h, 固定长 0x58)
  +ptr   Link Capability           (ID 0004h)
  +ptr   HDM Decoder Capability    (ID 0005h, 长 = 0x20*count + 0x10)
  +ptr   Extended Ranges Register  (ID 000Ah, 16-bit 位图)
```

**HDM Decoder Capability 内部布局（ID 0005h，8.2.4.20）**

| 偏移 | 寄存器 |
|---|---|
| `00h` | HDM Decoder Capability（`Decoder Count[3:0]`，编码见下） |
| `04h` | HDM Decoder Global Control |
| `08h/0Ch` | Reserved |
| `20h*n + 10h` | Decoder n Base Low（`Memory Base Low[31:28]`） |
| `20h*n + 14h` | Decoder n Base High（`Memory Base High[31:0]`） |
| `20h*n + 18h` | Decoder n Size Low（`Memory Size Low[31:28]`） |
| `20h*n + 1Ch` | Decoder n Size High（`Memory Size High[31:0]`） |
| `20h*n + 20h` | Decoder n Control |
| `20h*n + 24h` | Decoder n Target List Low / DPA Skip Low |
| `20h*n + 28h` | Decoder n Target List High / DPA Skip High |

`Decoder Count` 编码 → 实际个数：`0→1, 1→2, 2→4, 3→6, 4→8, 5→10, 6→12, 7→14, 8→16, 9→20, Ah→24, Bh→28, Ch→32`。

`Decoder Control`（`20h*n+20h`）：

| Bits | 字段 |
|---|---|
| 3:0 | Interleave Granularity（`0`=256B, `1`=512B … `6`=16KB） |
| 7:4 | Interleave Ways（`0`=1way, `1`=2way, `2`=4way, `3`=8way, `4`=16way, `8`=3way, `9`=6way, `A`=12way） |
| 8 | Lock On Commit |
| 9 | Commit |
| 10 | Committed（RO，1=该 decoder 生效） |
| 11 | Error Not Committed |
| 12 | Target Range Type（`0`=HDM-D/DB, `1`=HDM-H） |
| 13 | BI |

---

## 6. CXL Device Register Block（ID `03h`，8.2.8）

这是**另一块** 64 KB 对齐的寄存器块，不在 Table 8-21 的 64 KB 窗口内，而是由 Register Locator 的另一条目（Block ID = `03h`）指向。CXL Type 3 设备的 **mailbox / 内存设备状态** 都在这里。

```
+00h  CXL Device Capabilities Array Register (128-bit)
+10h  Device Capability 1 Header (128-bit)
+20h  Device Capability 2 Header
+n*10h ...
```

**Capabilities Array Register**

| Bits | 字段 |
|---|---|
| 15:0 | Capability ID = `0000h` |
| 23:16 | Version = `01h` |
| 27:24 | Type（`0`=按 Class Code 推断, `1`=Memory Device, `2`=Switch Mailbox CCI） |
| 47:32 | Capabilities Count（后续头个数） |

**Device Capability Header**（每项 16 字节）

| Bits | 字段 |
|---|---|
| 15:0 | Capability ID |
| 23:16 | Version |
| 63:32 | **Offset**（相对 Device Register Block 起点的字节偏移） |
| 95:64 | Length（结构字节数） |

**Capability ID**

| ID | 结构 | 必需性 |
|---|---|---|
| `0001h` | Device Status Registers | M |
| `0002h` | Primary Mailbox Registers | M |
| `0003h` | Secondary Mailbox Registers | O |
| `4000h` | Memory Device Status Registers（类型相关） | M（内存设备） |

**Device Status（+00h）= Event Status**：bit0 Informational / bit1 Warning / bit2 Failure / bit3 Fatal / bit4 Dynamic Capacity。

**Mailbox 布局（相对 mailbox capability offset）**

| 偏移 | 寄存器 |
|---|---|
| `00h` | Mailbox Capabilities（`Payload Size[4:0]` = 2^n 字节） |
| `04h` | Mailbox Control（bit0 Doorbell） |
| `08h` | Command（`Opcode[15:0]`, `Payload Length[36:16]`） |
| `10h` | Mailbox Status（`Return Code[47:32]`, `Vendor Ext[63:48]`） |
| `18h` | Background Command Status |
| `20h` | Command Payload Registers |

**常用 opcode**：`0001h` Identify、`0002h` Background Operation Status、`0100h` Get Event Records、`0101h` Clear Event Records、`4001h` Identify Memory Device。

**Memory Device Status（4000h cap + 00h）**：bit0 Device Fatal、bit1 FW Halt、`Media Status[3:2]`、bit4 Mailbox Interfaces Ready、`Reset Needed[7:5]`。

---

## 7. CPMU 寄存器块（ID `04h`，8.2.7）

Register Locator DVSEC 中 **Register Block Identifier = `04h`** 指向 CPMU。布局见 **Table 8-32（Version=1）**。

### 7.1 块内布局

| 偏移 | 长度 | 内容 |
|---|---|---|
| `00h` | 8 | **CPMU Capability** |
| `08h` | 8 | Reserved |
| `10h` | 8 | **CPMU Overflow Status** |
| `18h` | 8 | **CPMU Freeze**（仅 Freeze Support=1 时实现） |
| `20h` | 224 | Reserved |
| `100h` | 8×32 | **CPMU Event Capabilities[0..31]** |
| `200h` | 8×64 | Counter Unit n 的 **Counter Configuration** |
| `400h` | 4×8×64 | Counter Unit n 的 **Filter ID m 配置**（`400h + n*20h + m*4`） |
| `C00h` | 8×64 | Counter Unit n 的 **Counter Data**（**必须 8 字节访问**） |

### 7.2 CPMU Capability（`00h`）

| Bits | 字段 | 说明 |
|---|---|---|
| `5:0` | Number of Counter Units | **0-based**，`00h`=1 个，`14h`=21 个 |
| `15:8` | Counter Width | 计数器位宽 n，最大值 `2^n - 1` |
| `24:20` | Number of Event Capability Regs | 也是 **0-based** |
| `39:32` | Filters Supported | 位图，bit n = Filter ID n 支持 |
| `47:44` | Interrupt Message Number | MSI/MSI-X 向量 |
| `48` | Counters Writable while Frozen | |
| `49` | Counter Freeze Support | 0 则 Freeze 寄存器与 Global Freeze 位均保留 |
| `50` | Interrupt on Overflow Support | |
| `63:60` | Version | 固定 `1` |

> **两个 0-based 字段最容易搞错**：Number of Counter Units 和 Number of Event Capability Regs 都是 0-based。读到 `14h` 要按 21 个算，不是 20 个。

### 7.3 Counter Configuration（`200h + n*8`）

| Bits | 字段 |
|---|---|
| `1:0` | Counter Type：`00b` free-running / `01b` fixed-function / `10b` configurable |
| `8` | Counter Enable |
| `9` | Interrupt on Overflow |
| `10` | Global Freeze on Overflow |
| `11` | Edge（0→1 跳变计数） |
| `12` | Invert（配合 Threshold） |
| `23:16` | Threshold（reset 默认 `01h`） |
| `55:24` | Events 位图（对应 Event Group 内的 Event ID） |
| `63:59` | **Event Group ID Index**，指向第几个 Event Capabilities 寄存器 |

free-running 与 fixed-function 类型下，`8`/`9`/`10`/`11`/`12`/`23:16`/`55:24`/`63:59` 大部分是 RO。

### 7.4 Event Capabilities（`100h + n*8`）

| Bits | 字段 |
|---|---|
| `31:0` | Supported Events 位图 |
| `47:32` | Event Group ID |
| `63:48` | Event Vendor ID（CXL 为 `1E98h`） |

### 7.5 Filter 归属（依据 Table 13-5，极易弄反）

| Event Group | Filter ID |
|---|---|
| `20h`–`25h`（全部 CXL.mem 通道） | **Filter ID = 0**（HDM decoder 掩码，bit n → HDM Decoder n） |
| `8000h`（DDR Interface） | **Filter ID = 1**（Bank/BankGroup/Rank/Channel） |
| 其余组 | 无过滤器 |

Filter 寄存器 reset 默认 **`FFFFFFFFh` = 不做过滤**。Filter ID=1 的编码：`[7:0]` Bank、`[15:8]` BankGroup、`[23:16]` Rank、`[31:24]` Channel，置 `FFh` 表示该维度不限。

### 7.6 事件组（Table 13-5）

| Group | 含义 | 可用 Event |
|---|---|---|
| `00h` | Base | `00h` Clock Ticks |
| `10h`–`13h` | D2H/H2D Req/Rsp 通道 | Event ID 即 opcode 编码（见 Table 3-22/3-25/3-26/3-27） |
| `14h` | CXL.cache Data | `00h` D2H Data、`01h` H2D Data |
| `20h` | M2S Req | MemInv/MemRd/MemRdData/MemRdFwd/MemWrFwd/MemSpecRd/MemInvNT… |
| `21h` | M2S RwD | MemWr/MemWrPtl/MemRdFill… |
| `22h` | M2S BIRsp | BIRspI/S/E 及 Blk 变体 |
| `23h` | S2M BISnp | |
| `24h` | S2M NDR | Cmp/Cmp-S/Cmp-E/Cmp-M/BI-ConflictAck/CmpTEE |
| `25h` | S2M DRS | MemData/MemData-NXM/MemDataTEE |
| `8000h` | **DDR Interface** | ACT/PRE/CAS Rd/CAS Wr/Refresh/Self Refresh Entry/RFM |

### 7.7 读计数值前必读

计数器默认 **Counter Enable = 0**。此时 `Counter Data` 全为 0 是**正常设计**，不是故障。要看到非零值必须先写 Counter Enable —— 而本工具是**纯只读**的，不会写任何寄存器，所以它展示的是「计数器配置与能力」，不是「实时性能数据」。

---

## 8. Vendor Specific 寄存器块（ID `FFh`）

8.1.9.1 只规定块标识符与块内容**均由厂商定义**，规范**没有给出任何布局**。因此这类块只能报告可验证的事实（窗口地址、头部是否与 PCI Vendor ID 一致、ASCII 签名串），不应臆测字段语义。

实测 `a8:00.0`（Microchip `1b00:c002`）有两个 `FFh` 块（`BAR0+0x30000`、`BAR0+0x200000`），头部 `+0000` 均为 `00001b00`（与 PCI Vendor ID 一致），`+0x24` 处有 ASCII 串，两块内容在 16 KB 范围内仅差 1 个 dword —— **很可能是同一物理窗口的别名，而非两个独立寄存器组**。

---

## 9. 如何判定「真的是 CXL 设备」（`--list` 的准确性问题）

**只看到 vendor `1E98h` 的 DVSEC 就认定是 CXL 设备，会误判。**

实测环境里 8 个 Intel 根端口（`8086:0db0`~`0db3`，class `060400`）都带有 DVSEC `0003h/0004h/0007h/0008h`，按「有 CXL DVSEC 就是 CXL 设备」的判据会把它们全部列出来，而实际上只有 `a7:02.0`（`a8:00.0` 的上游端口）真正工作在 CXL 模式。

这是规范允许的：8.1.9 明确要求 **CXL 根端口必须实现 Register Locator DVSEC**，所以空置的根端口天然带这些 DVSEC，与链路是否协商成 CXL 无关。Linux 内核在 `include/uapi/linux/pci_regs.h` 里也特别注明：

> Note that CXL DVSEC id 3 and 7 to be ignored when the CXL link state is "disconnected" (CXL r4.0, sec 9.12.3).

### 判据（按优先级）

| 顺序 | 条件 | 依据 | 结论 |
|---|---|---|---|
| 1 | 存在 DVSEC `0000h` | Table 8-2：`0000h` 对 D1/D2/LD/FMLD **Mandatory**，对 P/UP1/DP1/R/USP/DSP **Not Permitted** | **是** CXL 设备 |
| 2 | `Flex Bus Port Status[2:0] != 0` | 8.2.1.3.3（DVSEC `0007h` + `0Eh`），这三个位由物理层在 alternate protocol 协商**选定 CXL 之后**才置位 | **是**，且链路已协商 |
| 3 | Component Block `+1000h` 的 header ID = `0001h` | Table 8-23，有效 CXL.cachemem range 的 ID 固定为 `0001h` | **是**，寄存器块真实存在 |
| — | 以上都不满足 | — | **否**，只是挂了 CXL DVSEC 的 PCIe function |

`Flex Bus Port Status` 低位含义：

| bit | 字段 |
|---|---|
| 0 | `Cache_Enabled` |
| 1 | `IO_Enabled` |
| 2 | `Mem_Enabled` |
| 3 | `CXL_Sync_Hdr_Bypass_Enabled` |
| 4 | `Drift_Buffer_Enabled` |
| 5 | `CXL 68B Flit and VH Enabled` |

实测对照：

| 设备 | Flex Bus Status | Component header | 判定 |
|---|---|---|---|
| `a7:02.0` | `0x0126` → io+mem+68B | `0x0001` | 是（已协商） |
| `a8:00.0` | — | `0x0001` | 是（有 `0000h`） |
| 其余 7 个根端口 | `0x0000` | `0x0000` | 否（从未协商，且块未实现） |

注意判据 3 需要 mmap，在无权限或 BAR 未分配时会失败。这种情况按「不构成 CXL 证据」处理，不能当成错误抛出，否则枚举会中断。

---

## 10. 配套代码

`src/cxl_regs.h` — 上面所有偏移/位域的 C 常量，可直接 include。
`src/cxl_dump.py` — 可运行的用户态提取工具，无第三方依赖。

```bash
sudo python3 src/cxl_dump.py            # 枚举真正的 CXL 设备
sudo python3 src/cxl_dump.py --list     # 同上，并列出被排除的误报设备
sudo python3 src/cxl_dump.py -d 0000:3b:00.0 -v
sudo python3 src/cxl_dump.py -d 0000:3b:00.0 --hex 0x1000
```

---

## 11. 参考章节索引

| 内容 | 章节 |
|---|---|
| 组件寄存器区间表（截图） | 8.2.3, Table 8-21 |
| 基址获取（RCRB/MEMBAR0/BAR/DVSEC/CEDT） | 8.2.2 |
| 访问宽度规则 | 8.2.3 |
| cachemem 寄存器发现机制 | 8.2.4 |
| Capability Header / Pointer 位域 | 8.2.4.1, Table 8-23 |
| Capability ID 分配 | 8.2.4, Table 8-22 |
| RAS | 8.2.4.17 |
| Link | 8.2.4.19 |
| HDM Decoder | 8.2.4.20 |
| Extended Ranges 位图 | 8.2.4.25.1 |
| ARB/MUX | 8.2.5 |
| CPMU | 8.2.7 |
| Device Register / Mailbox | 8.2.8 |
| 命令集与 opcode | 8.2.9 |
| Register Locator DVSEC | 8.1.9 |
| PCIe DVSEC for CXL Devices（HDM Range 老路径） | 8.1.3 |
| RCH/RCD RCRB | 8.2.1.1 / 8.2.1.2 |
| CHBCR / CEDT | 8.2.2, 9.18.1.2 |
| CPMU 寄存器接口 | 8.2.7, Table 8-32 |
| CPMU 事件定义 | Table 13-5 |
| CPMU 过滤器编码 | 8.2.7.2.2, Table 8-33 |
| DVSEC ID 分配 | Table 8-2 |
