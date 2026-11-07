/*
 * cxl_regs.h - CXL Component / Device register definitions for userspace
 *
 * Source: Compute Express Link Specification Rev 3.1, Ver 1.0 (2023-08-09)
 *
 *   Table 8-21  CXL Subsystem Component Register Ranges        (8.2.3)
 *   Table 8-22  CXL_Capability_ID Assignment                   (8.2.4)
 *   Table 8-23  CXL.cache and CXL.mem Register Discovery       (8.2.4.1)
 *   Section 8.1.9  Register Locator DVSEC
 *   Section 8.2.5  CXL ARB/MUX
 *   Section 8.2.7  CPMU
 *   Section 8.2.8  CXL Device Register Interface
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */
#ifndef CXL_REGS_H
#define CXL_REGS_H

#include <stdint.h>

/* ==========================================================================
 * 1. PCIe configuration space - DVSEC discovery
 * ========================================================================== */

/* PCIe extended capability ID for Designated Vendor-Specific (DVSEC) = 0023h.
 * Careful: 0003h is Device Serial Number, not DVSEC. */
#define PCI_EXT_CAP_ID_DVSEC        0x0023
#define PCI_EXT_CAP_ID_DSN          0x0003
#define CXL_DVSEC_VENDOR_ID         0x1E98

/* CXL DVSEC IDs (Table 8-2) */
#define CXL_DVSEC_DEVICE            0x0000  /* PCIe DVSEC for CXL Devices,  8.1.3  */
#define CXL_DVSEC_NON_CXL_FUNC_MAP  0x0002
#define CXL_DVSEC_PORT_EXT          0x0003  /* CXL Extensions for Ports,    8.1.5  */
#define CXL_DVSEC_GPF_PORT          0x0004
#define CXL_DVSEC_GPF_DEVICE        0x0005
#define CXL_DVSEC_FLEX_BUS_PORT     0x0007  /* 8.1.8 */
#define CXL_DVSEC_REGISTER_LOCATOR  0x0008  /* 8.1.9  */
#define CXL_DVSEC_MLD               0x0009
#define CXL_DVSEC_TEST_CAPABILITY   0x000A  /* PCIe DVSEC for Test Capability, 14.16.1 */

/* --- Register Locator DVSEC (8.1.9) -------------------------------------- */

/*
 * Structure:
 *   +00h  PCIe Extended Capability Header
 *   +04h  DVSEC Header 1 : VendorID[15:0] Rev[19:16] Length[31:20]
 *   +08h  DVSEC Header 2 : DVSEC ID[15:0] == 0008h
 *   +0Ch  Register Block 1 - Register Offset Low
 *   +10h  Register Block 1 - Register Offset High
 *   +14h  Register Block 2 - Register Offset Low   ... (8 bytes per entry)
 */
#define CXL_REGLOC_HDR_LEN          0x0C    /* offset of first register block */
#define CXL_REGLOC_BLOCK_STRIDE     0x08

/* Register Offset Low */
#define CXL_REGLOC_BIR_MASK         ((uint32_t)0x7)
#define CXL_REGLOC_BLOCK_ID_MASK    ((uint32_t)0xFF)
#define CXL_REGLOC_BLOCK_ID_SHIFT   8
#define CXL_REGLOC_OFFSET_LOW_MASK  ((uint32_t)0xFFFF)
#define CXL_REGLOC_OFFSET_LOW_SHIFT 16

/* Register Block Identifier values */
#define CXL_REGLOC_BLOCK_EMPTY      0x00
#define CXL_REGLOC_BLOCK_COMPONENT  0x01    /* -> Section 8.2.3 / Table 8-21 */
#define CXL_REGLOC_BLOCK_BAR_ACL    0x02
#define CXL_REGLOC_BLOCK_DEVICE     0x03    /* -> Section 8.2.8 */
#define CXL_REGLOC_BLOCK_CPMU       0x04    /* -> Section 8.2.7 */
#define CXL_REGLOC_BLOCK_VENDOR     0xFF

/*
 * Register Block Offset is 64 KB aligned: A[15:0] are 0000h, so the low
 * register only carries A[31:16].
 *   base = BAR[BIR] + (offset_low[31:16] | offset_high << 16)
 */
#define CXL_COMPONENT_REG_BLOCK_ALIGN   0x10000ULL
#define CXL_COMPONENT_REG_BLOCK_SIZE    0x10000ULL  /* 64 KB */

