# Converter power scales on the RFSoC 4x2

Primary-source notes on the absolute power scale of our board's DACs and ADCs as QICK drives them. The goal is two formulas for the app: QICK gain → dBm at the DAC's SMA, and readout |I + jQ| → dBm at the ADC's SMA. Read in November 2026. Every claim cites a source. Statements marked **(inference)** are our own reasoning or arithmetic, not something a source says. **(unverified)** marks a number we could not confirm in a primary source.

**Bench facts this has to explain.**

- Loopback, short cable DAC_B → ADC_D, const pulse, gain 0.5, 550 MHz: |I + jQ| ≈ 900–1000 from `acquire()` and ≈ 926–1000 per sample from `acquire_decimated()`. So 20·log10(|IQ|/gain) ≈ 65–66 dB.
- Oscilloscope (1 MΩ input, unterminated) on DAC_A at gain 0.5, 50–100 MHz: about 220–260 mV peak.

**Source tags**

| Tag | Source |
|---|---|
| `[fix]` | `tests/fixtures/soccfg_rfsoc4x2.json` (the firmware config the PC sees) |
| `[fwHWH]` | `~/jupyter_notebooks/qick_firmware/qick_4x2.hwh` on the board: our firmware, parsed read-only |
| `[lib] file:line` | Installed QICK 0.2.442, `.venv/lib/python3.12/site-packages/qick/<file>` |
| `[gh] path` | https://github.com/openquantumhardware/qick at `main`, commit `80753a9` (2026-10-30), still version 0.2.442. Firmware IP sources under `firmware/ip/` |
| `[RD-RM]` | Real Digital, *RFSoC 4x2 Reference Manual*, https://www.realdigital.org/downloads/d6a7543b5033e5dadde272a48bcb5090.pdf (28 pp., PDF dated 2025-09-11, downloaded 2026-11-04). "Sampling Circuits" (p. 6), Appendix C "Major BOM Components" (p. 26), Appendix D (p. 27) and E (p. 28) |
| `[DS926-ADC]` | AMD DS926, Table 117 "RF-ADC Electrical Characteristics for ZU4xDR Devices", as reprinted in `[RD-RM]` Appendix D |
| `[DS926-DAC]` | AMD DS926, Table 132 "RF-DAC Electrical Characteristics for ZU4xDR Devices", as reprinted in `[RD-RM]` Appendix E |
| `[PG269] section` | AMD PG269 v2.6, *RF Data Converter LogiCORE IP Product Guide*, https://docs.amd.com/r/en-US/pg269-rf-data-converter/<section> (read through web search and WebFetch excerpts) |
| `[MABA]` | MACOM, *MABA-011118 1:2 Transmission Line Balun, 10–10,000 MHz*, Rev. V5, https://cdn.macom.com/datasheets/MABA-011118.pdf (5 pp., downloaded 2026-11-04). Electrical table (p. 2) and typical curves (p. 3) |
| `[PG269-2.4] p.` | AMD/Xilinx PG269 v2.4 (2020-11-30), full PDF, https://www.xilinx.com/content/dam/xilinx/support/documents/ip_documentation/usp_rf_data_converter/v2_4/pg269-rf-data-converter.pdf (downloaded 2026-11-04) |
| `[DS926]` | AMD DS926 v1.14 (2024-12-23), section "RF-DAC Electrical Characteristics", https://docs.amd.com/r/en-US/ds926-zynq-ultrascale-plus-rfsoc/RF-DAC-Electrical-Characteristics (read through WebFetch) |
| `[PG149] p.` | AMD/Xilinx PG149 *FIR Compiler v7.2* (2022-10-26), https://www.xilinx.com/support/documents/ip_documentation/fir_compiler/v7_2/pg149-fir-compiler.pdf (downloaded 2026-11-04) |
| `[rfdc] file` | Xilinx embeddedsw RFdc driver, `XilinxProcessorIPLib/drivers/rfdc/src/`, commit `97f2baf` (master, 2026-11-04) |
| `[RD-SCH] p.` | Real Digital, *RFSoC 4X2 Gen3* schematic, Rev. V3I1, dated 2024-05-23, 46 sheets, https://www.realdigital.org/downloads/1859152f898cfb0d53c4792e23e91b35.pdf ("Schematic" on the board's Resources tab, downloaded 2026-11-04). Sheet 27 "RF ADC", sheet 28 "RF DAC" |
| `[RD-BOM]` | Real Digital, RFSoC 4x2 BOM, https://www.realdigital.org/downloads/23339e93fd1c8d059cd81122ab75e840.xlsx (downloaded 2026-11-04) |

