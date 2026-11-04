# DAC tile synchronization (MTS) on the RFSoC 4x2

Primary-source notes on why the DAC_A ↔ DAC_B delay changes from boot to boot, whether multi-tile synchronization (MTS) can fix it on our board and firmware, and what to do instead. Read in November 2026. Every claim cites a source. Statements marked **(inference)** are our own reasoning or arithmetic, not something a source says.

**Bench observation that started this.** In loopback, DAC_B led DAC_A by 1.55 ns on one boot and by 3.30 ns after a power cycle, a change of about 1.75 ns. The phase at 0 Hz and the amplitude ratio were stable.

**Source tags**

| Tag | Source |
|---|---|
| `[fix]` | `tests/fixtures/soccfg_rfsoc4x2.json` (the firmware config the PC sees) |
| `[fwHWH]` | `~/jupyter_notebooks/qick_firmware/qick_4x2.hwh` on the board: our firmware, parsed read-only |
| `[libHWH]` | `.venv/lib/python3.12/site-packages/qick/qick_4x2.hwh`: the bitfile bundled with the library (not ours) |
| `[lib] file:line` | Installed QICK 0.2.442, `.venv/lib/python3.12/site-packages/qick/<file>` |
| `[RD-RM]` | Real Digital, *RFSoC 4x2 Reference Manual*, https://www.realdigital.org/downloads/d6a7543b5033e5dadde272a48bcb5090.pdf (28 pp., downloaded 2026-11-04, read with `pdftotext`). Sections: "Clocking" and Figure 5 "RFSoC Clocking Scheme" (p. 8); "Clock Signals" table; "RF Subsystem Signals" (p. 24–25) |
| `[xrfclk]` | `/usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfclk/LMK04828_245.76.txt` on the board (PYNQ 3.0.1), decoded with the LMK04828B register map shipped in `[lib] ipq_pynq_utils/ipq_pynq_utils/data/lmk04828b_regmap.json` |
| `[xrfdc]` | `/usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc/` on the board (package `xrfdc` 1.0, PYNQ 3.0.1): `__init__.py`, `xrfdc_functions.c` (the cffi declarations), `libxrfdc.so` (inspected with `nm -D`) |
| `[PYNQ]` | https://github.com/Xilinx/PYNQ, `sdbuild/packages/xrfdc/` at `master` (commit `d90670c`, 2026-09-29) and at tag `v3.0.1` |
| `[esw] file:line` | Xilinx embeddedsw, `XilinxProcessorIPLib/drivers/rfdc/src/<file>` at tag `xilinx-v2020.2`, the version PYNQ v3.0.1 builds `libxrfdc.so` from (`[PYNQ]` v3.0.1 `Makefile`: `ESW_VERSION := xilinx-v2020.2`) |
| `[MTS] path` | https://github.com/Xilinx/RFSoC-MTS (commit `f8e93e7`, 2023-06-22), AMD's PYNQ MTS overlay for the ZCU208 **and the RFSoC 4x2** |
| `[PG269] section` | AMD PG269, *Zynq UltraScale+ RFSoC RF Data Converter LogiCORE IP Product Guide*, current online edition, https://docs.amd.com/r/en-US/pg269-rf-data-converter/<section> (read with WebFetch) |
| `[gh] path` | https://github.com/openquantumhardware/qick at `main`, commit `80753a9` (2026-10-30), still version 0.2.442 (`qick_lib/qick/VERSION`), the same as PyPI's latest |
| `[#277]` | QICK issue #277, "Start time of pulses across multiple DACs misaligned" (RFSoC 4x2, 2024–2025), https://github.com/openquantumhardware/qick/issues/277 |

---

## Short answer