/* --- PCIe DVSEC for CXL Devices (8.1.3) - the pre-HDM-Decoder path -------- */
#define CXL_DVSEC_CAP_OFFSET        0x0A
#define CXL_DVSEC_CAP_CACHE         (1u << 0)
#define CXL_DVSEC_CAP_IO            (1u << 1)
#define CXL_DVSEC_CAP_MEM           (1u << 2)
#define CXL_DVSEC_CAP_MEM_HW_INIT   (1u << 3)
#define CXL_DVSEC_CAP_HDM_COUNT_MASK ((uint32_t)0x3)
#define CXL_DVSEC_CAP_HDM_COUNT_SHIFT 4
#define CXL_DVSEC_CAP_RESET_CAPABLE (1u << 7)

#define CXL_DVSEC_CTRL_OFFSET       0x0C
#define CXL_DVSEC_CTRL_MEM_ENABLE   (1u << 2)

/* Range 1 registers (8.1.3.8) */
#define CXL_DVSEC_RANGE1_SIZE_HI    0x18
#define CXL_DVSEC_RANGE1_SIZE_LO    0x1C
#define CXL_DVSEC_RANGE1_BASE_HI    0x20
#define CXL_DVSEC_RANGE1_BASE_LO    0x24
#define CXL_DVSEC_SIZE_LO_INFO_VALID    (1u << 0)
#define CXL_DVSEC_SIZE_LO_MEM_ACTIVE    (1u << 1)
#define CXL_DVSEC_SIZE_LO_MEDIA_TYPE_MASK  ((uint32_t)0x7)
#define CXL_DVSEC_SIZE_LO_MEDIA_TYPE_SHIFT 2
#define CXL_DVSEC_SIZE_LO_CLASS_MASK    ((uint32_t)0x7)
#define CXL_DVSEC_SIZE_LO_CLASS_SHIFT   5
#define CXL_DVSEC_SIZE_LO_IG_MASK       ((uint32_t)0x1F)
#define CXL_DVSEC_SIZE_LO_IG_SHIFT      8

/* --- PCIe DVSEC for Flex Bus Port (8.1.8) -------------------------------- */
#define CXL_FLEXBUS_CAP_OFFSET      0x0A
#define CXL_FLEXBUS_CAP_CACHE       (1u << 0)
#define CXL_FLEXBUS_CAP_IO          (1u << 1)
#define CXL_FLEXBUS_CAP_MEM         (1u << 2)
#define CXL_FLEXBUS_CAP_68B_VH      (1u << 5)
#define CXL_FLEXBUS_CAP_MLD         (1u << 6)
#define CXL_FLEXBUS_CAP_256B_FLIT   (1u << 13)

#define CXL_FLEXBUS_CTRL_OFFSET     0x0C
#define CXL_FLEXBUS_CTRL_CACHE_EN   (1u << 0)
#define CXL_FLEXBUS_CTRL_MEM_EN     (1u << 2)

/* ==========================================================================
 * 2. Component Register Block layout - Table 8-21
 * ========================================================================== */

#define CXL_COMP_OFF_CXLIO          0x0000ULL  /* 4 KB, reserved             */
#define CXL_COMP_OFF_CM_PRIMARY     0x1000ULL  /* 4 KB, CXL.cachemem primary */
#define CXL_COMP_OFF_EXT_POOL       0x2000ULL  /* 48 KB, extended range pool */
#define CXL_COMP_OFF_ARBMUX         0xE000ULL  /* 1 KB, CXL ARB/MUX          */
#define CXL_COMP_OFF_RESERVED       0xE400ULL  /* 7 KB, reserved             */

#define CXL_COMP_SIZE_CXLIO         0x1000ULL
#define CXL_COMP_SIZE_CM_PRIMARY    0x1000ULL
#define CXL_COMP_SIZE_EXT_POOL      0xC000ULL
#define CXL_COMP_SIZE_ARBMUX        0x0400ULL
#define CXL_COMP_SIZE_RESERVED      0x1C00ULL

/* --------------------------------------------------------------------------
 * 2.1 CXL.cache / CXL.mem capability discovery - 8.2.4.1 / Table 8-23
 *
 *   +00h : CXL_Capability_Header            (ID must be 0001h)
 *   +04h : Capability Header [1]            \
 *   +08h : Capability Header [2]             > Array_Size entries, 1 DWORD each
 *   ...                                      /
 * -------------------------------------------------------------------------- */

