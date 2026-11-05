# Qubit pulse shapes: flat, Gaussian or flat-top?

Why our Rabi amplitude sweep plays a Gaussian while the Rabi length sweep and Two-tone play flat pulses, what the sources do, and what QICK 0.2.442 lets us sweep. Read in November 2026. Papers were read in full from the arXiv PDFs with `pdftotext`; the QICK notebooks were downloaded from GitHub `main` on 2026-11-04.

**Source tags**

| Tag | Source |
|---|---|
| `[lib] file:line` | Installed QICK 0.2.442, `.venv/lib/python3.12/site-packages/qick/<file>` |
| `[soccfg]` | `tests/fixtures/soccfg_rfsoc4x2.json` (our firmware's config) |
| `[demo06]` | https://github.com/openquantumhardware/qick/blob/main/qick_demos/06_qubit_demos.ipynb (tProc v1), cell numbers |
| `[tut02]`, `[tut03]`, `[tut06]` | https://github.com/openquantumhardware/qick/blob/main/docs/source/tutorials/02_Parameter_Sweeps.ipynb, `03_Advanced_Timing.ipynb`, `06_Generators_And_Readouts.ipynb` (tProc v2), cell numbers |
| `[Krantz19]` | P. Krantz et al., "A quantum engineer's guide to superconducting qubits", Appl. Phys. Rev. 6, 021318 (2019), arXiv:1904.06560 |
| `[Blais21]` | A. Blais et al., "Circuit quantum electrodynamics", RMP 93, 025005 (2021), arXiv:2005.12667 |
| `[Motzoi09]` | F. Motzoi et al., "Simple pulses for elimination of leakage in weakly nonlinear qubits", PRL 103, 110501 (2009), arXiv:0901.0534 |
| `[Lucero08]` | E. Lucero et al., "High-fidelity gates in a single Josephson qubit", PRL 100, 247001 (2008), arXiv:0802.0903 |
| `[Chen16]` | Z. Chen et al., "Measuring and suppressing quantum state leakage in a superconducting qubit", PRL 116, 020501 (2016), arXiv:1509.05470 |
| `[Somoroff23]` | A. Somoroff et al., "Millisecond coherence in a superconducting qubit", PRL 130, 267001 (2023), arXiv:2103.08578 |
| `[Bao22]` | F. Bao et al., "Fluxonium: an alternative qubit platform for high-fidelity operations", PRL 129, 010502 (2022), arXiv:2111.13504 |
| `[Manucharyan09]`, `[Schuster05]`, `[Nguyen19]` | As in `two-tone.md` |
| `[app]` | Our code under `src/qick_interface/` |

Statements marked **(inference)** are our own reasoning. Statements marked **(computed)** come from a short numpy script (Fourier transforms of the sampled envelopes at 9830.4 Msps, and a three-level rotating-frame simulation with no decoherence and an ideal line). Neither is a source.

---

## Short answer: the three tentative claims

| Claim | Verdict |
|---|---|
| (a) QICK sweeps a const length in the tProc, but a Gaussian's length is fixed by its stored envelope. A σ sweep needs one envelope per point (~6.7 µs of envelope memory per generator) or one program per point. | **Holds.** `length` is a sweepable parameter of `const` and `flat_top`, but `arb` has no `length` at all; its length is the envelope's (§1.1). Envelope memory is 65536 samples = 4096 cycles = **6.667 µs per generator** [soccfg]. One correction: even with every envelope stored, the sweep API cannot step through them, because `envelope` is a name, not a numeric parameter. So in practice a σ sweep means one program per point (§1.2). |
| (b) Two-tone uses a long saturation pulse whose spectral width (~1/length) is below the qubit linewidth. | **The practice holds, the reason does not.** Every source we read uses a flat (or CW) probe (§2.1). But 1/T is *not* generally below the linewidth: a 10 µs flat pulse has an 89 kHz Fourier width, wider than the natural line of any qubit with T2 ≳ 4 µs **(computed)**. The real reasons are below (§2.2). For a long pulse (T ≫ T1, T2) the qubit sits in steady state and the edges don't matter. For a "find the line" scan the line is power-broadened far beyond 1/T. A flat pulse's sidelobes at 100 MHz-scale offsets are ≈ −70 dB **(computed)**, so they cannot fake a neighbouring transition. |
| (c) `flat_top` (Gaussian ramps + flat middle, middle sweepable) is a middle ground. | **Holds, with two costs.** The flat length is swept in the tProc ([lib] asm_v2.py:1704–1710, 1837; [tut02] cell 11 does exactly this). The costs: (1) the flat part plays at **half** amplitude, so the strongest flat_top is 6 dB below the strongest const pulse; (2) the minimum flat segment is 3 cycles, so the ramps add a fixed rotation. Our damped-cosine fit absorbs that rotation as long as it is under a quarter Rabi period (§3.3). |

---

## 1. What QICK 0.2.442 allows

### 1.1 Which pulse lengths can be swept

- **Pulse styles and parameters.** `StandardGenManager` (our `axis_signal_gen_v6`) defines `const: freq, phase, gain, length`, `arb: freq, phase, gain, envelope` and `flat_top: freq, phase, gain, length, envelope`. Only `PARAMS_NUMERIC = ['freq', 'phase', 'gain', 'length']` can be `QickParam` sweeps ([lib] asm_v2.py:1704–1710, 1695–1697).
- **const.** The length register is `us2cycles(par['length'])` ([lib] asm_v2.py:1815). `us2cycles` passes a `QickParam` through `to_int` ([lib] qick_asm.py:728–729; helpers.py:34–35), so a swept length compiles to a swept register. Our Rabi length sweep already relies on this ([app] measurements/rabi.py:60).
- **arb.** The length register is the envelope's length: `w['lenreg'] = env_length` ([lib] asm_v2.py:1817–1820). Passing `length=` to an `arb` pulse raises `"unsupported pulse parameter(s)"` ([lib] helpers.py:252–258, called at asm_v2.py:1691). **A Gaussian's length and σ cannot be swept.**
- **flat_top.** It is three waveforms: the first half of the envelope (ramp up, `product`), a flat DDS segment of length `us2cycles(par['length'])`, and the second half (ramp down) ([lib] asm_v2.py:1829–1845; docstring 1748–1756). Only the flat segment's length is swept. QICK's own tutorial sweeps it from 50 to 150 ns: `length=QickSweep1D("length_sweep", 0.05, 0.15)` on a `flat_top` ([tut02] cell 11). "`length` refers to the flat segment duration … `total_length` includes the rise and fall times" ([tut02] cell 12; [lib] asm_v2.py:461, 482–494, 2493–2495).
  - [tut02] cell 12 also says the two "can be swept independently". **That is not what the library does:** `total_length` is computed from the waveforms and is not an input parameter ([lib] asm_v2.py:461, 2493).
- **Timing after a swept pulse.** `delay_auto()` "works even if pulse lengths change (e.g., in a sweep)" ([tut03] cell 9). This is what places our readout after a swept qubit pulse ([app] measurements/rabi.py `_body`).

### 1.2 Envelope memory and σ sweeps

- **Size.** Each of our generators has `maxlen` = 65536 samples, `samps_per_clk` = 16, `f_fabric` = 614.4 MHz [soccfg]. So it holds 4096 fabric cycles = **6.667 µs** of envelope (also `qick.md` §0). `add_envelope` raises `"generator %d envelope memory holds %d samples, but the envelopes on it would need %d"` when the envelopes on one generator exceed this ([lib] qick_asm.py:1416–1417). In the transmon I/Q setup each control generator holds its own copy ([app] iq.py:101–103).
- **Granularity.** Envelope lengths are whole fabric cycles (16 samples, 1.63 ns) ([lib] qick_asm.py:1414–1415, 1497–1505). With `even_length=True` the length is rounded to an even number of cycles ([lib] qick_asm.py:1498–1499). σ itself is kept as a float in samples ([lib] qick_asm.py:1502).
- **How many Gaussians fit (inference, arithmetic).** N envelopes of 4σᵢ each need Σ 4σᵢ ≤ 6.667 µs, i.e. N · mean(σ) ≤ 1.67 µs. For example:
  - σ from 5 to 35 ns (mean 20 ns): at most ~83 points.
  - σ up to 100 ns (mean ~50 ns): at most ~33 points.
- **Selecting them in the sweep.** Even if all envelopes fit, `envelope` is a string name and not in `PARAMS_NUMERIC`. So `QickSweep1D` cannot step through envelopes, and each stored envelope needs its own `add_pulse` definition. Picking a different pulse per loop iteration would need hand-written tProc branching. **Unverified;** we found no QICK example of it. The documented route is one program per point. That is how [demo06] cell 20 does its (v1, const) Length Rabi: a Python loop that builds a program per length.
- **Our app's σ limit.** `sigma_us` allows up to 10 µs ([app] measurements/rabi.py:30). Any σ > 1.667 µs gives a 4σ envelope larger than the memory and fails at compile time with the error above **(inference from the two limits; not tried)**.

### 1.3 Length limits

- Every waveform must be ≥ 3 and < 2¹⁶ fabric cycles ([lib] asm_v2.py:1729–1734). At 614.4 MHz, 3 cycles = **4.88 ns**; the length step is 1 cycle = 1.63 ns.
- For `flat_top` the check applies to **each** segment, because each goes through `params2wave` ([lib] asm_v2.py:1835–1845):
  - each ramp half ≥ 3 cycles, so the envelope must be ≥ 6 cycles (9.8 ns);
  - the flat segment ≥ 3 cycles (4.88 ns). **A flat_top sweep cannot start at zero flat length.**
- An odd-length envelope loses its middle cycle, with a warning ([lib] asm_v2.py:1825–1828). Use `even_length=True`, as [tut02] does and as our `add_gauss_envelope` already does ([app] iq.py:103).
- A flat_top uses 3 waveform-memory entries instead of 1 ([lib] asm_v2.py:1843–1845). That is irrelevant for us (1024 entries, `qick.md` §1.4).

### 1.4 Amplitude scale of each style

This is already covered in `converter-power-scale.md` (§ "The factor 2 for arbitrary envelopes"). Cross-checked here:

- `const` at gain g plays g × full scale ([lib] asm_v2.py:1800–1802).
- `arb` at gain g peaks at g/2 × full scale. This is an inference from the HDL in `converter-power-scale.md`.
- `flat_top`: "the flat segment is played at half gain, to match the ramps" ([lib] asm_v2.py:1790–1799, 1838). So **a flat_top at gain g has its flat part at g/2 × full scale**, half of a const pulse at the same gain. Its gain is also quantized to even integers ([lib] asm_v2.py:1799).
- **Consequences (inference):**
  - Swapping const for flat_top at the same gain halves the Rabi frequency and roughly doubles the π length.
  - The strongest possible flat_top is 6 dB weaker than the strongest const pulse.
  - Our power hint subtracts 6.02 dB only for shape `"gauss"` ([app] power.py:127). A flat_top would need the same treatment.

### 1.5 QICK's Gaussian is truncated, not lifted

- `add_gauss` samples `maxv·exp(−(x−μ)²/2σ²)` over the given length, with no offset subtracted ([lib] helpers.py:81–98; qick_asm.py:1468–1511).
- At 4σ total length, each end therefore starts at e⁻² = **13.5 %** of the peak: a step.
- [Motzoi09] Eq. 5, by contrast, subtracts a constant B "to start and end at zero".
- **tProc v1 vs v2.** v1 programs divide σ by √2 (`GAUSS_BUG = True`, [lib] asm_v1.py:571; qick_asm.py:1493–1494); v2 does not (qick_asm.py:997). So [demo06]'s "σ ≈ 25 ns, ≈ 100 ns long" Gaussian (cells 6, 21) has a true σ of ≈ 17.7 ns and is ≈ 5.7 true σ long. Our v2 `length=4σ` is a true 4σ.

---

## 2. Two-tone: probe pulse shape

### 2.1 What the sources use

All of these are flat or CW. None of the sources we read uses a shaped probe.

- [Schuster05]: CW drive (`two-tone.md` §1.2).
- [Manucharyan09] SOM: "a 6 µs saturating pulse followed immediately by the 2 µs readout pulse" (`two-tone.md` §1.3).
- [demo06] cell 16 (`PulseProbeSpectroscopyProgram`): `style="const"`, `probe_length` 2 µs, gain 10/32766 (cell 17).
- [Nguyen19]: "conventional two-tone dispersive spectroscopy", with no pulse details.
- [Krantz19] has no qubit-spectroscopy section (`two-tone.md` §1.1). [Blais21] §VI.B.1 gives the steady-state lineshape (Eq. 127), which assumes a drive long enough to reach steady state.

### 2.2 Why flat is fine (and when it is not)

- **Long pulse (T ≫ T1, T2):** the qubit reaches the driven steady state, and the line is the Lorentzian of [Blais21] Eq. 127. Its width is √(1/T2² + Ω_R²T1/T2), set by T2 and the drive power, not by the pulse edges. The edges are a negligible fraction of the pulse **(inference)**.
- **Short pulse (T ≲ T2), the usual "find the line" case:** the response is coherent, and the line has a Fourier floor.
  - The power spectrum of a flat pulse has a FWHM of 0.886/T: **443 kHz at 2 µs, 89 kHz at 10 µs (computed)**. The natural FWHM is 1/(πT2) (Lorentzian of [Blais21] Eq. 127), which is 32 kHz at T2 = 10 µs.
  - So **claim (b) is backwards for modern qubits.** A 10 µs probe is wider than the natural line. The scan still works, because a search scan is run power-broadened anyway (`two-tone.md` §2.1).
- **Flat-pulse sidelobes (computed).**
  - The first sinc sidelobe is −13 dB at ≈ ±1.43/T: ±140 kHz for T = 10 µs, ±0.7 MHz for 2 µs.
  - These are visible only when the line is narrower than 1/T, i.e. weak drive and T2 > T **(inference)**. They could then be mistaken for close-lying structure, such as photon-number splitting at 2χ (`two-tone.md` §1.1).
  - A Gaussian or flat_top edge suppresses them, at the price of a wider main lobe for the same duration.
- **Far transitions (two-photon 0→2/2 at ≈ α/2 ≈ 100 MHz below f01; 1→2; fluxonium's other lines).**
  - The sinc envelope of a flat pulse is 1/(πfT)². At 100 MHz offset that is −56 dB for T = 2 µs and −70 dB for 10 µs **(computed)**.
  - So sidelobes cannot excite those lines. They show up in two-tone because the sweep tunes the probe onto them and drives them directly. With strong drive this is intended (`two-tone.md` §2.1, [SchusterPhD] §7.3).
- **The cost of shaping the probe (inference):**
  - In QICK a shaped probe is `flat_top`, which halves the maximum amplitude (§1.4). That matters most where a strong probe is needed: fluxonium's weak 0–1 matrix element near half flux, and two-photon lines (`two-tone.md` §3).
  - A longer flat pulse narrows the Fourier floor without that cost.

---

## 3. Length (time) Rabi

### 3.1 What the sources use

- **QICK:** [demo06] cell 18–20, "Length Rabi": `style="const"`, length swept 4…203 cycles in a Python loop, at gain 2000 (≈ 6 % of full scale). The notebook calls it "a preliminary measurement to prove that we see Rabi oscillations … followed up by the Amplitude Rabi experiment" (cell 18).
- **QICK v2 tutorial:** the length sweep example is a `flat_top` ([tut02] cell 11), but it is a loopback demo, not a qubit.
- **Fluxonium gates:**
  - [Somoroff23] Suppl. Note 3: X/2 and Y/2 are "Gaussian-edged square pulses with 60 ns plateau and 5 ns-width edges totaling to an 80 ns duration … No … DRAG correction or other state leakage mitigation technique was necessary thanks to the strong qubit anharmonicity."
  - [Bao22]: "simple cosine envelopes" with a fixed 10 ns duration, the angle set by amplitude. Leakage is "below 10⁻⁵ when the pulse is longer than 5 ns" (Suppl. §C, Fig. S8).
- **Reviews:**
  - [Blais21] §VII.A: "square pulses are optimal" for speed, but "high-frequency components of the square pulse can cause unwanted transitions to levels outside the two-level computational subspace. This leakage can be avoided by using smooth (e.g. Gaussian) pulses, but this leads to longer gate times."
  - [Krantz19] §IV.D.1 Eq. 94: the rotation angle is the envelope's area, Θ(t) = −ΩV₀∫₀ᵗ s(t′)dt′.
- **Not found:** no source we read runs a time Rabi by sweeping a Gaussian's σ. Swept-σ Gaussians appear only as gate-calibration data (error vs σ in [Blais21] Fig. 28; [Lucero08] Fig. 4), not as a Rabi method.

### 3.2 Leakage in a length sweep (transmon)

- In a length sweep the pulse is mostly flat. The leakage is set mainly by the steady drive strength relative to α, not by the edges **(inference)**.
- A three-level simulation (α/2π = −200 MHz, resonant π pulse, no decoherence) **(computed)**:

  | Rabi freq. | π length | Square: P₁ / P₂ at end | flat_top, σ = 5 ns edges (8σ envelope), same area: P₁ / P₂ at end |
  |---|---|---|---|
  | 5 MHz | 100 ns | 0.9995 / 3×10⁻⁴ | 0.9998 / 3×10⁻⁷ |
  | 10 MHz | 50 ns | 0.998 / 1.2×10⁻³ | 0.9994 / 1×10⁻⁶ |
  | 25 MHz | 20 ns | 0.989 / 7.5×10⁻³ | 0.997 / 1×10⁻⁵ |

- During the pulse both shapes put about the same population in |2⟩ (≈ 2Ω²/α² for weak drive). The smooth edges let it return adiabatically at the end, while a square edge leaves it behind.
- P₁ < 1 also includes the drive-induced Stark shift of the 0–1 line.
- **For a Rabi measurement whose contrast is known to ~1 %, a square pulse is fine below ~20 MHz Rabi frequency (π ≳ 25 ns). Shaping the edges pays off for faster drives (inference).** Line distortion, which [Blais21] §VII.A also blames on square pulses, is not modelled.
- **Fluxonium:** leakage is not the issue ([Somoroff23]; [Bao22]). The concerns are different **(inference)**:
  - For a qubit at tens to hundreds of MHz, a 5 ns edge is a sizeable fraction of a carrier period. The rotating-wave picture behind "area = angle" needs pulses of many carrier periods (one period is 71 ns at 14 MHz).
  - The weak matrix element needs strong drive, which favours const (full scale) over flat_top (half scale, §1.4).

### 3.3 The edge-area offset and our fit

- **Edge area (computed).** A flat_top's rotation is proportional to its area (Eq. 94). With the flat part at amplitude 1 and Gaussian ramps that peak at the same amplitude ([lib] asm_v2.py:1790), the area is flat length + edge area. The edge area of both halves together is σ√(2π)·erf(k/(2√2)) for an envelope of total length kσ:
  - k = 4: 2.39σ;
  - k = 8 or 10: 2.51σ.
  - For σ = 5 ns this is ≈ 12.5 ns of equivalent flat length.
- **The sweep never reaches zero rotation.** Its minimum is 3 cycles of flat (4.88 ns) plus the ramps (§1.3).
- **How the fit handles it (inference from [app] measurements/rabi.py:174–207).**
  - The model A·e^(−x/τ)·cos(2πfx + φ) + c has a free phase, so a constant offset x₀ shows up as φ = 2πf·x₀.
  - The code takes k = round(φ/π) and x_π = ((k+1)π − φ)/(2πf) (lines 202–203). For x₀ < ¼ Rabi period (k = 0), this gives x_π = 1/(2f) − x₀: the **flat length** that, together with the ramps, makes a π pulse. That is the right number to store.
  - If the ramps alone exceed a quarter period, rounding picks the wrong extremum and x_π lands a full period late. For σ = 5 ns that means a π length below ~25 ns.
  - The decay term is referenced to x = 0 rather than −x₀. That only rescales A.
- **Const pulses** have no designed offset. Any rise time of the analog chain gives a small offset, absorbed in the same way **(inference)**.

### 3.4 Detuning

- With detuning δ between drive and qubit, the Rabi frequency becomes √(Ω² + δ²) and the contrast drops to Ω²/(Ω² + δ²). This follows from the drive Hamiltonian with δ_q ≠ 0 ([Blais21] Eq. 131); the closed form is the standard Rabi formula, not quoted from the sources **(inference)**.
- The damped cosine still fits, but the π length it returns is for the detuned rotation, shorter than the resonant one. That applies equally to every shape.
- **(inference)** A low-contrast, fast Rabi is the sign of a wrong qubit frequency, whatever the shape.

---

## 4. Amplitude Rabi: Gaussian σ, truncation, DRAG

- **What QICK does:**
  - [demo06] cells 21–22: `add_gauss(sigma, length=4σ)`, `style="arb"`, gain swept, "an ≈ 100 ns (σ ≈ 25 ns) long Gaussian pulse". In true σ that is ≈ 17.7 ns and ≈ 5.7σ long (§1.5).
  - The v2 tutorials build Gaussians with σ = length/8 ([tut06] cell 8) and flat_top ramps with σ = length/10 or /8 ([tut02] cell 11; [tut06] cells 14, 17). Each half is therefore 4–5σ.
  - Our app: σ = 20 ns, length 4σ ([app] measurements/rabi.py:30, 56).
- **σ vs anharmonicity.**
  - [Krantz19] §IV.D.3 and Fig. 14: Gaussians with σ = 1, 2, 5 ns "have spectral content that leads to non-zero overlaps with the ω₁→₂ = ω_q − |α| frequency". The anharmonicity is "typically around 200 to 300 MHz".
  - [Lucero08] Fig. 4 (nonlinearity ≈ 200 MHz, Fig. 3 caption): |2⟩ error "drops exponentially with increasing pulse width, reaching the value 10⁻⁴ at 8 ns" FWHM (σ ≈ 3.4 ns). A 4 ns pulse "produces a significant amount of spectral power at ω21".
  - [Motzoi09] Fig. 1 (Δ/2π = −400 MHz, σ = t_g/2): a plain Gaussian's error "is 1% at a gate time of 6 ns".
  - [Blais21] Fig. 28 (Chow et al. 2010): Gaussian errors rise once "their frequency bandwidth become comparable to the transmon anharmonicity".
  - **Rule of thumb (inference):** keep 2π|α|σ ≳ 4, i.e. σ ≳ 3 ns at |α|/2π = 200 MHz. Our 20 ns default is far inside the safe range; there T1/T2, not leakage, limits σ.
- **4σ truncation.**
  - QICK's 4σ Gaussian has a 13.5 % step at each end (§1.5). This puts a sidelobe floor under the spectrum **(computed, power re the carrier at 200 MHz offset):**

    | Pulse | Power at 200 MHz offset |
    |---|---|
    | σ = 10 ns, 4σ long | −40 dB |
    | σ = 10 ns, 6σ long | −63 dB |
    | 40 ns square | −27 dB |

  - For a 20 ns-σ Rabi this does not matter. It would for σ of a few ns **(inference)**.
  - A longer window (6σ) or a lifted Gaussian ([Motzoi09] Eq. 5) removes the floor, at the cost of a longer pulse or a custom envelope via `add_envelope`.
- **DRAG** ([Motzoi09]; [Krantz19] §IV.D.3 Eq. 101; [Chen16] Eq. 1):
  - It adds λ·ṡ(t)/α on the quadrature. "The theoretically optimal choice for reducing dephasing error is λ = 0.5 and an optimal choice for reducing leakage error is λ = 1" ([Krantz19]). [Chen16] confirms this with α/2π = −212 MHz, 10 ns cosine pulses.
  - It matters when gates are short enough that the Gaussian's bandwidth reaches α, and errors below ~10⁻³ are the goal ([Blais21] §VII.A; Fig. 28).
  - Fluxonium does not need it ([Somoroff23] Suppl. Note 3; [Bao22]).
  - QICK has `add_DRAG(ch, name, sigma, length, delta, alpha=0.5, det=0)`, after [Chen16] ([lib] qick_asm.py:1513–1569). It needs a complex envelope, which our generators support (`complex_env: true` [soccfg]; check at qick_asm.py:1403–1404).
  - **(inference)** A Rabi calibration in this app does not need DRAG at σ ≳ 5 ns. It belongs with a later gate-calibration feature (DRAG-λ sweep).

---

## 5. Recommendation for this app

**Rabi length sweep**

1. **Keep "Flat" (const) as the default.** It matches QICK's own Length Rabi ([demo06] cell 19), sweeps in the tProc, starts at 4.88 ns, and reaches full DAC scale, which fluxonium needs. On a transmon it is clean enough for Rabi frequencies ≲ 20 MHz (§3.2).
2. **Add a "Gaussian edges" (flat_top) choice** for fast transmon drives, and to measure with the same shape later gates will use.
   - Parameters: edge σ, with the envelope fixed at **8σ total** (4σ per side, the QICK tutorial range) and `even_length=True`. Suggested default: **σ = 5 ns** (≈ [Somoroff23]'s "5 ns-width edges"; 40 ns of ramps). The validator must enforce 4σ ≥ 3 cycles (4.88 ns), and a Start ≥ 4.88 ns for the flat part (§1.3).
   - x axis: flat length (`get_pulse_param("qubit", "length")`), as now. Show the ramp duration (8σ) and the edge-area equivalent (2.51σ) in the info box. Store the π flat length **together with the edge σ**; it means nothing without it.
   - The scope trigger width must use `total_length`, not the flat length ([app] measurements/rabi.py `_body`).
   - Power hint: treat it like a Gaussian (−6.02 dB at the same gain) (§1.4).
3. **Do not offer a swept-σ Gaussian length sweep.** It cannot be swept in the tProc, so it means one program per point, which is slow over Pyro (unmeasured). Memory is also limited to N·mean(σ) ≤ 1.67 µs (§1.2).

**Two-tone**

4. **Keep the flat probe as the only shape, or add the same flat_top option, off by default.** Flat is what every source uses (§2.1). The cases where edges help are a weak-drive, narrow-line scan with T ≲ T2, where sinc sidelobes at ±1.4/T could look like structure. There, a longer flat probe is the cheaper fix, and it keeps the full 6 dB of drive headroom (§2.2).

**Amplitude Rabi** (not asked, found on the way)

5. The 4σ Gaussian is fine at σ ≳ 5 ns. Optionally offer a 6σ window to drop the 13.5 % end steps (§4).
6. **The σ field allows up to 10 µs, but a 4σ envelope must fit in 6.667 µs.** Cap σ at 1.66 µs, or catch QICK's envelope-memory error and explain it (§1.2).

**Decisions for the user**

- Add a Shape (Flat / Gaussian edges) selector to the Rabi length sweep? To Two-tone too, or not?
- Default edge σ (5 ns suggested) and envelope length (8σ suggested, vs QICK's amplitude-Rabi 4σ convention).
- Gain convention: show the flat_top gain as QICK's (flat at g/2), or rescale it in the UI so "gain 0.5" means the same amplitude for both shapes? Rescaling caps flat_top at gain 0.5.
- Store the π length per shape (flat π length and edge σ as chip parameters)?
- Optional 6σ window for the amplitude-Rabi Gaussian; the σ cap.

---

## Unverified

- Selecting a different stored envelope per loop iteration with hand-written tProc v2 code (§1.2): no example found, not tried.
- The behaviour of the app with σ > 1.667 µs. It is inferred from the two limits, not run.
- How long a per-point (Python-loop) σ sweep takes over our Pyro link.
- [Nguyen19] and [Manucharyan09] give no pulse shapes for Rabi or gates. Fluxonium shape statements rest on [Somoroff23] and [Bao22] only.
- The simulation (§3.2) and spectra (§2.2, §4) are idealized: no decoherence, and no DAC, balun, mixer or line response. On the bench, the analog chain's bandwidth will round a const pulse's edges too.
- [Blais21] Fig. 28 is "adapted from Chow et al. (2010)". We did not read Chow et al. directly.
