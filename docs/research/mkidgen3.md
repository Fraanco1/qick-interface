# MKIDGen3 (Mazin Lab): RFSoC MKID readout — research notes

Researched on 2026-11-03 against primary sources only: the MazinLab GitHub repos (checked out at the commits
below), the gen3 papers, and the Real Digital product page. Repo links are pinned to these commits:

| Repo | Commit used | Short alias below |
|---|---|---|
| MazinLab/MKIDGen3 (`main`) | `ed70dda` (2025-10-30) | `G3` = `https://github.com/MazinLab/MKIDGen3/blob/ed70ddaec33473544fa54b74a759767ece746c4b` |
| MazinLab/gen3-vivado-top (`main`) | `3f7ef94` (2026-06-12) | `FW` = `https://github.com/MazinLab/gen3-vivado-top/blob/3f7ef941a1d5d96fd9bb40992106ba1739ce3c4b` |
| MazinLab/gen3_rpc (`main`) | `e8986d7` (2025-05-30) | `RPC` = `https://github.com/MazinLab/gen3_rpc/blob/e8986d74c518ee5c6cc3ab757a45194f927bde23` |
| MazinLab/RFSoC_OPFB (`master`) | `8ab3d5b` (2024-08-23) | `OPFB` = `https://github.com/MazinLab/RFSoC_OPFB/blob/8ab3d5b6136490ebdf3b24953889decdfc3f40ae` |

Papers:
- **[P1]** J. P. Smith, J. I. Bailey III, A. Cuda, N. Zobrist, B. A. Mazin, "MKIDGen3: Energy-Resolving,
  Single-Photon-Counting MKID Readout on an RFSoC", arXiv:2406.09764 (2024), Rev. Sci. Instrum.,
  doi:10.1063/5.0225768. https://arxiv.org/abs/2406.09764
- **[P2]** J. P. Smith, J. I. Bailey III, B. A. Mazin, "Highly-Multiplexed Superconducting Detector Readout:
  Approachable High-Speed FPGA Design", FCCM 2022 poster, arXiv:2203.16520 (ZCU111 era). https://arxiv.org/abs/2203.16520
- **[P3]** The OPFB paper on IEEE Xplore: https://ieeexplore.ieee.org/document/9336352 (linked from `OPFB/README.md#L19`).

To expand an alias, replace it with its URL. For example, `G3/README.md#L3` is
`https://github.com/MazinLab/MKIDGen3/blob/ed70dda.../README.md#L3`.

The prior RedPitaya implementation (`github.com/Fraanco1/mkid_readout`) could not be read. The anonymous
clone asked for credentials, so the repo is private or the URL is wrong. It was not used here.

---

## TL;DR

- MKIDGen3 targets the **RFSoC 4x2 (XCZU48DR)**, the same board we have. The earlier ZCU111 work is legacy.
  It reads out **2048 resonator channels at 1 MHz** each over **4.096 GHz of complex baseband (±2.048 GHz)**,
  using **2 DACs + 2 ADCs at 4.096 GSPS** feeding an external **I/Q mixer IF board**. That is the same
  topology we plan to build (`G3/README.md#L3`, `G3/mkidgen3/system_parameters.py#L23-L35`, [P1] §IV.1).
- **No prebuilt full gen3 bitstream is published.** There are no `.bit`/`.hwh` files in MKIDGen3 or
  gen3-vivado-top, and neither has GitHub releases. The server's default path `/home/xilinx/gen3_top_final.bit`
  is a lab-local file (`G3/mkidgen3/server/fpga_objects.py#L23`). We would have to build it with Vivado
  2022.1 (`FW/README.md#L12-L16`). The only prebuilt 4x2 bitstream is the **OPFB-only loopback demo** in
  RFSoC_OPFB (`OPFB/bit/opfb_streaming.bit`).
- They require **PYNQ ≥ 3.0.1**, plus a patched `xrfdc` for MTS, a modified device tree (reserved PS-DDR and
  PL-DDR4 windows) and a patched `pynq` (`G3/pyproject.toml#L39-L44`, `G3/docs/pynq_deviations.md`). Our
  image is "2022_10_22", which is probably PYNQ 3.0.0 (not verified) and stock. **Expect to reflash or patch it.**