#define CXL_CM_CAP_HDR_OFFSET       0x00
#define CXL_CM_CAP_HDR_ID_MASK      ((uint32_t)0xFFFF)
#define CXL_CM_CAP_HDR_VERSION_MASK ((uint32_t)0xF)
#define CXL_CM_CAP_HDR_VERSION_SHIFT     16
#define CXL_CM_CAP_HDR_CM_VER_MASK  ((uint32_t)0xF)
#define CXL_CM_CAP_HDR_CM_VER_SHIFT      20
#define CXL_CM_CAP_HDR_ARRAY_SIZE_MASK ((uint32_t)0xFF)
#define CXL_CM_CAP_HDR_ARRAY_SIZE_SHIFT  24

#define CXL_CM_CAP_HDR_CAP_ID       0x0001

/* Each capability header element */
#define CXL_CM_CAP_ID_MASK          ((uint32_t)0xFFFF)
#define CXL_CM_CAP_VERSION_MASK     ((uint32_t)0xF)
#define CXL_CM_CAP_VERSION_SHIFT         16

/*
 * Capability Pointer: bits [31:20].
 *
 * IMPORTANT: this is a BYTE offset relative to the start of the
 * CXL_Capability_Header (i.e. relative to the 0x1000 block for the primary
 * range). It is added as-is - do NOT shift left by 2. Matches Linux
 * cxl_probe_component_regs() in drivers/cxl/core/regs.c.
 */
#define CXL_CM_CAP_PTR_MASK         ((uint32_t)0xFFF)
#define CXL_CM_CAP_PTR_SHIFT             20

/* CXL_Capability_ID assignment - Table 8-22 */
#define CXL_CM_CAP_ID_NULL          0x0000
#define CXL_CM_CAP_ID_HEADER        0x0001
#define CXL_CM_CAP_ID_RAS           0x0002
#define CXL_CM_CAP_ID_SECURITY      0x0003
#define CXL_CM_CAP_ID_LINK          0x0004
#define CXL_CM_CAP_ID_HDM           0x0005
#define CXL_CM_CAP_ID_EXT_SECURITY  0x0006
#define CXL_CM_CAP_ID_IDE           0x0007
#define CXL_CM_CAP_ID_SNOOP_FILTER  0x0008
#define CXL_CM_CAP_ID_TIMEOUT_ISO   0x0009
#define CXL_CM_CAP_ID_CM_EXT_REG    0x000A
#define CXL_CM_CAP_ID_BI_ROUTE      0x000B
#define CXL_CM_CAP_ID_BI_DECODER    0x000C
#define CXL_CM_CAP_ID_CACHEID_ROUTE 0x000D
#define CXL_CM_CAP_ID_CACHEID_DEC   0x000E
#define CXL_CM_CAP_ID_EXT_HDM       0x000F
#define CXL_CM_CAP_ID_EXT_METADATA  0x0010

/* Structures with ID 0001h..000Ah may NOT appear in an Extended Range. */
#define CXL_CM_CAP_ID_PRIMARY_ONLY_MAX  CXL_CM_CAP_ID_CM_EXT_REG

/* --------------------------------------------------------------------------
 * 2.2 CXL.cachemem Extended Ranges Register - 8.2.4.25.1
 *
 * 16-bit bitmap: bit n set => range (n*0x1000)-(n*0x1000+0xFFF) hosts a
 * CXL.cachemem extended range. Bits 0, 1 and 14 are reserved.
 * -------------------------------------------------------------------------- */

#define CXL_CM_EXT_RANGES_REG_OFFSET    0x00
#define CXL_CM_EXT_RANGE_BIT_LO         2
#define CXL_CM_EXT_RANGE_BIT_HI         13
#define CXL_CM_EXT_RANGE_BIT_F000       15      /* covers F000h-FFFFh */

#define CXL_CM_EXT_RANGE_BASE(bit)  ((uint64_t)(bit) * 0x1000ULL)

/* ==========================================================================
 * 3. CXL RAS Capability Structure - 8.2.4.17
 * ========================================================================== */

#define CXL_RAS_OFF_UNCOR_STATUS    0x00
#define CXL_RAS_OFF_UNCOR_MASK      0x04
#define CXL_RAS_OFF_UNCOR_SEVERITY  0x08
#define CXL_RAS_OFF_COR_STATUS      0x0C
#define CXL_RAS_OFF_COR_MASK        0x10
#define CXL_RAS_OFF_CAP_CONTROL     0x14
#define CXL_RAS_OFF_HEADER_LOG      0x18
#define CXL_RAS_HEADER_LOG_DWORDS   16
#define CXL_RAS_CAPABILITY_LENGTH   0x58