- **DAC_A and DAC_B are on different tiles**: DAC_A is DAC tile 2 (package tile 230) and DAC_B is DAC tile 0 (tile 228). Each tile pins out only one channel. A skew that changes at every boot is what PG269 says to expect across tiles that are not synchronized.
- **The board hardware is ready for MTS.** The LMK04828 already sends a continuous 7.68 MHz SYSREF to the RFSoC's analog SYSREF pins and to a PL pin. It also sends a 122.88 MHz PL clock.
- **Our firmware is not ready.** MTS is off for every tile. There is no `user_sysref` input, and the DAC fabric clock comes from tile 2's output clock, not from the PL clock input. Turning MTS on means **rebuilding the firmware**.
- **The software is half ready.** The board's `libxrfdc.so` already contains `XRFdc_MultiConverter_Sync`, but PYNQ's Python wrapper does not expose it. A short cffi declaration is enough to call it.
- **QICK has no MTS support.** No QICK firmware project enables MTS, and the maintainers said so in [#277]. That holds for 0.2.442 and for current `main`, which is the same version.
- **Recommendation:**
  1. Now, software only: treat the I↔Q delay as a per-boot calibration value, as a delay term in the TX I/Q calibration.
  2. Optionally: cancel the envelope skew with the RF-DC's per-channel **coarse delay**, in steps of one sample (0.10 ns), range 0–40 samples.
  3. MTS only if the user decides the firmware rebuild is worth it (see §6).

---

## 1. Which tiles DAC_A, DAC_B, ADC_C and ADC_D use

| Port | QICK channel `[fix]` | RF-DC tile, block `[fix]` | Package pin name `[RD-RM]` "RF Subsystem Signals" |
|---|---|---|---|
| DAC_A | gen 1, `dac: "20"` | DAC tile 2, block 0 | `DAC_VOUT0_230` (DAC tile 230) |
| DAC_B | gen 0, `dac: "00"` | DAC tile 0, block 0 | `DAC_VOUT0_228` (DAC tile 228) |
| ADC_D | ro 0, `adc: "00"` | ADC tile 0, block 0 | `ADC_VIN_I01_224` |
| ADC_C | ro 1, `adc: "02"` | ADC tile 0, block 2 (index [0, 1]) | `ADC_VIN_I23_224` |
| ADC_B | ro 2, `adc: "20"` | ADC tile 2, block 0 | `ADC_VIN_I01_226` |

- **DAC_A and DAC_B do not share a tile.** `[fix]` lists `rf.tiles.dac` as tile `"0"` with blocks `["00"]` and tile `"2"` with blocks `["20"]`. The manual shows one `DAC_VOUT0_*` pin per tile, 228 and 230 `[RD-RM]`. The board therefore **cannot** put I and Q on one DAC tile **(inference)**.
- **ADC_D and ADC_C share ADC tile 0** (`[fix]` tile `"0"`, blocks `["00","02"]`; both are on tile 224 in `[RD-RM]`). PG269 says "the converters within a single tile share the clocking and data infrastructure, so the sample rates and latency are fixed" `[PG269] Multi-Tile-Synchronization`. The planned I/Q return path on ADC_D + ADC_C should therefore **not** show a per-boot skew **(inference)**.
- **Each DAC tile runs its own PLL.** In `[fwHWH]`:
  - `C_DAC0_PLL_Enable=true`, `C_DAC0_Clock_Source=4`, `C_DAC0_Refclk_Freq=491.520`, `C_DAC0_Clock_Dist=0`;
  - `C_DAC2_PLL_Enable=true`, `C_DAC2_Clock_Source=6`, `C_DAC2_Clock_Dist=0`;
  - both at `C_DACn_Sampling_Rate=9.8304`, `C_DACn_Fabric_Freq=614.400`, `C_DACn_Interpolation=1`.
- **Both tiles' reference clocks come from one source.** They come from the DAC LMX2594 ("PLL2"), from its outputs A (tile 230) and B (tile 228), at 491.52 MHz `[RD-RM]` Figure 5.
- **Both DAC tiles' AXI-Stream inputs run on one clock: tile 2's output clock.**
  - In `[fwHWH]`, the RF-DC ports `s0_axis_aclk` and `s2_axis_aclk` are both driven by `usp_rf_data_converter_0_clk_dac2`, and `clk_dac0` is unconnected.
  - The standard QICK 4x2 tProc v2 project does the same: `clk_dac2` drives `s0_axis_aclk`, `s2_axis_aclk`, both signal generators and `qick_processor_0/t_clk_i` (`[gh] firmware/projects/qick_tprocv2_4x2_standard/bd_2023-1.tcl:1902`).
  - That is why `[fix]` shows one clock group, `[tProc core, tProc timing, DAC 0, DAC 2]`.
  - The bundled bitfile differs: it clocks the generators from `clk_dac0` `[libHWH]`.

**What this implies (inference).**

- The PL side of both DAC paths is one clock domain, so the tProc → generator → RF-DC path is identical for the two outputs.
- The per-boot difference is therefore inside the RF-DC. Tile 0's internal clocks come from its own PLL and dividers. The phase of those dividers, and where tile 0's gearbox FIFO lands relative to `clk_dac2`, are set at tile start-up.
- PG269 names exactly these sources: "the clock divider phase", "FIFO latencies, clock skew, and data skew", and "independent gearbox FIFOs" that give "a non-deterministic latency that must also be measured and corrected for by using SYSREF" `[PG269] Detailed-Description`.
- The numbers fit:
  - The step we saw (≈1.75 ns) is close to one fabric period, 1/614.4 MHz = 1.628 ns = 16 samples.
  - Each sample is T1 = 1/9830.4 MHz = 0.1017 ns.
  - The remaining ≈0.12 ns is about one sample, or measurement error.
- A delay that changes while the phase at 0 Hz stays put is what a pure latency step looks like.

**When to expect a new value.** Every time the tiles start up again: after a power cycle, and probably also at each firmware load, because QICK downloads the bitstream every time the service starts. [#277] reports this on a 4x2 firmware with common clocks: "a time delay between the two outputs that is random each time you reload the firmware, but is constant otherwise" (comment by meeg, 2025-02-26). We have not yet checked on our board whether restarting the service alone changes the skew.

---

## 2. What MTS needs on the 4x2, and what we have

### 2.1 PG269 requirements

1. **One analog SYSREF.** "A single analog SYSREF input per device is distributed internally to all RF-ADCs and RF-DACs" `[PG269] Detailed-Description`.
2. **A PL SYSREF and a common PL clock.** "The common clock for the PL user design and tiles is shown as PL Clock" and "There is a separate PL SYSREF for RF-ADCs (`user_sysref_adc`) and RF-DACs (`user_sysref_dac`)" `[PG269] Detailed-Description`.
3. **AXI-Stream clocks made from the PL clock input.**
   - The AXI4-Stream clocks "must be generated from the PL clock input".
   - "The PL clock must be a common multiple or sub-multiple of the RF-ADC and RF-DAC AXI4-Stream clocks", "related by an integer value".
   - "The PL clock input must be on a dedicated clock pin".
   - "the PL SYSREF frequency must be a common sub-multiple of all the clocks in the system" `[PG269] PL-SYSREF-Capture`.
4. **SYSREF frequency.**
   - It is an integer submultiple of GCD(DAC_fs/16, ADC_fs/16) and of "all PL clocks that sample it", and "less than 10 MHz".
   - It is "a continuous clock for the duration of the MTS procedure", "turned on and stabilized prior to the MTS function call".
   - Analog SYSREF and PL SYSREF "must be the same frequency and have a constant phase relationship" `[PG269] SYSREF-Signal-Requirements`.
5. **MTS enabled per tile in the IP.** The driver refuses tiles without it: `"%s tile %d is not enabled for MTS, check IP configuration"`, triggered when the tile's `XRFDC_MTS_DLY_ALIGNER0` register reads 0 `[esw] xrfdc_mts.c:1178–1184`.
6. **Order of operations.**
   1. "Enable all clocks and SYSREF generators".
   2. SYSREF analog capture.
   3. Clock divider reset.
   4. "FIFO latency measure and adjust".
   5. Synchronize NCO, QMC and coarse delay with SYSREF update events.

   The IP and the driver do steps 2–4. Restarting any tile, or changing a setting that changes the FIFO clock rate or width, means running MTS again `[PG269] Synchronization-Steps`.

### 2.2 Board clocking: SYSREF already reaches the RFSoC and the PL

From `[RD-RM]` Figure 5 and the clock tables, at the PYNQ defaults:

| LMK04828 output | Frequency | Goes to | RFSoC pin |
|---|---|---|---|
| OUT3 | 7.68 MHz | "RF SYS REFCLK", the RF-DC analog SYSREF | `DAC_230_SYSREF_P/N` U5/U4, "DEFAULT 7.680MHz" |
| OUT9 | 7.68 MHz | "PL RF SYS REFCLK", the PL SYSREF | `SYS_REF_FPGA_P/N` AP18/AR18, LVDS, "FOR ADC/DAC SUBSYSTEM" |
| OUT8 | 122.88 MHz | "PL SYS REFCLK", the PL clock | `FPGA_REFCLK_IN_P/N` AN11/AP11, LVDS |
| OUT4 | 245.76 MHz | DAC LMX2594 (PLL2) → 491.52 MHz to DAC tiles 228 and 230 | `DAC_228_REFCLK` R5/R4, `DAC_230_REFCLK` N5/N4 |
| OUT0 | 245.76 MHz | ADC LMX2594 (PLL1) → 491.52 MHz to ADC tiles 224 and 226 | |
| OUT1, OUT5 | off | SYNC inputs of the two LMX2594s | |

`[RD-RM]` "Clocking" adds: "If the SYNC input is needed, OUT1 and OUT5 of the LMK must be enabled to synchronize the downstream LMX's (OUT1 and OUT5 are powered off by default). Enabling OUT1 and OUT5 will also reset the dividers in the LMX's so that all ADC and DAC clocks are fully synchronized."

**The LMK configuration QICK loads already produces SYSREF.**

- QICK programs the clock chips with `xrfclk.set_ref_clks(lmk_freq=245.76, lmx_freq=491.52)` on the 4x2 (`[lib] qick.py:1288–1302`), i.e. PYNQ's `LMK04828_245.76.txt`.
- Decoding that file `[xrfclk]`:
  - `DCLKout0_DIV=10`, so the VCO is 2457.6 MHz.
  - `SYSREF_MUX=3` (continuous) and `SYSREF_DIV=320`, so SYSREF is 2457.6/320 = **7.68 MHz, continuous**.
  - `SYSREF_PD=0`.
  - `SDCLKout3`, `SDCLKout9` and `SDCLKout11` are on (`_PD=0`, `_DIS_MODE=0`, `_FMT=3`, `_MUX=1` = SYSREF). `SDCLKout1`, `5` and `13` are off.
  - `DCLKout8_DIV=20`, giving 122.88 MHz.
- This matches the 7.68 MHz the manual gives for U5 and AP18. **No clock-chip change is needed to get SYSREF (inference from the decode).**
- For comparison, the 4x2 LMK file in AMD's MTS overlay `[MTS] boards/RFSoC4x2/xrfclk/LMK04828_500.0.txt` has the same SYSREF outputs on, plus `SDCLKout1` (VCO 3000 MHz, `SYSREF_DIV=600` → 5 MHz).

**Our frequency plan against the SYSREF rules (arithmetic).**

| Clock | Clock / 7.68 MHz | Integer? |
|---|---|---|
| DAC fs/16 = 614.4 MHz | 80 | yes |
| ADC fs/16 = 276.48 MHz | 36 | yes |
| DAC fabric 614.4 MHz | 80 | yes |
| ADC fabric 552.96 MHz | 72 | yes |
| PL clock input 122.88 MHz | 16 | yes |

Two consequences:

- **DACs only.** 614.4 = 5 × 122.88, so the PL clock input satisfies PG269's integer rule.
- **ADCs too.** 552.96 / 122.88 = 4.5 is **not** an integer, which breaks the rule. Including the ADC tiles would mean changing OUT8, e.g. to 61.44 MHz (`DCLKout8_DIV=40`): 614.4/61.44 = 10 and 552.96/61.44 = 9 **(inference, not tested)**.

### 2.3 What our firmware has (`[fwHWH]`, RF-DC IP `xilinx.com:ip:usp_rf_data_converter:2.6`)

| Requirement | Our firmware |
|---|---|
| MTS enabled per tile | **No.** `C_DAC0..3_Multi_Tile_Sync=false`, `C_ADC0..3_Multi_Tile_Sync=false`, `C_DAC_MTS_Variable_Fabric_Width=false`. The bundled bitfile is the same `[libHWH]` |
| Analog SYSREF wired | Yes. `sysref_in_p/n` go to the top-level port `sysref_in_diff_p/n` (always there on this IP). `C_Sysref_Source=1` (meaning not checked) |
| PL SYSREF (`user_sysref_dac/adc`) | **No.** There is no such port on the IP instance and no `PL_SYSREF` / AP18 input |
| AXI-Stream clocks from the PL clock | **No.** `s0/s2_axis_aclk` = `clk_dac2` (the RF-DC's own output clock). There is no `PL_CLK` / AN11 input |

The standard QICK 4x2 tProc v2 project is the same: `sysref_in` is its only SYSREF connection (`[gh] firmware/projects/qick_tprocv2_4x2_standard/bd_2023-1.tcl:347,1852`). No QICK firmware project sets any `*_Multi_Tile_Sync` to true (grep over `[gh] firmware/`). Its `ios.xdc` borrows the PL DDR4 pins "from https://github.com/Xilinx/RFSoC-MTS/blob/main/boards/RFSoC4x2/build_mts/mts.xdc" but not the SYSREF pins.

### 2.4 A working 4x2 reference design: AMD's RFSoC-MTS

`[MTS] README.md` says "This design is available for the following boards: ZCU208, RFSoC4x2" (PYNQ v3.0.1, Vivado 2022.1). The 4x2 design does the following:

- **RF-DC IP** (`boards/RFSoC4x2/build_mts/mts.tcl`, `usp_rf_data_converter_1`):
  - `DACn_Multi_Tile_Sync {true}` and `ADCn_Multi_Tile_Sync {true}`.
  - Tile 2's PLL is on (`DAC2_PLL_Enable {true}`, `DAC2_Clock_Dist {2}`), and the other tiles take their clock from it (`DAC0_Clock_Source {6}`, `DAC0_PLL_Enable {false}`).
- **PL clocking:**
  - `PL_CLK` is on pin AN11 and `PL_SYSREF` on AP18 (`mts.xdc:8–9`).
  - `PL_CLK` → BUFG → a `clk_wiz` MMCM (`MTSclkwiz`) produces the RF fabric clock. That clock drives every `m*_axis_aclk` / `s*_axis_aclk` of the RF-DC (`mts.tcl:3392`).
  - `PL_SYSREF` is re-timed into that clock with `xpm_cdc_gen` (`synchronizeSYSREF`) and drives both `user_sysref_adc` and `user_sysref_dac` (`mts.tcl:1326–1349, 3403`).
  - `mts.xdc:168–179` adds input-delay constraints on `PL_SYSREF` "to ensure MTS requirements via PG269".
- **Software** (`rfsoc_mts/mts.py`):
  - `RFSOC4X2_DAC_TILES = 0b0101` (tiles 0 and 2) and `DAC_REF_TILE = 2`.
  - `sync_tiles()` sets `mts_dac_config.Tiles`, `SysRef_Enable = 1` and `Target_Latency`, then calls `mts_dac()`.
  - `init_tile_sync()` runs MTS on one tile, resets the MMCM and calls `dac_tiles[n].Reset()` on the group.

---

## 3. PYNQ's xrfdc driver and MTS

- **The installed Python wrapper does not expose MTS** `[xrfdc]`.
  - `RFdc` has no `mts_*` methods.
  - `xrfdc_functions.c` (the cffi `cdef`) declares no `XRFdc_MultiConverter_*` function and no `XRFdc_MultiConverter_Sync_Config` struct.
  - The only MTS-related names are the `ADCSysRefSource` / `DACSysRefSource` fields of `XRFdc_Config` and the constant `EVNT_SRC_SYSREF = 3`.
- **The shared library does contain MTS.** `nm -D libxrfdc.so` lists `XRFdc_MultiConverter_Init`, `XRFdc_MultiConverter_Sync`, `XRFdc_MTS_Sysref_Config` and `XRFdc_GetMTSEnable` as defined symbols `[xrfdc]`. That is because PYNQ compiles every `.c` file of the embeddedsw `rfdc` driver into it (`[PYNQ] sdbuild/packages/xrfdc/package/Makefile`, `ESW_SRC := ... drivers/$(lib)/src/*.c`).
- **Upstream PYNQ `master` still has no MTS in the wrapper** (`[PYNQ]`, grep of `__init__.py` and `xrfdc_functions.c`).
- **AMD's MTS overlay patches it in** with `[MTS] boards/patches/xrfdc_mts.patch`:
  - It adds the structs `XRFdc_MTS_DTC_Settings` and `XRFdc_MultiConverter_Sync_Config` and the two prototypes to `xrfdc_functions.c`.
  - It adds `mts_adc_config` / `mts_dac_config` (initialized with `XRFdc_MultiConverter_Init(cfg, NULL, NULL)`) and `mts_adc()` / `mts_dac()` (`XRFdc_MultiConverter_Sync(instance, 0|1, cfg)`) to `RFdc`.
  - `[MTS] install.sh` rebuilds the package (`pre.sh`, `qemu.sh`) and needs internet and `sudo`.

### 3.1 The driver API (embeddedsw `xilinx-v2020.2`, the one in our `libxrfdc.so`)

- **`XRFdc_MultiConverter_Init(cfg, PLL_Codes, T1_Codes)`**, three arguments in 2020.2 `[esw] xrfdc_mts.c:1097`. It sets these defaults:
  - `RefTile=0`, `Target_Latency=-1`, `Marker_Delay=15`, `SysRef_Enable=1`.
  - Newer embeddedsw added a fourth argument, `RefTile` ("MTS now scans reference tile first. This has required a change to the prototype of XRFdc_MultiConverter_Init", 03/08/21, in `xrfdc.h` at `master`).
- **`XRFdc_MultiConverter_Sync(inst, Type, cfg)`**, with Type 0 = ADC and 1 = DAC `[esw] xrfdc_mts.c:1151–1258`:
  1. Checks that each tile in `cfg->Tiles` is started and MTS-enabled.
  2. Disables the FIFOs and enables SysRef Rx.
  3. Runs a DTC scan per tile, including a "DTC Scan PLL" when a Gen 3 tile uses its internal PLL (`:1222–1233`). Per-tile PLLs like ours are therefore handled.
  4. Enables the FIFOs, reads the markers and calls `XRFdc_MTS_Latency`. That function computes each tile's latency in units of `Count_W = Read_Words * Interpolation` and adds delay to match the target.
  5. If `Target_Latency < 0`, the reference tile's own latency is the target.
- **Constant total latency across runs.** PG269 says that for applications "where the total latency must be constant, the `Target_Latency` setting in the API can be enabled". To find it, run once with `-1`; "the returned latency value (plus some margin) must be set as the target value for future runs" `[PG269] Deterministic-Multi-Tile-Synchronization-API-Use`.

### 3.2 Calling MTS without rebuilding xrfdc (sketch, not tested; only for an MTS-enabled bitstream)

```python
import xrfdc
xrfdc._ffi.cdef("""
typedef struct { u32 RefTile; u32 IsPLL; int Target[4]; int Scan_Mode; int DTC_Code[4];
  int Num_Windows[4]; int Max_Gap[4]; int Min_Gap[4]; int Max_Overlap[4]; } XRFdc_MTS_DTC_Settings;
typedef struct { u32 RefTile; u32 Tiles; int Target_Latency; int Offset[4]; int Latency[4];
  int Marker_Delay; int SysRef_Enable; XRFdc_MTS_DTC_Settings DTC_Set_PLL;
  XRFdc_MTS_DTC_Settings DTC_Set_T1; } XRFdc_MultiConverter_Sync_Config;
void XRFdc_MultiConverter_Init(XRFdc_MultiConverter_Sync_Config *, int *, int *);
u32  XRFdc_MultiConverter_Sync(XRFdc *, u32, XRFdc_MultiConverter_Sync_Config *);
""")
cfg = xrfdc._ffi.new("XRFdc_MultiConverter_Sync_Config*")
xrfdc._lib.XRFdc_MultiConverter_Init(cfg, xrfdc._ffi.NULL, xrfdc._ffi.NULL)
cfg.RefTile = 2; cfg.Tiles = 0b0101; cfg.SysRef_Enable = 1; cfg.Target_Latency = -1
status = xrfdc._lib.XRFdc_MultiConverter_Sync(soc.rf._instance, 1, cfg)   # 1 = DAC
print(status, list(cfg.Latency), list(cfg.Offset))
```

Notes on the sketch:

- The struct layout is copied from `[MTS] boards/patches/xrfdc_mts.patch`.
- Whether `xrfdc._lib` (opened with `_ffi.dlopen`) picks up declarations added after loading has not been checked. If it does not, `dlopen` the `.so` again.
- QICK's vendored `ipq_pynq_utils` does the same thing for the ZCU208 (`ZCU208Board.perform_mts`, `[lib] ipq_pynq_utils/ipq_pynq_utils/boards.py:410–437`). Its header `data/xrfdc_cdefs.h` declares the **four**-argument `Init` of newer embeddedsw. Against our 2020.2 library the extra argument is ignored, and `RefTile` must then be set by hand **(inference from the two prototypes)**.

---

## 4. QICK and MTS

- **0.2.442, installed and on GitHub `main`: no MTS in `QickSoc`.**
  - `qick.py` never calls an MTS function. It only programs the clock chips and checks PLL lock (`[lib] qick.py:1199–1310`).
  - The one MTS helper is the ZCU208/CLK104-specific `ZCU208Board.perform_mts` in the vendored `ipq_pynq_utils` (`[lib] .../boards.py:172–201, 410`). `QickSoc` does not use it. Its docstring states the same three requirements: "MTS synchronization must have been enabled in the IP configurator and the PL SYSREF line must have been connected to the Dataconverter IP".
- **Firmware: no QICK project enables MTS** (4x2, 2x4, ZCU111, ZCU216; grep for `Multi_Tile_Sync {true}` and `user_sysref` over `[gh] firmware/projects/`).
- **What the maintainers said** in [#277] (RFSoC 4x2, DAC_A/DAC_B for an I/Q mixer, comment by meeg 2024-08-13):
  - "Phase alignment across DAC tiles is possible in principle, using what Xilinx calls multi-tile sync, but we have not implemented this in QICK."
  - In the 2023 4x2 firmware the two generators had separate 614.4 MHz fabric clocks, so a pulse-to-pulse CDC jitter added to the tile skew. Our firmware no longer has that problem: both generators and the tProc timing clock are on `clk_dac2` (§1).
  - The maintainers planned to fix the 4x2 PL clocking "when we redo all of the standard firmwares". [#277] was closed in March 2025 without MTS.
- **Newer than 0.2.442:** none exists; `main` and PyPI are at 0.2.442 (`[gh] qick_lib/qick/VERSION`, checked 2026-11-04).
  - PR #342 (merged 2025-06-17), "changes to improve multiboard sync", only makes the tProc core and timing clocks integer-related. It has no MTS.
  - The tutorial `docs/source/tutorials/14_XCOM_Network_Synchronization.ipynb` (added 2026-10-30) lists "Multi-tile sync (MTS) calibration" as a step and calls `soc.init_tile_sync()`, `soc.verify_clock_tree()` and `soc.sync_tiles()`. **Those methods do not exist in `qick_lib` on `main`** (grep). They have the same names as AMD's RFSoC-MTS overlay methods, and the notebook needs a special XCOM firmware.
  - The non-`main` branches `2.0.0-dev`, `sho` and `merge-hrl-main` contain no MTS changes (GitHub compare API; we scanned the diff patches for MTS keywords).
- **Not checked:** the QICK forum and GitHub Discussions, and any XCOM or MTS firmware outside the public repo.

---

## 5. Alternatives to MTS

1. **Read the tiles' latency at boot: not possible without MTS.**
   - The driver gets the per-tile latency from the MTS markers. It needs an MTS-enabled tile (`XRFDC_MTS_DLY_ALIGNER0 != 0`, `[esw] xrfdc_mts.c:1178`) and SYSREF capture.
   - There is **no `XRFdc_GetFIFOLatency`** in the 2020.2 driver or in `xrfdc.h` at `master` (grep). `FabRdVldWords` / `FabWrVldWords` are FIFO widths, not latencies.
   - We found no other register in PG269 that reports the latency without MTS. We did not search the register map exhaustively.
2. **Deterministic-latency settings: none for this case.** PG269 says the latency within a tile is fixed, and across tiles must be measured and corrected with SYSREF `[PG269] Detailed-Description`. No FIFO or datapath mode removes the cross-tile ambiguity without SYSREF.
3. **Measure each boot, then compensate.** This is software only. The pieces exist:
   - **RF-DC coarse delay.**
     - Gen 3 tiles accept "digital control values 0 to 40, each step equal to T1" `[PG269] Coarse-Delay`, and the driver enforces `XRFDC_CRSE_DLY_MAX_EXT 0x28` `[esw] xrfdc.h`.
     - The PYNQ wrapper exposes it per block: `soc.rf.dac_tiles[0].blocks[0].CoarseDelaySettings = {'CoarseDelay': n, 'EventSource': xrfdc.EVNT_SRC_IMMEDIATE}` `[xrfdc]` `_block_props`. With `EVNT_SRC_IMMEDIATE` the driver triggers the update itself `[esw] xrfdc.c` `XRFdc_SetCoarseDelaySettings`.
     - At 9830.4 Msps one step is 0.102 ns and the range is 4.07 ns. Delaying DAC_B by 15 or 32 steps would have cancelled both values we measured (1.55 ns, 3.30 ns) to within ±51 ps **(inference)**.
     - **Not verified:** that coarse delay acts in our DAC datapath mode (`datapath: 4` in `[fix]`, interpolation 1).
   - **I/Q phase.**
     - A delay τ between I and Q is a phase 2π·f_IF·τ. At 1 GHz IF, the 1.75 ns step is 630°, i.e. 270° modulo 360° **(arithmetic)**.
     - Our TX I/Q calibration stores a single phase (`iq_phase_deg`, `src/qick_interface/iq.py:25–33`). It is right only at the IF and on the boot where it was measured.
     - The RX path already models the delay (`rx_delay_ps`, `iq.py:56–59`). The TX path can get the same term from a calibration at two or more IFs.
   - **How to measure τ per boot:**
     - the bench scope (`board/scope.py`) on DAC_A and DAC_B;
     - the I/Q calibration at two IFs;
     - or a combiner of DAC_A + DAC_B into one ADC.
4. **Re-randomize until a known state (inference, not recommended).** Restart DAC tile 0 (`dac_tiles[0].StartUp()` / `Reset()`) and measure until the skew lands on a chosen value. QICK warns that `Reset()` resets RF-DC registers such as the sample rate (`[lib] qick.py:855`), and any tile restart redoes the FIFO alignment. It is fragile, and it still needs the measurement.

---

## 6. Recommendation for this project

**What is affected (inference).**

- Only the **transmon I/Q output** (DAC_A = I, DAC_B = Q) is hurt materially. A per-boot I↔Q delay makes the sideband and carrier calibration go stale at every boot.
- For the fluxonium wiring (DAC_A control, DAC_B readout), ≈1.7 ns of jitter between the qubit pulse and the readout is negligible next to µs pulses.
- The ADC_D + ADC_C return path is in one tile and should be immune (§1).

| Path | What it takes | Effort | Risk |
|---|---|---|---|
| **A. Calibrate per boot (software only), recommended now** | Add a TX delay term τ to the I/Q calibration (calibrate at ≥ 2 IFs) and re-run the I/Q calibration after every power cycle or service restart. Optionally apply `CoarseDelaySettings` on DAC tile 0 to also line up the envelopes. Test-first at the I/Q calibration test point. | Small: `iq.py`, the calibration measurement, the profile field, and one RF-DC call in `board/` | Low. It needs a calibration step after each boot (the user must remember it, or the app must detect a new boot, e.g. from the service start time). Coarse delay in our datapath mode is unverified: check it on the bench first |
| **B. Firmware with DAC MTS** | Rebuild our custom firmware (we would need its Vivado project; the standard QICK 4x2 project is at `[gh] firmware/projects/qick_tprocv2_4x2_standard`, Vivado 2023.1): <br>1. enable `DAC0/DAC2_Multi_Tile_Sync`; <br>2. add `PL_CLK` (AN11, 122.88 MHz) → MMCM → the 614.4 MHz DAC/tProc-timing clock instead of `clk_dac2`; <br>3. add `PL_SYSREF` (AP18) → synchronizer → `user_sysref_dac`; <br>4. add the input-delay constraints, following `[MTS] boards/RFSoC4x2/build_mts`; <br>5. refresh `tests/fixtures/soccfg_rfsoc4x2.json`; <br>6. in `board/qick_service.py`, call `XRFdc_MultiConverter_Sync` (DAC, `Tiles=0b0101`, `RefTile=2`, fixed `Target_Latency`) after `QickSoc()` (sketch in §3.2). LMK/LMX files unchanged. | Large: days to weeks of FPGA work, outside QICK's supported path | Medium–high: <br>• timing closure at 614.4 MHz with a new MMCM clock tree; <br>• QICK's clock-group and timing assumptions; <br>• MTS must be re-run after every tile restart (`[PG269] Synchronization-Steps`); <br>• SYSREF capture margins. <br>Gain: the same DAC_A↔DAC_B latency every boot ("guarantees alignment between tiles in each group", `[PG269] Deterministic-...-API-Use`) |
| **C. Firmware with DAC and ADC MTS** | Same as B, plus the ADC tiles. Also needs a PL clock that is an integer submultiple of 552.96 MHz as well (e.g. LMK OUT8 → 61.44 MHz; a new TICS file) | Larger than B | As B, plus a custom LMK configuration |
| D. Wait for QICK | No MTS is planned publicly; [#277] only promised to fix the PL CDC structure | none | It may never arrive |

**Suggested order.**

1. Do **A** now. It also fixes the phase drift of the I/Q calibration with IF, which exists even on a single boot.
2. Measure on the bench how many skew states occur, and whether a service restart alone changes them.
3. Bring **B** to the user as a design decision only if a per-boot calibration proves too slow or unreliable. It changes the firmware, so CLAUDE.md requires asking.

## Not verified

- That the skew changes on a firmware reload without a power cycle (expected from [#277] and the tile start-up sequence, not measured on our board).
- That coarse delay acts in DAC datapath mode 4 with interpolation 1, and that one step is exactly one 9.83 GS/s sample on our tiles.
- The meaning of `C_Sysref_Source=1` in `[fwHWH]`.
- Whether the two LMX2594 outputs feeding DAC tiles 228 and 230 keep a fixed phase without the LMX SYNC (OUT5) being enabled.
- That Vivado can rebuild the custom firmware (we do not have its project files in this repo).
- PG269 was read online with WebFetch (summarized quotes), not from a PDF of a pinned version.