- Status: "in high flux… APIs, resource calculations, and drivers are only partially done"
  (`G3/README.md#L5`). Development is active on side branches through 2026-09: MKIDGen3 `D2-15`/`iq`
  (IQTransform, triggerv2, fftgain) and gen3-vivado-top `vivado2025.1`. A Rust/Cap'n Proto RPC layer
  (gen3_rpc) seems to be taking over from the Python/ZMQ feedline server.
- The design is **photon-event oriented**: it outputs a phase-pulse trigger with timestamps. Continuous
  multi-channel I/Q comes from **bounded captures into 4 GiB of PL DDR4**, not from a network stream.

---

## 1. Repositories, status, licenses

| Repo | Role | License | Activity (newest branch commit) |
|---|---|---|---|
| [MKIDGen3](https://github.com/MazinLab/MKIDGen3) | Python package `mkidgen3` (PYNQ drivers, DAC comb, feedline server/client, notebooks). Pulls in firmware, blocks and IF board as submodules | GPL-3.0 (`G3/LICENSE`) | `main` 2025-10-30; `D2-15` 2026-08-27 |
| [gen3-vivado-top](https://github.com/MazinLab/gen3-vivado-top) | Vivado top-level block designs (`bd/*.tcl`), constraints, Makefile build, DESIGN.md | none declared (GitHub API `license: null`) | `main` 2026-06-12; `vivado2025.1` 2026-09-26 |
| [mkidgen3_blocks](https://github.com/MazinLab/mkidgen3_blocks) | Vitis HLS cores: dac-replay, adc-to-opfb, opfb-fir-cfg, opfb-fir-to-fft, ssrfft_16x4096, pkg-fft-output, opfb-bin-to-res, resonator-dds, photon-trigger, iq-capture, gen3-timekeeper, pps-synchronizer… (each also has its own repo) | none declared | 2025-03-17 |
| [RFSoC_OPFB](https://github.com/MazinLab/RFSoC_OPFB) | Standalone 4096-ch 2× oversampled OPFB demo on the RFSoC4x2, **ships a bitstream** | GPL-3.0 | 2024-08-23 |
| [gen3_rpc](https://github.com/MazinLab/gen3_rpc) | Rust Cap'n Proto RPC (`Gen3Board`: DDC, DacTable, Capture, IfBoard, DspScale). `pyo3server` wraps PYNQ MMIO from Rust | MIT OR Apache-2.0 (`RPC/gen3_rpc/Cargo.toml`) | `gobbler` 2026-06-11; release v0.1.0 (2025-04) |
| [readout-gui](https://github.com/MazinLab/readout-gui) | Rust egui GUI (native/WASM). Release binaries are named `guilo-*` | MIT/Apache-2.0 | 2025-12 |
| [IF-Board](https://github.com/MazinLab/IF-Board) | Arduino firmware for the IF board (TRF3765 LO, PE43705 attenuators) | none declared | 2021-12 |
| MKIDReadout / MKIDFirmware | Gen2 (ROACH2/CASPER), legacy | GPL | 2018–2024 |

Sources: GitHub API `users/MazinLab/repos` (license and push dates), `git ls-remote`/shallow fetch of all
branches, and `G3/.gitmodules` (submodules `firmware`→gen3-vivado-top, `blocks`→mkidgen3_blocks,
`arduino/ifduino`→IF-Board).

Notes:
- The README calls the whole project "in high flux… Liberal communication with the authors is both welcomed
  and advised" (`G3/README.md#L5`, `FW/README.md#L3`).
- `G3/docs/design_description.md#L3` says its own design description "does not accurately reflect the
  current state". Treat the docs as orientation only.
- Some files are stale. `FW/DESIGN.md#L50-L51` still says "I to DAC10 / Q to DAC11" (ZCU111 naming). The
  actual 4x2 block design enables DAC tile 0 slice 0 and DAC tile 2 slice 0 (see §3).
- The mkidgen3_blocks and gen3-vivado-top repos declare no license, so reuse and redistribution of the HDL is
  legally unclear. Ask the authors before redistributing.

## 2. Supported boards and PYNQ version

- **RFSoC4x2 is the primary target.**
  - "The readout is under active development around the RFSoC4x2 Academic Eval board" (`G3/README.md#L3`).
  - The Vivado project is created for part `xczu48dr-ffvg1517-2-e`, board `realdigital.org:rfsoc4x2:part0:1.0`
    (`FW/scripts/tcl/create_top_level_prj.tcl#L13,L18`). Board files are vendored in `FW/rfsoc4x2_board_files/`.
  - [P1] states the system "leverages the Xilinx RFSoC4x2" with 2048 channels per board.
- **ZCU111 (XCZU28DR)** was the earlier platform ([P2]; old test designs use `xczu28dr` / `zcu111`, e.g.
  `FW/tests/opfb_dac_loopback/write_prj.tcl#L12-L16`; RFSoC_OPFB keeps a `zcu111_legacy` branch,
  `OPFB/README.md#L19`). It is not maintained for the current design.
- **ZCU216/ZCU208**: no mention in either repo.
- **Our board:** Real Digital lists 4 RF-ADCs (5 GSPS) and 2 RF-DACs (9.85 GSPS) on SMA, ZU48DR, and
  "ZCU208-compatible" clocking (https://www.realdigital.org/hardware/rfsoc-4x2). Gen3 uses **both DACs and two
  of the four ADCs**, all at 4.096 GSPS ([P1] §IV.1). So gen3 and QICK cannot both drive the DACs at the same time.
- **Prebuilt bitstream:** none for the full gen3 design (see TL;DR). `OPFB/bit/opfb_streaming.{bit,hwh}` is an
  RFSoC4x2 OPFB loopback demo (DAC LUT → 2 DAC → 2 ADC → OPFB → PL-DDR4 capture) (`OPFB/README.md#L21`).
- **PYNQ version:**
  - `mkidgen3[board]` requires `pynq>=3.0.1`, `xrfdc==2.0`, `xrfclk==2.0` and Python ≥ 3.10
    (`G3/pyproject.toml#L26,L39-L44`).
  - [P1] §IV.4: "PYNQ 3.0.1 on Ubuntu 22.04", with a modified device tree and patched xrfdc. Its Table 2 lists
    Python 3.11.
  - MTS needs the Xilinx RFSoC-MTS xrfdc patch, "At present (… PYNQ 3.0.1)" (`G3/docs/mts_4x2.md#L13-L27`;
    install steps in `G3/README.md#L24-L40`).
  - Further deviations from stock PYNQ (`G3/docs/pynq_deviations.md`):
    - Device tree reserves PS-DDR `0x8_0000_0000` (size `0x40000000`) and the PL-DDR4 window
      `0x5_0000_0000` (+4 GiB) for zocl (`#L190-L239`).
    - `pynq` is patched with `set_psddr_region()` (`#L241-L376`).
    - A udev rule for `/dev/ifboard` (`#L395-L402`).
  - RFSoC_OPFB: stock PYNQ 3.0.1 works if the PL DDR4 is made reachable by `pynq.allocate`. They also publish
    a custom 4x2 SD image (Google Drive link) (`OPFB/README.md#L43`).
- **Compared with our image** (Release 2022_10_22, "PYNQ ~3.0", Python 3.10, Linux 5.15): Python 3.10 meets
  `requires-python`. If the image is PYNQ 3.0.0 it does **not** meet `pynq>=3.0.1`. In any case it lacks the
  MTS xrfdc patch, the PL-DDR4 reservation and the pynq patch. **Action:** run `pip show pynq xrfdc xrfclk` on
  the board. The practical route is a second SD card with PYNQ 3.0.1 for the 4x2 plus the gen3 patches,
  or the RFSoC_OPFB custom image as a starting point.

## 3. Signal-chain architecture (current `gen3_top`)

```
PS DDR ──AXI4──► DAC replay (2^19 complex LUT in 60–64 URAM, 7.8125 kHz grid)
                  ├─ I ─► RF-DAC (tile 0 / 228, ch0) ─┐
                  └─ Q ─► RF-DAC (tile 2 / 230, ch0) ─┴─► IF board: I/Q upmix with LO → 4–8 GHz → MKIDs
MKIDs → IF board: I/Q downmix → I,Q ─► 2 RF-ADC (tile 0 / 224) @4.096 GSPS
  → OPFB: 16 FIR banks + 4096-pt SSR FFT → 4096 bins, 1 MHz spacing, 2 MHz wide, 2 MSPS each (2× OS)
  → bin_to_res: pick any of 4096 bins for each of 2048 channels (256 groups × 8)
  → resonator DDC: per-channel NCO (fine tone), loop rotation + centering
  → low-pass FIR (20 tap, ÷2) → 2048 ch × 1 MSPS I/Q
  → CORDIC atan → phase (16 b, 1 MSPS)
  → phasematch: per-channel matched/optimal FIR (30-tap default, reloadable)
  → photon trigger (threshold + holdoff) → photon events {36b time, 12b id, 16b phase} → PS DDR
  → postage stamps (127 µs IQ windows, up to 8/16 channels)
  └ debug capture taps (ADC raw, OPFB/DDC IQ, phase) → PL DDR4 (4 GiB) via axis2mm
```

| Item | Value | Source |
|---|---|---|
| ADC/DAC rate | 4.096 GSPS, complex baseband ±2.048 GHz (DAC freq range −2.048…+2.048 GHz) | `G3/mkidgen3/system_parameters.py#L23-L27`; [P1] §IV.1 |
| Converters enabled | DAC tile 0 slice 0 and DAC tile 2 slice 0. ADC tile 0 (`vin0_01`, `vin0_23`) | `FW/bd/gen3_top.tcl#L3162,L3177,L3232,L3235,L3148`; `#L3320-L3360` |
| DAC LUT | 2^19 complex samples (2×8×2^15 shorts), 2 MiB of URAM, AXI4 read from PS DDR, 256 MHz | `FW/DESIGN.md#L37-L52`; `system_parameters.py#L22,L25` |
| DAC tone grid | 4.096e9 / 2^19 = 7.8125 kHz | `system_parameters.py#L25`; [P1] §IV.2.1 |
| Comb generation | Python, sum of tones with phase optimisation / per-tone attenuation (`daccomb`, `generate_dac_comb`, `FreqlistWaveform`) | `G3/mkidgen3/daccomb.py#L11,L69`; `G3/mkidgen3/server/waveform.py#L112-L290` |
| OPFB | 4096 channels, OS = 2 → 1 MHz spacing, 2 MHz bandwidth, 2 MSPS per bin. Runs at 512 MHz with 16 lanes | `system_parameters.py#L28,L34-L35`; `FW/DESIGN.md#L94-L106` |
| Channels | 2048 resonator channels, TDM in 256 groups of 8 | `system_parameters.py#L29-L31`; `FW/DESIGN.md#L207-L251` |
| Bin select | 96 b × 256 LUT mapping 8 channels → OPFB bin each, via AXI-Lite | `FW/DESIGN.md#L231-L251` |
| DDC | per-channel phase accumulator, 11-bit tone increment, 21-bit phase offset, quarter-wave LUT, complex multiply. `CenteringDDC` adds loop centering | `FW/DESIGN.md#L254-L286`; `G3/mkidgen3/drivers/ddc.py#L47-L221` |
| Low-pass | FIR 20 taps, decimate 2 → 1 MSPS per channel, "~3 dB flat in 500 kHz" | `FW/DESIGN.md#L257,L288-L289` |
| I/Q output rate | `LOWPASSED_IQ_SAMPLE_RATE = 1e6` per channel | `system_parameters.py#L48` |
| Phase | 4× Xilinx CORDIC (arctan), 16-bit, 15 fractional bits (scaled radians) | `FW/DESIGN.md#L291-L310`; `system_parameters.py#L42-L43` |
| Matched filter | FIR, 256-ch, per-channel reloadable coefficients. README: default build has 30 taps | `FW/DESIGN.md#L313-L317`; `FW/README.md#L20`; [P1] §IV.3.4 |
| Trigger | per-channel threshold (8-bit, ~0.02 rad), holdoff 8–254 µs | [P1] §IV.3.5 |
| Photon record | 64-bit packed: phase[15:0], id[27:16], time = bits ≥28 (36 b, 1 µs, PPS/GPS-disciplined) | `G3/mkidgen3/mkidpynq.py#L8-L33`; [P1] §IV.3.9 |
| Count-rate design point | 5000 counts/s per pixel | `system_parameters.py#L49`; [P1] §III.4.3 |
| Capture | PL DDR4 4 GiB, >16 GiB/s sustained, taps ADC / IQ / phase | `FW/DESIGN.md#L322`; `mkidpynq.py#L4-L5` |
| Clocks | 512 MHz pipeline, 256 MHz DAC replay, LMK04828/LMX2594 profiles `4.096GSPS_MTS_dualloop` (4x2 only) | `FW/DESIGN.md#L18-L23`; `G3/mkidgen3/drivers/rfdcclock.py#L29-L63` |
| Resources | 68 % CLB, 80 % URAM, 11 % DSP of ZU48DR | [P1] Table 2 |
| Measured | images ≤ −30 dB (RFDC loopback), ~−25 dB (IF loopback). Phase noise floor ~−80 dBc/Hz | [P1] §V |

Which front-panel SMA ports (ADC A–D, DAC A/B) the tiles correspond to must be checked against the RFSoC4x2
schematic or reference manual. The gen3 repo does not name them.

Not on `main` yet: `FW/bd/gen3_top_mts.tcl` enables all four ADC tiles at 4.096 GSPS. `G3/docs/mts_4x2.md#L3`
synchronises ADC tiles 224/226 and DAC tiles 228/230 via MTS. Per [P1] §IV.1.2, MTS took image tones from
≈−20 dB to ≈−40 dB.

## 4. Driving it from Python

### 4.1 On-board (PYNQ) API, the "notebook" level
- Load the overlay with `pynq.Overlay(bitfile)`, then `mkidgen3.quirks.Overlay(ol).post_configure()` and
  `ol.rfdc.enable_mts(...)` / `ol.rfdc.set_gain(...)`. Clocks are set via
  `mkidgen3.drivers.rfdcclock.configure(...)` (`G3/mkidgen3/server/fpga_objects.py#L54-L60,L143-L150`).
- PYNQ IP drivers bind automatically to the custom IP VLNVs:

| Overlay path | Driver | Key calls |
|---|---|---|
| `ol.dac_table` | `DACTableURAM` / `DACTableAXIM` | `.replay(iq)`, `.configure(waveform=...)`, `.stop()`, `.quiet()` (`G3/mkidgen3/drivers/dactable.py#L9-L190`) |
| `ol.photon_pipe.reschan.bin_to_res` | `BinToResIP` | `.bins = array(2048)`, `.configure(bins=...)` (`drivers/bintores.py#L6-L75`) |
| `ol.photon_pipe.reschan.ddccontrol_0` | `ThreepartDDC` | `.configure(tones, phase_offset, loop_center, ...)` (`drivers/ddc.py#L216-L221`) |
| `ol.photon_pipe.phasematch` | phasematch | `.configure(...)` (`drivers/phasematch.py`) |
| `ol.trigger_system.trigger_1` / `photon_maxi_0` / `postage_*` | `PhotonTrigger`, MAXI | thresholds and holdoffs, photon buffers (`drivers/trigger.py`) |
| `ol.capture` | `CaptureHierarchy` | `.capture_adc(n)`, `.capture_iq(n, groups, tap_location='ddciq')`, `.capture_phase(n, ...)`, `.keep_channels(tap, ch)`, `.looping_capture(...)` (marked "untested") (`drivers/capture.py#L153-L537`) |
| `ol.rfdc` | patched RFDC | `enable_mts`, `set_gain`. `set_qmc` is a **no-op** ("Pretending to set QMC, not currently supported") (`drivers/rfdc.py#L106,L234-L251`) |
| IF board | `mkidgen3.equipment_drivers.ifboard.IFBoard` (USB serial, 115200) | `.set_lo(freq)`, `.set_attens(output_attens, input_attens)`, `.lo_freq` (`G3/mkidgen3/equipment_drivers/ifboard.py#L27,L196-L237,L285`) |

- Convenience helpers in `G3/mkidgen3/overlay_helpers.py`:
  - `set_waveform(freqs, amplitudes|attenuations, phases)` builds the comb and replays it (`#L12-L67`).
  - `set_channels(freqs)` maps up to 2048 frequencies to OPFB bins (`#L74-L85`).
  - `capture_opfb(ol, n)` (`#L99`).
- Frequency helpers: `mkidgen3.opfb.opfb_bin_number`, `quantize_frequencies` (`G3/mkidgen3/opfb.py#L4,L48`).
- Example notebooks in `G3/notebooks/`:
  - `RFDC_Loopback_Capture_Spectrum.ipynb`, `IQ_Capture_Loopback.ipynb`, `OPFB_Test.ipynb`, `reschan_test.ipynb`
  - `PhotonPipeFullVerification.ipynb`, `Streaming_Photon_Trigger_Test.ipynb`, `loop_readout.ipynb`
  - `PL_DDS_*` (from the `jpsmith/pl_sweep` branch)
  - `MTSVerification.ipynb`, `FCCM22_Demo.ipynb`
  - `G3_Paper_Data_Figures*.ipynb`
  - Several still reference lab-local `.bit` paths.

### 4.2 Client/server (current Python implementation)
- **Feedline Readout Server (FRS)** runs on the board: `python -m mkidgen3.server.feedline_server`
  (`G3/mkidgen3/server/feedline_server.py#L53,L323-L340`).
  - ZMQ **REQ/REP command port 8888**, capture-data **PUB port 8889**, status **PUB port 8890**. XSUB/XPUB
    proxies forward the data and status streams (`#L326-L361`).
  - CLI options: `--bitstream` (default `/home/xilinx/gen3_top_final.bit`), `--clock`, `--if /dev/ifboard`.
- **Model** (`G3/docs/frs.md#L1-L120`):
  - The client builds a `FeedlineConfig` (bitstream, RFDC clocking, IF, waveform, channels, DDC, filter, trigger)
    and a `CaptureRequest(n, tap ∈ {adc, iq, phase, photon, postage}, config)`.
  - It wraps the request in a `CaptureJob(cr, cmd_url, data_url, status_url)` and calls `.submit()`, then
    `.data()`.
  - The server applies the config (reloading the bitstream if needed), runs one tap thread per capture type,
    and publishes data tagged with the capture id.
  - Photon, postage and one of ADC/IQ/phase captures can run at the same time.
  - Sources: `G3/mkidgen3/server/captures.py#L31-L75,L901`; `feedline_config.py#L434-L658`;
    example in `G3/tests/feedline_client_test.py`.
- **Data transport:**
  - Captures go to PL DDR4, are copied to PS buffers, then serialized over ZMQ. `sccommon` extras pull in
    `pyzmq` and `blosc2` compression (`G3/pyproject.toml#L50-L55`). Clients save to HDF5/npy
    (`client` extras, `#L62-L67`).
  - Photons go via the `photon_maxi` double buffer in PS DDR into a ZMQ sender thread
    (`fpga_objects.py#L325-L405`).
  - [P1] §IV.4: data goes to network storage over 1 GbE, after a patched Ethernet BSP restored near line rate.
    Table 2 gives a data rate of "80 MiB/s + 16 GiB/s" (photons/network + PL capture).
- **Direction of travel:** `gen3_rpc` defines a Cap'n Proto RPC with these interfaces:
  - `Gen3Board.getDdc / getDacTable / getCapture / getDspScale / getIfBoard`
  - `Ddc.allocateChannel(config)` → `DdcChannel.setSource(bin) / setDdcFreq / setRotation / setCenter`
  - `Capture.capture(tap, length)` → `Snap`
  - Source: `RPC/gen3_rpc/schema/gen3rpc.capnp`.
  - The server is Rust (`pyo3server` calls the PYNQ MMIO through PyO3, `RPC/pyo3server/src/main.rs`).
    The client side is Rust (`readout-gui`).
  - There is no Python client for gen3_rpc in the repo. That is an inference from the workspace members
    `gen3_rpc, mock, pyo3server, reading_rainbow` (`RPC/Cargo.toml`).

## 5. External RF hardware: their assumptions vs ours

**Theirs** ([P1] §IV.1.1; `IF-Board/`; `G3/mkidgen3/equipment_drivers/ifboard.py`):
- A custom IF board shifts the ±2 GHz complex baseband to and from **4–8 GHz**.
- It has complex (I/Q) mixers and a **TRF3765** PLL LO. The driver programs the TRF at `freq/2`, so the LO is
  doubled on the board (`ifboard.py#L196-L201`). [P1] gives no numeric LO tuning range.
- Two programmable attenuators per direction, 0.25 dB steps, max 31.75 dB each (`ifboard.py#L17-L19`;
  [P1] says 0–63 dB in total).
- About 88 dB of receive gain, anti-alias filters swapped to 2 GHz / 3.8 GHz parts ([P1] §IV.1.1).
- Arduino Nano over USB serial (`/dev/ifboard`).
- [P1] §VI: the hand-reworked board "is not suitable for instrument deployment". IQ (QMC) calibration is
  impractical beyond ~400 MHz of instantaneous bandwidth.
- Gen3 RFSoC direct RF sampling in 4–8 GHz is "not yet possible".

**Ours**: external LO up to 7 GHz plus generic I/Q mixers, two DACs into the I/Q modulator, I/Q demodulator into
two ADCs. This is **topologically identical** to gen3. Differences and things to plan for:
- **No `IFBoard`.** We must stub or replace `mkidgen3.equipment_drivers.ifboard` (FRS defaults to
  `/dev/ifboard`, `feedline_server.py#L336`). Our LO and attenuator control would live in our app or in a shim
  class with the same `set_lo / set_attens / lo_freq` interface.
- **Band.** With a ~5 GHz array spanning tens to hundreds of MHz and an LO ≤ 7 GHz, place the LO a few hundred MHz
  away from the band so the tones sit away from DC and LO leakage. Only a tiny part of the ±2 GHz span is used,
  so most OPFB bins and channels stay idle.
- **I/Q imbalance.** Generic mixers will produce images (a tone at +f leaks to −f). Gen3's `set_qmc` is a no-op,
  so correction would be ours: pre-distort the DAC comb, or calibrate per tone in software. Keep tones off
  mirror frequencies (±f symmetric about the LO).
- **Analog conditioning.** We need anti-alias / reconstruction low-pass filters (< ~2 GHz) on the I and Q
  lines, receive gain (they use ~88 dB including cryogenic HEMT/LNA), and step attenuators. ADC full scale is
  ~1 dBm and DAC max ~1 dBm (`system_parameters.py#L4,L12`).
- **Clocking.** Gen3 programs the onboard LMK04828/LMX2594 for 4.096 GSPS (`rfdcclock.py`). If our external
  LO must be phase-coherent with the RFSoC, a shared 10 MHz reference is needed. Gen3 does not assume one;
  the IF board's TRF has its own reference.

## 6. Effort and risk to run on our RFSoC 4x2; coexistence with QICK

**Risks and effort, roughly highest first:**
1. **Build the bitstream ourselves.**
   - Needs Vivado/Vitis HLS 2022.1 (`FW/README.md#L14`) plus submodule HLS blocks.
   - The SSR FFT is an exported System Generator/Model Composer IP (`FW/DESIGN.md#L182`; RFSoC_OPFB needs
     SysGen 2019.2, `OPFB/README.md#L32`).
   - Amaranth RTL (`rtl/mkidaranth`) built through `pdm` (`FW/Makefile#L33-L40`).
   - The design is large (80 % URAM) with timing-sensitive 512 MHz paths. The README has FIR "speed fix"
     TCL snippets (`FW/README.md#L37-L51`).
   - **Days to weeks**, and a Vivado license is required for ZU48DR. ZU48DR is not in the free WebPACK device
     list, so a licensed Vivado edition is needed (to be verified against AMD licensing).
   - `main` vs active branches may not match the Python `main`. Pin a matched pair (e.g. firmware `main`
     2026-06 plus MKIDGen3 `main` 2025-10) and expect to ask the authors.
2. **Software and image.**
   - Needs PYNQ 3.0.1, the RFSoC-MTS xrfdc patch, xrfclk 2.0, a PL-DDR4/PS-DDR reserved-memory device tree
     and the `pynq` patch (§2).
   - The device-tree change applies at boot and reserves memory for every overlay, which affects QICK too.
   - Best done on a **separate SD card**.
3. **Data model mismatch.**
   - Gen3 streams **photon events**. Continuous I/Q of N channels is a bounded capture into PL DDR4, copied to
     PS and sent over the network.
   - 16 ch × 1 MSPS × 4 B ≈ 64 MB/s, near the 1 GbE limit after overhead. Continuous streaming is not what the
     server does; `looping_capture` is "untested".
   - For imaging with 16 MKIDs, use either (a) photon counts or phase from the trigger path, or (b) repeated
     bounded IQ captures.
4. **Missing IF board.** Shim the driver (§5).
5. **Maturity.** "APIs… only partially done", design doc out of date, active rewrites (triggerv2, IQTransform,
   gen3_rpc). There is no versioned release of the firmware or Python.

**Low-risk first step:** flash a separate SD card, run `RFSoC_OPFB` with its prebuilt
`opfb_streaming.bit` and `opfb_demo.ipynb` in DAC→ADC loopback, then through our I/Q mixers. This validates
the 4.096 GSPS clocking, the two-DAC/two-ADC I/Q path and the OPFB on our exact board before investing in the
full gen3 build (`OPFB/README.md#L21,L43-L46`).

**Coexistence with QICK:**
- PYNQ allows only one full overlay in the PL at a time. Loading gen3 replaces QICK and vice versa, and each
  reprograms the LMK/LMX clocks.
- The gen3 FRS itself reloads the bitstream on `reset()` / config change (`fpga_objects.py#L71-L75,L143`).
- Both use the same two DACs, so they cannot run at the same time.
- Feasible pattern: one SD image that satisfies both, then on the board a "mode switch" that:
  1. stops the QICK Pyro4 server (it holds `QickSoc`);
  2. starts the gen3 FRS (or our own PYNQ service) with the gen3 bitstream;
  3. reverses the two steps to switch back.
- Unknowns:
  - Whether QICK's 4x2 overlay tolerates the gen3 reserved-memory device tree and the patched xrfdc 2.0 needs
    a test. QICK pins its own xrfdc usage; not verified here.
  - Reflashing between experiments is the safe fallback.

---

## Implications for our app

1. **Treat MKIDGen3 as a separate "readout mode" with its own board-side server.** The FastAPI app should talk
   to a gen3 backend through an adapter interface, e.g. `ReadoutBackend` with `set_tones`,
   `assign_channels`, `capture_iq`, `capture_phase` and `stream_photons`, implemented once for QICK
   (Pyro4) and once for gen3. Do not mix the two in one code path.
2. **Gen3 transport is ZMQ, not Pyro4.**
   - Short term: run their FRS and use `mkidgen3[client]` (`CaptureJob`/`FeedlineConfig`) from the lab PC.
     Ports 8888/8889/8890; install with `pip install -e '.[client]'`, Python ≥ 3.10.
   - Alternative: write a thin Pyro4 or FastAPI service on the board that imports the gen3 PYNQ drivers
     directly (`ol.dac_table`, `bin_to_res`, `ddccontrol_0`, `ol.capture`). Keep an eye on gen3_rpc
     (Cap'n Proto, Rust), which looks like their future control plane but has no Python client yet.
3. **Map our 16-MKID workflow onto gen3 primitives:**
   - Frequency sweep / VNA: comb on the 7.8125 kHz DAC grid via `FreqlistWaveform` / `set_waveform`. The
     LO is set in our app, since we have no IF board.
   - Channel assignment: `bin_to_res.bins` = `opfb_bin_number(f_tone − f_LO)` plus DDC tone offsets.
   - Loop rotation/centering through `ThreepartDDC.configure`.
   - Data at 1 MSPS per channel, by I/Q group of 8 channels: 16 resonators = 2 groups.
4. **Plan the image pipeline around bounded captures or photon events, not continuous I/Q streaming.** Budget
   ≤ ~64 MB/s for 16 ch continuous over 1 GbE and do decimation or averaging on the board.
5. **Own the IF layer.** Implement LO, attenuator and IQ-imbalance calibration in our app (or an `IFBoard`
   shim), because gen3's QMC hook is a no-op and our mixers are generic.
6. **Board/image management becomes a feature.** The app needs to know which overlay/image is active and
   expose a guarded mode switch (stop QICK server → load gen3 → start FRS). Plan for a second SD card with
   PYNQ 3.0.1 plus the gen3 patches.
7. **Before writing code:**
   - Confirm our PYNQ/xrfdc versions on the board.
   - Run the RFSoC_OPFB prebuilt loopback demo.
   - Contact the authors (Smith, Cuda, Bailey; `G3/pyproject.toml` maintainers) for a known-good bitstream +
     Python commit pair. This could save weeks of Vivado work.