/* Uncorrectable Error Status bits */
#define CXL_RAS_UC_CACHE_DATA_PARITY    (1u << 0)
#define CXL_RAS_UC_CACHE_ADDR_PARITY    (1u << 1)
#define CXL_RAS_UC_CACHE_BE_PARITY      (1u << 2)
#define CXL_RAS_UC_CACHE_DATA_ECC       (1u << 3)
#define CXL_RAS_UC_MEM_DATA_ECC         (1u << 4)
#define CXL_RAS_UC_MEM_ADDR_PARITY      (1u << 5)
#define CXL_RAS_UC_MEM_BE_PARITY        (1u << 6)
#define CXL_RAS_UC_MEM_DATA_PARITY      (1u << 7)
#define CXL_RAS_UC_ATA_PARITY           (1u << 8)
#define CXL_RAS_UC_INTERNAL_ERR         (1u << 14)
#define CXL_RAS_UC_IDE_TX_ERR           (1u << 15)
#define CXL_RAS_UC_IDE_RX_ERR           (1u << 16)
#define CXL_RAS_UC_MASK                 (0x0001DFFFu)

/* Correctable Error Status bits */
#define CXL_RAS_CE_INTERNAL_ERR         (1u << 0)
#define CXL_RAS_CE_CACHE_DATA_ECC       (1u << 1)
#define CXL_RAS_CE_MEM_DATA_ECC         (1u << 2)
#define CXL_RAS_CE_ATA_ERR              (1u << 3)
#define CXL_RAS_CE_CACHE_ADDR_PARITY    (1u << 6)
#define CXL_RAS_CE_MASK                 (0x0000004Fu)

/* Error Capabilities and Control */
#define CXL_RAS_CAP_FIRST_ERR_PTR_MASK  ((uint32_t)0x3F)
#define CXL_RAS_CAP_MULTI_HDR_REC_CAP   (1u << 9)
#define CXL_RAS_CAP_POISON_ENABLED      (1u << 13)

/* ==========================================================================
 * 4. CXL Link Capability Structure - 8.2.4.19
 * ========================================================================== */

#define CXL_LINK_OFF_CAP            0x00
#define CXL_LINK_OFF_CTRL_STATUS    0x08
#define CXL_LINK_OFF_RX_CREDIT_CTRL 0x10
#define CXL_LINK_OFF_RX_CREDIT_RET  0x18
#define CXL_LINK_OFF_TX_CREDIT_STAT 0x20
#define CXL_LINK_OFF_ACK_TIMER      0x28
#define CXL_LINK_OFF_DEFEATURE      0x30
#define CXL_LINK_OFF_RX_CREDIT_CTRL2 0x38
#define CXL_LINK_OFF_RX_CREDIT_RET2  0x40
#define CXL_LINK_OFF_TX_CREDIT_STAT2 0x48

#define CXL_LINK_CTRL_LL_RESET          (1ull << 0)
#define CXL_LINK_CTRL_LL_INIT_STALL     (1ull << 1)
#define CXL_LINK_CTRL_LL_CRD_STALL      (1ull << 2)
#define CXL_LINK_CTRL_INIT_STATE_MASK   ((uint64_t)0x3)
#define CXL_LINK_CTRL_INIT_STATE_SHIFT  3

/* ==========================================================================
 * 5. CXL HDM Decoder Capability Structure - 8.2.4.20
 * ========================================================================== */

#define CXL_HDM_OFF_CAP             0x00
#define CXL_HDM_OFF_GLOBAL_CTRL     0x04

/* Decoder n register offsets */
#define CXL_HDM_DEC_BASE_LOW(n)     (0x20ULL * (n) + 0x10)
#define CXL_HDM_DEC_BASE_HIGH(n)    (0x20ULL * (n) + 0x14)
#define CXL_HDM_DEC_SIZE_LOW(n)     (0x20ULL * (n) + 0x18)
#define CXL_HDM_DEC_SIZE_HIGH(n)    (0x20ULL * (n) + 0x1C)
#define CXL_HDM_DEC_CTRL(n)         (0x20ULL * (n) + 0x20)
#define CXL_HDM_DEC_TARGET_LOW(n)   (0x20ULL * (n) + 0x24)
#define CXL_HDM_DEC_TARGET_HIGH(n)  (0x20ULL * (n) + 0x28)
#define CXL_HDM_DEC_SKIP_LOW(n)     CXL_HDM_DEC_TARGET_LOW(n)
#define CXL_HDM_DEC_SKIP_HIGH(n)    CXL_HDM_DEC_TARGET_HIGH(n)

