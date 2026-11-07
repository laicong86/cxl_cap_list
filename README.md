# cxl_cap_dump

Linux 用户态提取 CXL 设备寄存器信息的工具与规范梳理。

依据 *Compute Express Link Specification* **Rev 3.1, Ver 1.0**（2023-08-09）。

## 目录

```
docs/cxl-component-register-map.md   规范梳理（8.2 章节 + Table 8-21 逐段解读）
src/cxl_regs.h                       寄存器偏移/位域 C 定义，可独立 include
src/cxl_dump.py                      可运行的 Python 提取工具（无第三方依赖）
tests/test_cxl_dump.py               离线自测，用合成寄存器块验证解码逻辑
```

## 快速开始

```bash
# 列出机器上的 CXL 设备
python3 src/cxl_dump.py --list

# 完整 dump（需要 root：读 config space + mmap BAR）
sudo python3 src/cxl_dump.py

# 指定设备
sudo python3 src/cxl_dump.py -d 0000:3b:00.0

# 原始 hexdump 某个区间
sudo python3 src/cxl_dump.py -d 0000:3b:00.0 --hex 0x1000 0xE000 --len 0x40

# 跑自测（不需要 CXL 硬件）
python3 tests/test_cxl_dump.py
```

## 工具做了什么

完整实现了规范规定的两段式发现链：

1. 遍历 PCIe 扩展能力链，找出 DVSEC（Ext Cap ID `0023h`）中 Vendor ID = `1E98h` 的条目
2. 解析 **Register Locator DVSEC（ID `0008h`）** 得到 `BIR` + 64 KB 对齐偏移
3. mmap 对应 BAR，定位 64 KB **Component Register Block**
4. 按 **Table 8-21** 分段：`0x0000` CXL.io / `0x1000` Primary / `0x2000` 扩展池 / `0xE000` ARB-MUX
5. 在 Primary Range 按 **Table 8-23** 跟随 `CXL_Capability_Header` 指针数组，逐个解出
   RAS / Link / HDM Decoder / IDE / Security / Snoop Filter / Timeout-Isolation
6. 读 `000Ah` 能力的 16 位位图，把每个被置位的 4 KB 扩展区也走一遍同样的解析
7. 另解析 Register Locator 中 Block ID = `03h` 的 **CXL Device Register Block**：
   Device Status、Memory Device Status、Primary/Secondary Mailbox

输出示例：

```
=== CXL.cachemem Primary Range (offset 0x1000) ===
  CXL_Capability_Header: ID=0x0001 ver=1 cm_ver=1 array_size=4

  #   ID     Ptr    AbsOff    Ver  Name
  1   0x0002 0x100  0x001100   3    CXL RAS Capability
  2   0x0004 0x200  0x001200   4    CXL Link Capability
  3   0x0005 0x300  0x001300   3    CXL HDM Decoder Capability
  4   0x000a 0x400  0x001400   1    CXL.cachemem Extended Register Capability

  [CXL HDM Decoder Capability @ 0x1300]
    Decoder Count code    = 0x1 -> 2 decoders
      n   Base           Size         IG     IW   Cmt  Type   Notes
      0   0x000000000000 0x0          1KB    4    Y    HDM-D
      1   0x000040000000 0x40000000   256B   1    Y    HDM-D
```

## 三个必须注意的点

1. **截图那张表不是 PCIe 配置空间**，是 MMIO 的 64 KB Component Register Block，所有偏移相对块基址，不是 BAR 起始地址。

2. **Capability Pointer 就是字节偏移，不要左移 2 位**。`target = 0x1000 + pointer`，与 Linux 内核 `cxl_probe_component_regs()` 一致。唯一乘 4 的地方是数组步长。

3. **DVSEC 的 PCIe 扩展能力 ID 是 `0023h`，不是 `0003h`**。`0003h` 是 Device Serial Number。这个常量写错会导致能力链扫描一个都匹配不上，而全部协议层解析被静默跳过。

4. **访问宽度是硬性要求**（8.2.3）：32 位寄存器必须 4 字节读、64 位必须 8 字节读，部分读行为未定义。工具里用 `struct.unpack_from("<I"/"<Q")` 保证对齐访问。

## 已实现范围

- **Component Register Block**（8.2.3）：Table 8-21 五段区间、能力头与指针数组、扩展区位图
- **各能力结构**：RAS / Link / HDM Decoder / IDE / Security / Snoop Filter / Timeout-Isolation / ARB-MUX
- **CXL Device Register Block**（8.2.8）：Device Status、Memory Device Status、Primary/Secondary Mailbox
- **CPMU**（8.2.7）：21 个计数单元、事件组与 opcode 名、Filter 归属、64 位计数值
- **Vendor Specific 块**：无标准布局，只报告头部与可打印字符串，并检测互为别名的情况

## 未覆盖

- **CHBCR**（CXL Host Bridge 组件寄存器）：基址来自 ACPI CEDT，需解析 `/sys/firmware/acpi/tables/CEDT`，暂未实现
- **Mailbox 命令下发**：本工具只读，不发 doorbell、不写任何寄存器。要跑 Identify 等命令需在 `DeviceBlock` 上扩展写路径
- **CPMU 计数使能**：计数器默认 `En=0`，因此 Counter Data 全 0 属正常。要取实时值必须写 Counter Enable 并可能发 doorbell，与「纯只读」约束冲突，故未实现
- RCD / RCH 的 RCRB 路径（`MEMBAR0`）：代码预留了 BIR 逻辑但未专门处理 RCRB 场景

## 环境要求

- Linux（依赖 `/sys/bus/pci/devices/*/config` 与 `resource<N>`）
- root 或 `CAP_SYS_RAWIO`（读 config space、mmap BAR）
- Python 3.8+，无第三方包
- 可选 `pciutils`：无权限读 config 时用 `lspci -xxx` 兜底