---

## Short answer

- **DAC:** the firmware leaves the DACs in the fixed **20 mA** mode (no VOP), and QICK never changes the current. Gain 1.0 on a const pulse gives a full-scale sine, about **+1 dBm** at the RFSoC pins (DS926's typical for the 20 mA mode). After the balun that is **≈ −1.0 dBm at the SMA below 1 GHz**, then add the sinc roll-off (−2.5 dB at 4 GHz). Uncertainty ±1.5 dB. The scope reading (−1.7 to −3.2 dBm) is 0.6–2 dB lower.
- **ADC:** full scale is **+1 dBm** (1 V<sub>ppd</sub>) at the pins with the attenuator (DSA) at 0 dB, which is its start-up value in our firmware. The balun loses ~2 dB below 1 GHz and ~1 dB at 2 GHz, so full scale is **≈ +3 dBm at the SMA** below 1 GHz. No amplifier or attenuator is fitted; the only other parts are 100 nF series capacitors.
- **Readout scale:** a full-scale tone gives **|I + jQ| ≈ 4225** in `acquire()` and per sample in `acquire_decimated()`. That is 32768 × ¼ (real-to-complex mixing at half amplitude) × 0.516 (the decimation FIR's DC gain, 270382 / 2^19). `acquire()` returns the per-sample **mean**, not the sum.
- **Loopback check:** the datasheets predict 20·log10(|IQ|/gain) ≈ **68.5 dB**; the bench gives 65–66. The 2.5–3 dB gap is within the stacked "typical" tolerances, but the absolute scale should come from a signal-analyzer measurement (§5).

---

## 1. DAC: from QICK gain to dBm at the SMA

### 1.1 Gain → DAC code (`axis_signal_gen_v6`)

- **Gain register.** For a `const` pulse QICK writes `gainreg = trunc(gain · maxv · maxv_scale)` `[lib] asm_v2.py:1800-1802`. Our generators have `maxv = 32766` and `maxv_scale = 1.0` `[fix]` (`MAXV = 2**15-2` `[lib] drivers/generator.py:13`). Gain 1.0 is code 32766.
- **Const path.** `outsel="dds"` (register value 1 `[lib] asm_v2.py:1640`) feeds the DDS output straight into the gain multiplier. The rounded output is bits `[30 -: 16]` of `sample × gain`, i.e. `× gain/2^15` `[gh] firmware/ip/axis_signal_gen_v6/src/signal_gen.v` ("Product with Gain", "Rounding"). The DDS is 16 bits wide with `Amplitude_Mode = Full_Range` (`.../dds_compiler_0/dds_compiler_0.xci`), so its peak is ≈ 2^15. **Gain 1.0 gives a sine of peak ≈ 32765 codes: the DAC's full scale (inference).**
- **The factor 2 for arbitrary envelopes.** On the `product` path (envelope × DDS, the default for arb pulses), the complex product is first cut to bits `[31:16]`, i.e. `÷ 2^16`, before the gain stage `[gh] signal_gen.v`. An envelope at `maxv` with gain 1.0 therefore peaks at **half** of full scale, 6.02 dB below a const pulse at the same gain. QICK compensates for this on `flat_top` pulses: "the flat segment is played at half gain, to match the ramps" `[lib] asm_v2.py:1791`. **For arb/Gaussian/DRAG pulses: amplitude = ½ · gain · (envelope / maxv) of full scale (inference from the HDL).**
- **Linearity.** The output follows the gain to 0.1 dB on the bench (−6.02 dB at half, −19.93 dB at a tenth; `docs/s21.md` §4).

### 1.2 RF-DAC full-scale output (ZU48DR, Gen 3)

- **Our firmware:** `C_DAC_VOP_Mode = 0`, `C_DAC_Output_Current = 0`, `C_DAC0_VOP = C_DAC2_VOP = 20.0`, `C_DAC_Invsinc_Ctrl00/20 = false`, `C_DAC_Decoder_Mode00/20 = 0`, `C_DACn_Link_Coupling = 0` (AC), `C_DAC_Mixer_Mode = 2` with coarse mixer, NCO 0 `[fwHWH]`. QICK reads the first two as `dac_power: '20mA'` `[lib] qick.py:136-139`, `[fix]`. So: **20 mA**, no inverse-sinc filter, the default (NRZ) decoder, no NCO mixing.
- **QICK does not change the current.** `set_dac_curr` (which calls `XRFdc_SetDACVOP`) refuses to run unless the firmware was built in VOP mode `[lib] qick.py:764-790`. Nothing in QICK calls it on its own, and our app does not call it (grep of `src/`, `board/`, `scripts/`).
- **PG269:** the output current "is configurable, with an option of operating in either 20 mA or 32 mA modes. In the 20 mA mode, set the DAC_AVTT to 2.5V and in the 32 mA mode, set it to 3.0V" `[PG269-2.4] p. 100`. In Gen 3, "a backwards compatibility mode is provided… the VOP feature is no longer available, the RF-DAC works as in Gen 1 and Gen 2, outputting 20 mA with a 2.5V power supply and 32 mA with a 3.0V power supply on DAC_AVTT" `[PG269-2.4] p. 102`. VOP allows 2250–40500 µA in steps of 43.75 µA and needs DAC_AVTT = 3.0 V `[PG269] VOP-Details-Gen-3/DFE`, `XRFdc_SetDACVOP-Gen-3/DFE`.
- **The board's DAC_AVTT is 2.5 V:** "VDAC_AVTT (2V5 @ 2A)" in the power-supply diagram `[RD-RM]` p. 11. That matches the 20 mA mode.
- **Transfer function:** "I<sub>VOUTP</sub> = (BinDataIn / 2<sup>N</sup>) × I<sub>OUTFS</sub>, I<sub>VOUTN</sub> = I<sub>OUTFS</sub> − I<sub>VOUTP</sub>" `[PG269-2.4] p. 100`. So the differential current swings ±I<sub>OUTFS</sub> at full scale.
- **DS926, ZU4xDR (Gen 3) table:** "Maximum output power": −18.5 dBm (min) to **6.5 dBm (max)**, "V<sub>DAC_AVTT</sub> = 3.0V, 100Ω termination, signal frequency <200 MHz". "Output current range": 2.25–40.5 mA, AC coupling. Analog bandwidth 6 GHz (−3 dB). Return loss −12 dB to 4 GHz `[DS926-DAC]`. This table has no 20 mA row.
- **DS926, 20 mA mode:** the ZU2xDR and ZU39DR (Gen 1/2) tables list "Maximum Output Power, 20 mA mode, V<sub>DAC_AVTT</sub> = 2.5V, 100Ω termination: typ **+1 dBm**" and "32 mA mode, V<sub>DAC_AVTT</sub> = 3.0V: typ +5 dBm" (ZU39DR: 4.5 dBm) `[DS926]` Tables 1–2. With PG269's statement that Gen 3 in this mode "works as in Gen 1 and Gen 2", **P<sub>FS</sub>(20 mA) = +1 dBm typ** into 100 Ω differential. **Verified** in a primary source, with one step of inference: the number is printed for Gen 1/2 parts, not for the ZU48DR.
  - Cross-checks (inference). Power goes as current squared. 20·log10(32/20) = 4.1 dB, and +1 → +5 dBm is 4 dB. Scaling the Gen 3 VOP maximum gives 6.5 + 20·log10(20/40.5) = +0.4 dBm, 0.6 dB lower; DS926 gives that maximum at 3.0 V and as a "max", so the two do not have to agree exactly.
  - From first principles: each output leg has 50 Ω on-die termination in parallel with half of the 100 Ω load, i.e. 25 Ω per leg. That gives V<sub>diff</sub> = I<sub>FS</sub> × 25 Ω = 0.5 V peak, and 0.5²/(2·100 Ω) = +1.0 dBm. This agrees with DS926's +1 dBm.
  - DS926 gives this as a typical, with no min/max: keep **±1 dB**.
- **Sinc roll-off (inference, standard NRZ).** 20·log10|sinc(f/f<sub>s</sub>)| at f<sub>s</sub> = 9830.4 MSa/s `[fix]`. Inverse sinc is off `[fwHWH]`.

| f (MHz) | 100 | 550 | 1000 | 2000 | 3000 | 4000 | 4500 | 4915 |
|---|---|---|---|---|---|---|---|---|
| sinc (dB) | 0.00 | −0.04 | −0.15 | −0.60 | −1.37 | −2.51 | −3.23 | −3.92 |

### 1.3 RFSoC 4x2 output network

- "The ADC input and DAC output signals pass through decoupling capacitors and a balun, with no active components in the signal chain. A MABA-011118 balun rated at 10 MHz - 10GHz is connected between each SMA and ADC" `[RD-RM]` p. 6. The BOM lists T1–T6 as MACOM MABA-011118 (six baluns: four ADCs and two DACs) `[RD-RM]` App. C. No amplifier, attenuator or filter is listed.
- **MABA-011118** `[MABA]`: 1:2 impedance ratio (50 Ω ↔ 100 Ω balanced), 10–10,000 MHz. Balanced insertion loss, typ / max:

| Band (MHz) | 10–1000 | 1000–4000 | 4000–7000 |
|---|---|---|---|
| Insertion loss (dB) | 2.0 / 2.4 | 1.2 / 1.7 | 1.9 / 2.3 |

  - Read off the typical curve (p. 3; ±0.2 dB reading error): ≈2.1 dB near 0.1 GHz, 1.5 dB at 1 GHz, 1.0 dB at 2 GHz, 0.8 dB at 3 GHz, 1.0 dB at 4.5 GHz, 1.5 dB at 6 GHz.
  - Amplitude balance 0.3 dB typ (10–2000 MHz). Return loss 9–15 dB.
  - Below 10 MHz the balun is out of spec; the hardware setup already notes the roll-off.
- **Coupling capacitors: 100 nF, verified** `[RD-SCH]` sheets 27–28, `[RD-BOM]`. Every path has three, and nothing else but 0 Ω links:
  - **DAC** (sheet 28; DAC_B = bank 228 VOUT0, DAC_A = bank 230 VOUT0): pin → 100 nF in each leg (C321/C323, C324/C326) → 0 Ω (R304/R307, R309/R312) → balun T5/T6 → 100 nF single-ended (C322, C325) → SMA J20/J21.
  - **ADC** (sheet 27; ADC_D = bank 224 VIN_I01, ADC_C = 224 I23, ADC_B = 226 I01, ADC_A = 226 I23): SMA → 100 nF single-ended (C301, C306, C311, C314) → balun T1–T4 → 0 Ω per leg → 100 nF per leg (C302/C303, …) → pin.
  - The 866 Ω shunt resistors on the differential side (R288/R289, R305/R306, …) are marked not fitted.
  - Parts: single-ended caps Murata GRM155R71E104KE14J (0402, X7R); differential caps GRM033C71C104KE14D (0201, X7S) `[RD-BOM]`.
  - **Loss (inference):** the high-pass corner is 1/(2π · 50 Ω · 100 nF) ≈ 32 kHz (the two 100 nF in series into 100 Ω give the same). Their reactance at 10 MHz is 0.16 Ω, so the capacitance itself is negligible in our band. Their parasitic inductance above a few GHz is not in any document we read **(unverified; it is part of what the analyzer measurement in §5 captures)**.

### 1.4 Expected power at the DAC SMA

**(inference)**

  P<sub>DAC</sub>(gain, f) ≈ +1.0 dBm − L<sub>balun</sub>(f) + 20·log10|sinc(f/9830.4 MHz)| + 20·log10(gain) [const pulse]

| f | 100 MHz | 550 MHz | 1 GHz | 2 GHz | 3 GHz | 4 GHz | 4.5 GHz |
|---|---|---|---|---|---|---|---|
| Gain 1.0 → dBm at SMA | −1.1 | −1.0 | −0.7 | −0.6 | −1.2 | −2.4 | −3.2 |

**Uncertainty ±1.5 dB:**

- DS926 values are typical;
- the +1 dBm is printed for Gen 1/2 parts in the 20 mA mode, and applies to our Gen 3 part through PG269's backwards-compatibility statement;
- the balun curve read by eye;
- above ~4 GHz, the DAC's own analog roll-off (6 GHz −3 dB) and the 12 dB return loss add more, perhaps another 1 dB **(unverified)**.

**Scope cross-check (inference).**

- The DAC and balun present ≈ 50 Ω, and an unterminated 1 MΩ input reads about twice the voltage a 50 Ω load would see.
- So 220–260 mV peak becomes 110–130 mV into 50 Ω: −9.2 to −7.7 dBm at gain 0.5, or **−3.2 to −1.7 dBm at gain 1**.
- The prediction at 75 MHz is −1.1 dBm, 0.6 dB above the top of that range. The source match (balun return loss 9–15 dB) and the scope's accuracy can explain the spread.

---

## 2. ADC: full scale and input network

- **DS926:** resolution 14 bits; dual-tile channels up to 5 GS/s. "Full-scale input": **1 V<sub>PPD</sub> = 1 dBm**, "Input 100Ω on-die termination when DSA attenuation = 0 dB". Footnote 3: full scale is "the approximate input power required to drive the ADC to full scale output for a 5 MHz input tone… can vary from dual to quad ADCs… also subject to variation across process, voltage, and temperature… The typical average value is provided."
  - Maximum allowed input: 14.6 dBm with DSA ≥ 15 dB.
  - DSA range 0–27 dB in 1 dB steps.
  - Analog bandwidth 6 GHz (−3 dB, referenced to 100 MHz).
  - Return loss −12 dB to 4 GHz. `[DS926-ADC]`
- **Our firmware.** ADC_D and ADC_C are tile 0, blocks 00/02: dual (`hs_adc: true`), 4423.68 MSa/s, RF-DC decimation 1, real data (`C_ADC_Data_Type = 0`), coarse mixer in real-to-real mode, NCO 0, dither on, AC coupled, first Nyquist zone `[fix]`, `[fwHWH]`. Nothing in the RF-DC changes the amplitude **(inference)**.
- **DSA.** The firmware has no DSA parameter apart from `C_ADC_DSA_RTS = false` `[fwHWH]`. QICK only touches the DSA through `set_adc_attenuator` `[lib] qick.py:712-730, 1633-1654`, which our app never calls.
  - **Start-up value: 0 dB, verified.** PG269 v2.6, "DSA Operation Details": "When the IP starts up initially (or after s_axi_aresetn is driven Low), the attenuation is dependent on this input [dsa_code]… When the real-time DSA signal interface is not enabled the default attenuation is 0 dB" `[PG269] DSA-Operation-Details-Gen-3/DFE`. Our firmware has the real-time ports off (`C_ADC_DSA_RTS = false` `[fwHWH]`). So the DSA is **0 dB after every bitstream load**.
  - The same page says `XRFdc_Reset` and `XRFdc_StartUp` do not change the attenuation. The driver writes the DSA register only in `XRFdc_SetDSA` and has no start-up write `[rfdc] xrfdc_ap.c:2955-3016` (grep of all driver sources). So a `set_adc_attenuator` call from any client survives until the next overlay load.
  - Register encoding, for reading it back: attenuation = 27 − code × 1 dB on production silicon (`XRFDC_MAX_ATTEN` = 27, `XRFDC_STEP_ATTEN` = 1; 11 dB / 0.5 dB on ES1) `[rfdc] xrfdc.h:1271-1273`, `[PG269-2.4] p. 54`.
  - It can be read without changing anything: on the board, with QICK loaded, `soc.rf.get_adc_attenuator('00')` `[lib] qick.py:692-710`. We did not run it (read-only session).
- **Input network:** the same MABA-011118 balun and 100 nF capacitors (§1.3), no active parts `[RD-RM]`, `[RD-SCH]` sheet 27. Full scale at the SMA is therefore ≈ 1 dBm + L<sub>balun</sub>(f) **(inference)**: ≈ +3.0 dBm at 100–550 MHz, +2.5 dBm at 1 GHz, ≈ +2.0 dBm at 2 GHz.
- **Frequency response to 2.2 GHz (inference).**
  - The balun gets *better* from 0.1 to 2 GHz (≈2.1 → 1.0 dB).
  - The ADC's 6 GHz bandwidth suggests a droop of only a few tenths of a dB at 2 GHz **(unverified: DS926 gives only the −3 dB point)**.
  - Expect a net rise of ~+1 dB from 100 MHz to 2 GHz, with ±0.5 dB ripple from the 12–15 dB return losses.
- **ADC code scale: verified.** "Gen 3: 14-bit RF-ADC resolution, with 16-bit digital signal processing datapath; each 14-bit data stream is MSB-aligned to 16-bit samples at the output of the RF-ADC core before passing to the DDC block" `[PG269-2.4] p. 16`. The AXI-Stream carries "16-bit little endian words" `[PG269-2.4] p. 82`. With decimation 1 and the coarse mixer in real-to-real mode, nothing rescales the words, so full scale is ±32768 codes (14-bit steps of 4) **(inference for the last step)**.

---

## 3. QICK readout scaling (`axis_dyn_readout_v1` + `axis_avg_buffer`)

The data path, from `[gh] firmware/ip/axis_dyn_readout_v1/src/` (`readout_top.v`, `down_conversion_fir.v`, `down_conversion.v`, `fir.coe`, `fir_compiler_0/fir_compiler_0.xci`):

1. **Mixing** (`down_conversion.v`, 8 samples per 552.96 MHz clock). Each 16-bit ADC sample is multiplied by the 16-bit DDS cos and sin. The DDS is `Full_Range` with peak ≈ 2^15. The result is rounded (`+ 2^15`) and bits `[31:16]` are kept, i.e. `÷ 2^16`. So the complex sample is ≈ ½ · x[n] · e<sup>−jωn</sup>. For x = A·cos(ωn + θ), the DC term is **(A/4)·e<sup>jθ</sup>** **(inference)**. With `outsel="product"` (the default) this is the path used `[lib] asm_v1.py:187`.
2. **FIR + decimation by 8** (`fir_compiler_0`):
   - 120 integer taps (`fir.coe`), 16-bit data and coefficients, 2 paths (I, Q), 256-bit input, 32-bit output;
   - accumulator 35 bits, output 16 bits, `Symmetric_Rounding_to_Zero`.
   - **The output is the accumulator ÷ 2^19, rounded: verified.** PG149: the full-precision width is A<sub>w</sub> = D<sub>w</sub> + B, with B = ceil(log2 Σ|a<sub>n</sub>|) computed from the actual coefficients (Eq. 3-3, 3-4); in the rounding modes "m [is] the truncated LSBs (that is, the difference between the accumulator width and the output width)", which are removed after the rounding constant is added `[PG149] p. 64-66`. Here Σ|a<sub>n</sub>| = 435414 (log2 = 18.73), so B = 19 and A<sub>w</sub> = 16 + 19 = 35, matching the .xci's `C_ACCUM_OP_PATH_WIDTHS = 35,35` and `C_OUTPUT_WIDTH = 16`, with `Quantization = Integer_Coefficients`, no fractional bits `[gh] .../fir_compiler_0/fir_compiler_0.xci`. So m = 19.
   - "Symmetric Rounding to Zero" rounds to the nearest output LSB (ties toward zero), so it changes the result by at most ½ LSB `[PG149] p. 66`.
   - The tap sum is 270382, so the **DC gain is 270382 / 2^19 = 0.5157**.
   - The passband computed from the taps: −0.5 dB at ±50 MHz, −3 dB at ±200 MHz, −66 dB at ±276 MHz. A tone on the readout frequency lands at DC, so only the 0.516 applies.
   - The 2f term falls in the stopband unless 2f aliases near DC (f near f<sub>s</sub>/2 = 2211.84 MHz) **(inference)**.
3. **Accumulation** (`axis_avg_buffer/src/avg.sv`): `acc_i <= acc_i + din_ii`, full precision, one decimated sample per 552.96 MHz cycle. No shift.
4. **Software:**
   - `acquire()` → `_average_buf` divides by the readout `length` (in decimated samples) and subtracts `iq_offset` (0 here) `[lib] qick_asm.py:2041-2062`, `[fix]`. **`acquire()` returns the per-sample mean, so it matches `acquire_decimated()`**, which returns the raw decimated samples (as float, offset removed) `[lib] qick_asm.py:2238-2256`. The bench agrees: 900–1000 vs 926–1000.

**Scale constant (inference).**

  |IQ| = A × ¼ × 0.5157 = **0.1289 · A** [ADC codes, 16-bit scale]

  K<sub>FS</sub> = 32768 × 0.1289 = **4225 counts** (72.5 dB) for a full-scale input tone.

**Prediction for 0 dBm at the ADC SMA, f ≤ 1 GHz (inference).** The pins see 0 − 2.0 = −2.0 dBm, which is −3.0 dBFS. That gives |IQ| ≈ 4225 × 10<sup>−3.0/20</sup> ≈ **3000 counts** (±1.5 dB, i.e. 2500–3550).

**The loopback (DAC_B → ADC_D, 550 MHz, gain 0.5) (inference):**

| Step | Datasheet chain | Using the scope for the DAC |
|---|---|---|
| DAC at SMA, gain 0.5 | −1.0 − 6.0 = −7.0 dBm | −2.4 − 6.0 = −8.4 dBm (scope mid-range) |
| Short cable | −0.1 dB | −0.1 dB |
| ADC balun, 550 MHz | −1.9 dB | −1.9 dB |
| At the ADC pins | −9.0 dBm = −10.0 dBFS | −10.4 dBm = −11.4 dBFS |
| Predicted \|IQ\| | ≈ 1340 | ≈ 1140 |
| Predicted 20·log10(\|IQ\|/gain) | 68.5 dB | 67.2 dB |
| **Measured** | **926–1000 (65.3–66.0 dB)** | |

- The datasheet chain is **2.5–3 dB too optimistic**. If we trust the scope for the DAC, the ADC's full scale at the SMA comes out at ≈ +4.3 dBm instead of the predicted +2.9 dBm.
- Each of these alone could explain the difference:
  - DS926's ADC full scale is a "typical average value" that "can vary";
  - the 20 mA DAC power is a typical, printed for Gen 1/2 parts;
  - the balun is ±0.4 dB from part to part.
- The DSA is not a likely cause: it starts at 0 dB with our firmware (§2), and only an explicit `set_adc_attenuator` call since the last overlay load could change it. Reading it once (§5) rules this out.
- The shape of the chain is right; the absolute offset needs a measurement **(inference)**.

---

## 4. Recommended formulas for the app

**(inference)** Both formulas are in dBm at the SMA connector, 50 Ω.

**DAC, const pulse:**

  P<sub>DAC</sub>(gain, f) = P<sub>DAC,0</sub> + 20·log10(gain) + 20·log10|sinc(f / 9830.4 MHz)| − ΔL<sub>DAC</sub>(f)

- P<sub>DAC,0</sub> = **−1.0 dBm** (datasheet) or **−2.4 dBm** (scope). Use −1.7 dBm ± 1.5 dB until measured.
- ΔL<sub>DAC</sub>(f) = the balun's loss relative to 550 MHz: ≈ +0.2 dB at 100 MHz, −0.4 at 1 GHz, −0.9 at 2 GHz, −1.1 at 3 GHz, −0.9 at 4.5 GHz.
- **Arb/Gaussian pulses:** subtract 6.02 dB and scale by the envelope's peak/maxv.
- **Not covered:** the two DACs are on different tiles. Their absolute power can differ by a few tenths of a dB; the I/Q calibration's gain ratio already measures this.

**ADC:**

  P<sub>ADC</sub>(|IQ|, f) = 20·log10(|IQ|) − 72.5 + P<sub>FS,ADC</sub>(f)

- |IQ| is from `acquire()` or per sample from `acquire_decimated()`, at the readout frequency.
- P<sub>FS,ADC</sub>(f) = full scale at the SMA ≈ **+3.0 dBm** at 100–550 MHz (datasheet), +2.5 dBm at 1 GHz, +2.0 dBm at 2 GHz. The loopback suggests about 1.4 dB higher. **±2 dB** until measured.
- Valid for an on-frequency tone (window ≥ a few hundred ns), first Nyquist zone, DSA unchanged, input well below full scale.

**Consistency check the app can keep (inference).** The loopback gain G<sub>LB</sub> = 20·log10(|IQ|/gain) = 72.5 + P<sub>DAC,0</sub> − cable − P<sub>FS,ADC</sub>. With the datasheet values this is 68.5 dB; the bench gives 65–66. Once either side is measured, the bench G<sub>LB</sub> fixes the other.

---

## 5. What a signal analyzer should replace

1. **P<sub>DAC,0</sub>(f) for each DAC (A and B):** CW tone, const, gain 0.5 and 1.0, 50 MHz to 4.9 GHz, into a 50 Ω analyzer. This replaces DS926's typical (printed for Gen 1/2 parts), the balun curve, the capacitors' parasitics and the sinc model with one table per port. Also keep the scope reading in mind: it is 1 MΩ and depends on the source match.
2. **P<sub>FS,ADC</sub>(f) for each ADC (D, C, B):** inject a known tone, from the analyzer's source or a power-metered generator, at about −10 dBm, 50 MHz to 2.2 GHz, and record |IQ|. Then G<sub>LB</sub> on the bench checks the pair.
3. **The DSA value on each ADC:** it starts at 0 dB (§2), but a `set_adc_attenuator` call from any client persists until the next overlay load. Read it once (`soc.rf.get_adc_attenuator('00')`, `'02'`, `'20'`) to confirm 0 dB, and preferably set it explicitly at start-up so no earlier call can shift the scale. (That needs a decision from the user and a change in the board service.)
4. **Repeatability:** the same check after a power cycle. The DAC power should not depend on the boot. The tile-to-tile delay does change (see [dac-tile-sync.md](dac-tile-sync.md)), but that is a delay, not an amplitude.

Items checked against a primary source (November 2026):

- **ADC 16-bit MSB alignment: verified** (`[PG269-2.4] p. 16`, §2).
- **FIR Compiler output = accumulator ÷ 2^19, rounded: verified** (`[PG149] p. 64-66` with the QICK .xci, §3).
- **DS926 20 mA output power: verified as +1 dBm typ**, from the Gen 1/2 tables plus PG269's Gen 3 backwards-compatibility statement (`[DS926]`, `[PG269-2.4] p. 102`, §1.2). This moved P<sub>FS</sub> from +0.4 to +1.0 dBm. No ZU4xDR-specific 20 mA figure exists in DS926 **(still unverified for the ZU48DR itself)**.
- **Coupling capacitors: verified, 100 nF** (`[RD-SCH]` sheets 27–28, `[RD-BOM]`, §1.3). Their parasitics at GHz frequencies remain **unverified**.
- **DSA start-up value: verified, 0 dB** with the real-time ports off (`[PG269] DSA-Operation-Details-Gen-3/DFE`, §2). The value on our running board has not been read.