/* Capability register */
#define CXL_HDM_CAP_DECODER_COUNT_MASK  ((uint32_t)0xF)
#define CXL_HDM_CAP_TARGET_COUNT_MASK   ((uint32_t)0xF)
#define CXL_HDM_CAP_TARGET_COUNT_SHIFT  4
#define CXL_HDM_CAP_A11TO8_INTERLEAVE   (1u << 8)
#define CXL_HDM_CAP_A14TO12_INTERLEAVE  (1u << 9)
#define CXL_HDM_CAP_POISON_ON_DECODE    (1u << 10)
#define CXL_HDM_CAP_3_6_12_WAY          (1u << 11)
#define CXL_HDM_CAP_16_WAY              (1u << 12)
#define CXL_HDM_CAP_UIO                 (1u << 13)
#define CXL_HDM_CAP_UIO_DEC_COUNT_MASK  ((uint32_t)0xF)
#define CXL_HDM_CAP_UIO_DEC_COUNT_SHIFT 16
#define CXL_HDM_CAP_MEMDATA_NXM         (1u << 20)
#define CXL_HDM_CAP_COHERENCY_MASK      ((uint32_t)0x3)
#define CXL_HDM_CAP_COHERENCY_SHIFT     21

/* Global Control */
#define CXL_HDM_GCTRL_POISON_ON_DECODE_ERR_EN   (1u << 0)
#define CXL_HDM_GCTRL_HDM_DECODER_ENABLE        (1u << 1)

/* Decoder n Control */
#define CXL_HDM_CTRL_IG_MASK        ((uint32_t)0xF)
#define CXL_HDM_CTRL_IW_MASK        ((uint32_t)0xF)
#define CXL_HDM_CTRL_IW_SHIFT       4
#define CXL_HDM_CTRL_LOCK_ON_COMMIT (1u << 8)
#define CXL_HDM_CTRL_COMMIT         (1u << 9)
#define CXL_HDM_CTRL_COMMITTED      (1u << 10)
#define CXL_HDM_CTRL_COMMIT_ERROR   (1u << 11)
#define CXL_HDM_CTRL_TARGET_RANGE_TYPE (1u << 12)
#define CXL_HDM_CTRL_BI             (1u << 13)

/* Memory Base/Size Low: only bits [31:28] are implemented (28-bit granularity) */
#define CXL_HDM_BASE_LOW_SHIFT      28
#define CXL_HDM_SIZE_LOW_SHIFT      28

/*
 * Decoder Count encoding -> number of decoders (8.2.4.20.1):
 *   0 -> 1, 1 -> 2, 2 -> 4, 3 -> 6, 4 -> 8, 5 -> 10,
 *   6 -> 12, 7 -> 14, 8 -> 16, 9 -> 20, Ah -> 24, Bh -> 28, Ch -> 32
 */
static inline int cxl_hdm_decoder_count(uint32_t cap)
{
    unsigned int v = cap & CXL_HDM_CAP_DECODER_COUNT_MASK;

    if (v == 0)
        return 1;
    if (v <= 8)
        return (int)(v * 2);
    if (v <= 12)
        return (int)((v - 4) * 4);
    return -1;
}

/* Structure length: 0x10 header/global + 0x20 per decoder */
#define CXL_HDM_CAP_LENGTH(n)       (0x10u + 0x20u * (unsigned)(n))

/* ==========================================================================
 * 6. CXL Security / IDE / Snoop Filter / Timeout - 8.2.4.18 / .22 / .23 / .24
 * ========================================================================== */

#define CXL_SEC_OFF_POLICY          0x00
#define CXL_SEC_POLICY_TRUST_MASK   ((uint32_t)0x3)
#define CXL_SEC_POLICY_BLOCK_HDM_DB (1u << 2)

#define CXL_IDE_OFF_CAP             0x00
#define CXL_IDE_OFF_CTRL            0x04
#define CXL_IDE_OFF_STATUS          0x08
#define CXL_IDE_OFF_ERR_STATUS      0x0C
#define CXL_IDE_OFF_KEY_REFRESH_CAP 0x10
#define CXL_IDE_OFF_TRUNC_DELAY_CAP 0x14
#define CXL_IDE_OFF_KEY_REFRESH_CTL 0x18
#define CXL_IDE_OFF_TRUNC_DELAY_CTL 0x1C
#define CXL_IDE_CAP_CAPABLE         (1u << 0)
#define CXL_IDE_CAP_SKID_MODE       (1u << 1)
#define CXL_IDE_CAP_CONTAINMENT     (1u << 2)
#define CXL_IDE_CAP_ALGO_MASK       ((uint32_t)0x1F)
#define CXL_IDE_CAP_ALGO_SHIFT      17

#define CXL_SNOOP_OFF_GROUP_ID      0x00
#define CXL_SNOOP_OFF_CAPACITY      0x04

#define CXL_TIO_OFF_CAP             0x00
#define CXL_TIO_OFF_CTRL            0x08
#define CXL_TIO_OFF_STATUS          0x0C

/* ==========================================================================
 * 7. CXL ARB/MUX registers - 8.2.5 (offsets relative to 0xE000)
 * ========================================================================== */

#define CXL_ARBMUX_OFF_PM_TIMEOUT_CTRL  0x00
#define CXL_ARBMUX_OFF_UC_ERR_STATUS    0x04
#define CXL_ARBMUX_OFF_UC_ERR_MASK      0x08
#define CXL_ARBMUX_OFF_ARB_CTRL_IO      0x180
#define CXL_ARBMUX_OFF_ARB_CTRL_CM      0x1C0

#define CXL_ARBMUX_PM_TIMEOUT_EN        (1u << 0)
#define CXL_ARBMUX_PM_TIMEOUT_VAL_MASK  ((uint32_t)0x3)
#define CXL_ARBMUX_PM_TIMEOUT_VAL_SHIFT 1
#define CXL_ARBMUX_ARB_WEIGHT_MASK      ((uint32_t)0xF)
#define CXL_ARBMUX_ARB_WEIGHT_SHIFT     4

/* ==========================================================================
 * 8. CXL Device Register Block - 8.2.8
 * ========================================================================== */

#define CXL_DEV_CAP_ARRAY_OFF       0x00
#define CXL_DEV_CAP_ARRAY_ID_MASK   ((uint64_t)0xFFFF)
#define CXL_DEV_CAP_ARRAY_VERSION_MASK  ((uint64_t)0xFF)
#define CXL_DEV_CAP_ARRAY_VERSION_SHIFT 16
#define CXL_DEV_CAP_ARRAY_TYPE_MASK ((uint64_t)0xF)
#define CXL_DEV_CAP_ARRAY_TYPE_SHIFT    24
#define CXL_DEV_CAP_ARRAY_COUNT_MASK ((uint64_t)0xFFFF)
#define CXL_DEV_CAP_ARRAY_COUNT_SHIFT   32

#define CXL_DEV_CAP_TYPE_INFER      0x0
#define CXL_DEV_CAP_TYPE_MEMDEV     0x1
#define CXL_DEV_CAP_TYPE_SWITCH_MBOX 0x2

/* Each capability header is 16 bytes */
#define CXL_DEV_CAP_HDR_STRIDE      0x10
#define CXL_DEV_CAP_HDR_ID_MASK     ((uint64_t)0xFFFF)
#define CXL_DEV_CAP_HDR_VER_MASK    ((uint64_t)0xFF)
#define CXL_DEV_CAP_HDR_VER_SHIFT   16

/* Capability IDs */
#define CXL_DEV_CAP_ID_STATUS       0x0001
#define CXL_DEV_CAP_ID_PRIMARY_MBOX 0x0002
#define CXL_DEV_CAP_ID_SECOND_MBOX  0x0003
#define CXL_DEV_CAP_ID_MEMDEV       0x4000

/* Device Status / Event Status - 8.2.8.3.1 */
#define CXL_DEV_EVENT_INFO          (1u << 0)
#define CXL_DEV_EVENT_WARN          (1u << 1)
#define CXL_DEV_EVENT_FAIL          (1u << 2)
#define CXL_DEV_EVENT_FATAL         (1u << 3)
#define CXL_DEV_EVENT_DCD           (1u << 4)

/* Mailbox - 8.2.8.4 (offsets relative to mailbox capability offset) */
#define CXL_MBOX_OFF_CAPS           0x00
#define CXL_MBOX_OFF_CTRL           0x04
#define CXL_MBOX_OFF_CMD            0x08
#define CXL_MBOX_OFF_STATUS         0x10
#define CXL_MBOX_OFF_BG_STATUS      0x18
#define CXL_MBOX_OFF_PAYLOAD        0x20

#define CXL_MBOX_CAP_PAYLOAD_SIZE_MASK  ((uint32_t)0x1F)
#define CXL_MBOX_CAP_IRQ            (1u << 5)
#define CXL_MBOX_CAP_BG_CMD_IRQ     (1u << 6)
#define CXL_MBOX_CAP_IRQ_MSGNUM_MASK ((uint32_t)0xF)
#define CXL_MBOX_CAP_IRQ_MSGNUM_SHIFT 7

#define CXL_MBOX_CTRL_DOORBELL      (1u << 0)
#define CXL_MBOX_CTRL_IRQ_EN        (1u << 1)
#define CXL_MBOX_CTRL_BG_CMD_IRQ_EN (1u << 2)

#define CXL_MBOX_CMD_OPCODE_MASK    ((uint64_t)0xFFFF)
#define CXL_MBOX_CMD_PAYLOAD_LEN_MASK ((uint64_t)0x1FFFFF)
#define CXL_MBOX_CMD_PAYLOAD_LEN_SHIFT 16

#define CXL_MBOX_STATUS_BG_CMD      (1u << 0)
#define CXL_MBOX_STATUS_RET_CODE_MASK ((uint64_t)0xFFFF)
#define CXL_MBOX_STATUS_RET_CODE_SHIFT 32
#define CXL_MBOX_STATUS_VENDOR_MASK ((uint64_t)0xFFFF)
#define CXL_MBOX_STATUS_VENDOR_SHIFT 48

/* Command opcodes - 8.2.9 */
#define CXL_MBOX_OP_IDENTIFY            0x0001
#define CXL_MBOX_OP_BG_OPERATION_STATUS 0x0002
#define CXL_MBOX_OP_GET_RESPONSE_LIMIT  0x0003
#define CXL_MBOX_OP_SET_RESPONSE_LIMIT  0x0004
#define CXL_MBOX_OP_GET_EVENT_RECORDS   0x0100
#define CXL_MBOX_OP_CLEAR_EVENT_RECORDS 0x0101
#define CXL_MBOX_OP_IDENTIFY_MEMDEV     0x4001
#define CXL_MBOX_OP_GET_PARTITION_INFO  0x4100

/* Memory Device Status - 8.2.8.5.1.1 */
#define CXL_MEMDEV_STATUS_FATAL         (1u << 0)
#define CXL_MEMDEV_STATUS_FW_HALT       (1u << 1)
#define CXL_MEMDEV_STATUS_MEDIA_MASK    ((uint64_t)0x3)
#define CXL_MEMDEV_STATUS_MEDIA_SHIFT   2
#define CXL_MEMDEV_STATUS_MBOX_READY    (1u << 4)
#define CXL_MEMDEV_STATUS_RESET_NEEDED_MASK  ((uint64_t)0x7)
#define CXL_MEMDEV_STATUS_RESET_NEEDED_SHIFT 5

/* ==========================================================================
 * 9. CPMU registers (8.2.7, Table 8-32 Version=1)
 * ========================================================================== */

#define CXL_CPMU_CAP                 0x000   /* 8 bytes */
#define CXL_CPMU_OVERFLOW            0x010   /* 8 bytes */
#define CXL_CPMU_FREEZE              0x018   /* 8 bytes, if Freeze Support */
#define CXL_CPMU_EVCAP_BASE          0x100   /* 8 bytes each, up to 32 */
#define CXL_CPMU_EVCAP(n)            (0x100 + (n) * 8)
#define CXL_CPMU_CTR_CFG_BASE        0x200   /* 8 bytes each, up to 64 */
#define CXL_CPMU_CTR_CFG(n)          (0x200 + (n) * 8)
#define CXL_CPMU_CTR_FILTER_BASE     0x400   /* 4 bytes each */
#define CXL_CPMU_CTR_FILTER(n, m)    (0x400 + (n) * 0x20 + (m) * 4)
#define CXL_CPMU_CTR_DATA_BASE       0xC00   /* 8 bytes each, MUST be 8B access */
#define CXL_CPMU_CTR_DATA(n)         (0xC00 + (n) * 8)

/* CPMU Capability (00h). Two 0-based fields: units and event cap regs. */
#define CXL_CPMU_CAP_UNITS_MASK      0x3Full
#define CXL_CPMU_CAP_UNITS_SHIFT     0        /* raw + 1 = count */
#define CXL_CPMU_CAP_CTRWIDTH_MASK   0xFFull
#define CXL_CPMU_CAP_CTRWIDTH_SHIFT  8
#define CXL_CPMU_CAP_EVCAPS_MASK     0x1Full
#define CXL_CPMU_CAP_EVCAPS_SHIFT    20       /* raw + 1 = count */
#define CXL_CPMU_CAP_FILTERS_MASK    0xFFull
#define CXL_CPMU_CAP_FILTERS_SHIFT   32
#define CXL_CPMU_CAP_IMN_MASK        0xFull
#define CXL_CPMU_CAP_IMN_SHIFT       44
#define CXL_CPMU_CAP_WR_FROZEN       (1ull << 48)
#define CXL_CPMU_CAP_FREEZE_SUP      (1ull << 49)
#define CXL_CPMU_CAP_IRQ_OVF_SUP     (1ull << 50)
#define CXL_CPMU_CAP_VERSION_MASK    0xFull
#define CXL_CPMU_CAP_VERSION_SHIFT   60

/* Counter Configuration (200h + n*8) */
#define CXL_CPMU_CFG_TYPE_MASK       0x3ull
#define CXL_CPMU_CFG_TYPE_FREE_RUN   0x0
#define CXL_CPMU_CFG_TYPE_FIXED      0x1
#define CXL_CPMU_CFG_TYPE_CONFIG     0x2
#define CXL_CPMU_CFG_ENABLE          (1ull << 8)
#define CXL_CPMU_CFG_IRQ_OVF         (1ull << 9)
#define CXL_CPMU_CFG_GBL_FREEZE      (1ull << 10)
#define CXL_CPMU_CFG_EDGE            (1ull << 11)
#define CXL_CPMU_CFG_INVERT          (1ull << 12)
#define CXL_CPMU_CFG_THRESH_MASK     0xFFull
#define CXL_CPMU_CFG_THRESH_SHIFT    16
#define CXL_CPMU_CFG_EVENTS_MASK     0xFFFFFFFFull
#define CXL_CPMU_CFG_EVENTS_SHIFT    24
#define CXL_CPMU_CFG_GRP_INDEX_MASK  0x1Full
#define CXL_CPMU_CFG_GRP_INDEX_SHIFT 59

/* Event Capabilities (100h + n*8) */
#define CXL_CPMU_EVCAP_EVENTS_MASK   0xFFFFFFFFull
#define CXL_CPMU_EVCAP_GROUP_MASK    0xFFFFull
#define CXL_CPMU_EVCAP_GROUP_SHIFT   32
#define CXL_CPMU_EVCAP_VENDOR_MASK   0xFFFFull
#define CXL_CPMU_EVCAP_VENDOR_SHIFT  48

/* Event Group IDs (Table 13-5) and their Filter ID assignment.
 * CXL.mem groups use Filter ID 0; DDR Interface uses Filter ID 1. */
#define CXL_CPMU_GRP_BASE            0x00
#define CXL_CPMU_GRP_D2H_REQ         0x10
#define CXL_CPMU_GRP_D2H_RSP         0x11
#define CXL_CPMU_GRP_H2D_REQ         0x12
#define CXL_CPMU_GRP_H2D_RSP         0x13
#define CXL_CPMU_GRP_CACHE_DATA      0x14
#define CXL_CPMU_GRP_M2S_REQ         0x20    /* Filter ID 0 */
#define CXL_CPMU_GRP_M2S_RWD         0x21    /* Filter ID 0 */
#define CXL_CPMU_GRP_M2S_BIRSP       0x22    /* Filter ID 0 */
#define CXL_CPMU_GRP_S2M_BISNP       0x23    /* Filter ID 0 */
#define CXL_CPMU_GRP_S2M_NDR         0x24    /* Filter ID 0 */
#define CXL_CPMU_GRP_S2M_DRS         0x25    /* Filter ID 0 */
#define CXL_CPMU_GRP_DDR_IF          0x8000  /* Filter ID 1 */

/* Filter register reset default = no filtering */
#define CXL_CPMU_FILTER_NONE         0xFFFFFFFFu
#define CXL_CPMU_FILTER_ID_HDM       0
#define CXL_CPMU_FILTER_ID_DDR       1

/* Filter ID 1 field layout (Bank/BankGroup/Rank/Channel, FFh = all) */
#define CXL_CPMU_F1_BANK_MASK        0xFFu
#define CXL_CPMU_F1_BANK_SHIFT       0
#define CXL_CPMU_F1_BANKGROUP_MASK   0xFFu
#define CXL_CPMU_F1_BANKGROUP_SHIFT  8
#define CXL_CPMU_F1_RANK_MASK        0xFFu
#define CXL_CPMU_F1_RANK_SHIFT       16
#define CXL_CPMU_F1_CHANNEL_MASK     0xFFu
#define CXL_CPMU_F1_CHANNEL_SHIFT    24

/* ==========================================================================
 * 10. Small helpers
 * ========================================================================== */

#define CXL_FIELD_GET(mask, val)        ((val) & (mask))
#define CXL_FIELD_GET_SHIFT(mask, val, shift) \
        (((val) & (mask)) >> (shift))

static inline uint64_t cxl_regloc_block_offset(uint32_t off_lo, uint32_t off_hi)
{
    uint64_t lo = (uint64_t)((off_lo >> CXL_REGLOC_OFFSET_LOW_SHIFT) &
                             CXL_REGLOC_OFFSET_LOW_MASK) << 16;
    return lo | ((uint64_t)off_hi << 32);
}

#endif /* CXL_REGS_H */
