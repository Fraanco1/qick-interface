# Two-tone (qubit) spectroscopy: pulsed or CW?

Primary-source notes on how the qubit drive and the readout are timed in two-tone spectroscopy, and what that means for our Two-tone measurement. Every claim cites the paper (arXiv text, read in full with `pdftotext`), the QICK library, or the QICK demo notebook. Read in November 2026.

**Source tags**

| Tag | Source |
|---|---|
| `[Krantz19]` | P. Krantz et al., "A quantum engineer's guide to superconducting qubits", Appl. Phys. Rev. 6, 021318 (2019), arXiv:1904.06560 |
| `[Blais21]` | A. Blais, A. L. Grimsmo, S. M. Girvin, A. Wallraff, "Circuit quantum electrodynamics", Rev. Mod. Phys. 93, 025005 (2021), arXiv:2005.12667 |
| `[Schuster05]` | D. I. Schuster et al., "ac Stark shift and dephasing of a superconducting qubit strongly coupled to a cavity field", PRL 94, 123602 (2005), arXiv:cond-mat/0408367 |
| `[Wallraff05]` | A. Wallraff et al., "Approaching unit visibility for control of a superconducting qubit with dispersive readout", PRL 95, 060501 (2005), arXiv:cond-mat/0502645 |
| `[Gambetta06]` | J. Gambetta et al., "Qubit-photon interactions in a cavity: measurement-induced dephasing and number splitting", PRA 74, 042318 (2006), arXiv:cond-mat/0602322 |
| `[Schuster07]` | D. I. Schuster et al., "Resolving photon number states in a superconducting circuit", Nature 445, 515 (2007), arXiv:cond-mat/0608693 |
| `[SchusterPhD]` | D. I. Schuster, "Circuit Quantum Electrodynamics", PhD thesis, Yale (2007), https://rsl.yale.edu/sites/default/files/2024-08/2007-RSL-Thesis-David-Schuster.pdf |
| `[Manucharyan09]` | V. E. Manucharyan et al., "Fluxonium: single Cooper-pair circuit free of charge offsets", Science 326, 113 (2009), arXiv:0906.0831 (includes the Supporting Online Material) |
| `[Nguyen19]` | L. B. Nguyen et al., "High-coherence fluxonium qubit", PRX 9, 041041 (2019), arXiv:1810.11006 |
| `[Zhang21]` | H. Zhang et al., "Universal fast-flux control of a coherent, low-frequency qubit", PRX 11, 011010 (2021), arXiv:2002.10653 |
| `[Somoroff23]` | A. Somoroff et al., "Millisecond coherence in a superconducting qubit", PRL 130, 267001 (2023), arXiv:2103.08578 |
| `[QICKpaper]` | L. Stefanazzi et al., "The QICK (Quantum Instrumentation Control Kit)", Rev. Sci. Instrum. 93, 044709 (2022), arXiv:2110.00557 |
| `[demo06]` | https://github.com/openquantumhardware/qick/blob/main/qick_demos/06_qubit_demos.ipynb (cell numbers from the `main` branch, downloaded 2026-11-04) |
| `[lib] file:line` | Installed QICK 0.2.442, `.venv/lib/python3.12/site-packages/qick/<file>` |
| `[app]` | Our code, `src/qick_interface/measurements/two_tone.py` |

Statements marked **(inference)** are our own reasoning or arithmetic, not something a source says.

---

## Short answer

- **Both are standard.** The theory of two-tone spectroscopy is written for CW: a steady drive, a steady weak probe, and the steady-state Bloch-equation lineshape ([Blais21] §VI.B.1 Eq. 127; [Schuster05] Eq. 2). The first circuit-QED qubit spectra were CW ([Schuster05]). Labs then moved to **"saturating pulse, then readout pulse"** to keep the readout photons from shifting and broadening the line ([Manucharyan09] SOM; [Wallraff05]). QICK's own demo does exactly that ([demo06] cells 16–17).
- **Our Two-tone is the standard pulsed scheme.** It plays the qubit pulse, waits 50 ns, then plays the readout. That is a line-by-line copy of QICK's `PulseProbeSpectroscopyProgram` ([demo06] cell 16). The scheme is adequate for transmons and for fluxoniums with T1 ≫ the readout time.
- **Two defaults need care, not the scheme.** (1) The 50 µs repetition delay is shorter than the T1 of many modern transmons (QICK's own qubit: T1 = 119 µs, repetition delay 500 µs) and of every fluxonium. (2) For a low-frequency fluxonium the 0–1 contrast is small whatever the timing, because the qubit starts thermally mixed ([Zhang21]; [Somoroff23]).
- **A CW / overlapping variant is worth offering as an option, not as the default.** It helps when T1 is so short that the qubit decays before the readout ends, and for a first, broad search. It costs a measurement-induced Stark shift and broadening, so the readout must be weak (n̄ ≲ 1) ([Schuster05] Fig. 4 caption; [Blais21] §VI.B.2).

---

## 1. What the sources do

### 1.1 Reviews

- **[Krantz19] has no section on qubit spectroscopy.** A search of the full text finds "spectroscopy" only as *noise* spectroscopy (§III.E). What it does give is the physics that matters here:
  - Resonator photons shift the qubit by the ac-Stark shift, Δ_Stark = 2ηχn̄, and dephase it at Γφ = η·4χ²n̄/κ (§III.C.3, Eq. 51).
  - The dispersive Hamiltonian splits the qubit shift into a Lamb shift and an ac-Stark shift ∝ a†a (§V.A, Eq. 147). "The observed qubit frequency is always the Lamb-shifted frequency and not the bare qubit frequency" (footnote to §V.A).
- **[Blais21] §VI.B.1 "Qubit Spectroscopy"** describes the method:
  - "In circuit QED, one typically performs quantum jump spectroscopy by measuring the probability that an applied microwave drive places the qubit into its excited state … realized using two-tone spectroscopy by measuring the cavity transmission, or reflection, of an additional drive of frequency close to ω_r."
  - The analysis is steady state. The excited-state probability is P_e = ½ · Ω_R² / (γ₁γ₂ + δ_q²γ₁/γ₂ + Ω_R²) (Eq. 127, from Abragam 1961). At strong drive P_e saturates at ½ (Fig. 24b).
  - **Power broadening:** the FWHM grows from γ_q = 2γ₂ to 2√(1/T₂² + Ω_R²T₁/T₂) (Fig. 24c). The unbroadened γ₂ comes from extrapolating the squared HWHM to zero drive power.
  - With the probe at the bare cavity and χ ≪ κ, the probe phase is "simply proportional to the qubit population", φ ≈ 2χ⟨σz⟩/κ. So "monitoring φ_s as a function of the spectroscopy tone frequency therefore directly reveals the Lorentzian qubit lineshape (Schuster et al., 2005)."
- **[Blais21] §VI.B.2 "AC-Stark shift and measurement-induced broadening"** is about what happens when the readout is on during the drive:
  - The line shifts by 2χ⟨a†a⟩ (Fig. 25a, steady-state P_e vs drive frequency for three probe powers).
  - It also broadens. The Poisson spread of the coherent probe field gives a crossover "from a Lorentzian qubit lineshape whose linewidth scales with n̄ to a Gaussian lineshape whose linewidth rather scales as √n̄". The dephasing rate is γ_m = κχ²(n̄_g + n̄_e)/(δ_r² + χ² + (κ/2)²) (Eq. 128), ≈ 8χ²n̄/κ for small χ/κ.
  - When 2χ is larger than the linewidth, each photon number gives its own peak: number splitting (Fig. 25b; [Gambetta06]; [Schuster07]).

### 1.2 Transmon / Cooper-pair-box papers

- **[Schuster05] is CW on both tones.**
  - "For a continuous (cw) large amplitude spectroscopy drive, the qubit transition saturates and the population in the excited and ground state approaches 1/2." They map the spectrum by "continuously measuring φ".
  - The line is fitted with the steady-state Bloch result (Eq. 2). Its HWHM follows 2πδν = √(1/T₂² + n_s ω_vac² T₁/T₂). In the low-power limit the unbroadened HWHM is ≈ 750 kHz (Fig. 4a).
  - **They keep the readout weak while measuring linewidth.** "Probe beam power P_RF is adjusted such that n < 1" (Fig. 4 caption). At n ≈ 1 the line is Lorentzian; at n ≈ 40 it is Gaussian and shifted (Fig. 3a/b). The Stark shift is 0.6 MHz per photon (abstract).
  - The spectroscopy tone sits more than 100 MHz from the resonator, so "only a small number n_s … populates the resonator" (main text, after Fig. 2).
- **[SchusterPhD]** uses the same CW method throughout ch. 7–8. The measurement tone is "weakly populating the resonator with n_RF ≈ 2 photons" (§8.2). In the sideband experiment an unexplained asymmetry was "likely due to photons in the cavity from the weak measurement … A pulsed measurement protocol, would allow one to eliminate the former possibility" (§8.2, p. 190–191). This is the earliest first-party statement we found of *why* one moves from CW to pulsed readout.
- **[Wallraff05] introduces pulsed control with dispersive readout.**
  - Saturation is done with "a long microwave pulse which incoherently mixes the ground and excited states such that P↓ = P↑ = 1/2".
  - For Rabi the readout is continuous: the qubit pulse is short, and "the measurement response φ is continuously monitored. This sequence is repeated every 50 µs", with T1 ≈ 7.3 µs (≈ 7 T1 of repetition delay).
  - After a π pulse the signal rises in 2/κ ≈ 400 ns and then decays with T1. "As a result, the maximum measured response φ_max does not reach the full value". The contrast was 85 % because T1 is "about 15 times longer than the response time of the measurement".
  - For Ramsey: "To avoid dephasing induced by a weak continuous measurement beam [17] we switch on the measurement beam only after the end of the second π/2 pulse" (Fig. 1c, "followed by a pulsed measurement").
- **[QICKpaper] §V (Fig. 14b):** "The qubit probe frequency was swept around 4.743 GHz followed by a readout tone." The qubit there has T1 = 119.5 µs and T2* = 148.6 µs.

### 1.3 Fluxonium papers

- **[Manucharyan09] uses both and says why it uses pulsed for the map.**
  - Fig. 3 (line cuts) is called "a two-tone spectroscopy measurement … in addition to the fixed frequency readout tone, we probe the transition frequencies of the atom through a second, variable frequency spectroscopy tone". Its peaks are Lorentzian, with power-dependent widths and heights that follow the Bloch equations (Fig. 3 insets).
  - The flux-vs-frequency map, Fig. 4A, "is taken in the pulsed regime, when the spectroscopy generator outputs a **6 µs saturating pulse followed immediately by the 2 µs readout pulse**. This way we ensure that the sample is exposed to only one tone at a time, avoiding various spurious effects" (SOM, "Comments on the data").
  - **Unverified:** whether Fig. 3 itself was CW. The SOM describes Fig. 3 only as heterodyne phase vs spectroscopy frequency.
  - They read the 0–1, 0–2 and 0–3 transitions, all at GHz (Fig. 3, 4B).
- **[Nguyen19]** says only that the spectrum (Fig. 2) "was obtained by the conventional two-tone dispersive spectroscopy". **Unverified:** the timing; the paper does not give it.
  - Its qubits sit at a few hundred MHz at half flux (§II). "Due to the thermal occupation of the 1-state one can see the transition 1–2 in the small vicinity of φ_ext = π" (§II, Fig. 2).
  - The 0–2 line shows "continuous reduction of its power-broadened linewidth (in a fixed power experiment)", so it was run power-broadened on purpose.
- **[Zhang21]:** the qubit is at **14 MHz**, "an order of magnitude lower in energy than the ambient thermal energy scale" (abstract).
  - "The qubit starts in a nearly evenly-mixed state in thermal equilibrium", with P(|e⟩) = 0.4955 ± 0.0015 (main text, after Fig. 2).
  - They do not drive 0–1 by microwaves for control. The "suppressed charge matrix elements and low transition frequency have made it challenging to perform fast single-qubit gates using standard protocols" (abstract). Instead they reset through higher levels and the resonator and use flux pulses (Fig. 2a, Fig. 4).
- **[Somoroff23]:** the qubit is at ω₀₁/2π = **163 MHz**.
  - Circuit parameters come from "the two-tone spectroscopy of the device" (Suppl. Note 1, Suppl. Fig. 1). **Unverified:** the timing of that two-tone.
  - The thermal ground population is p₀ = 0.578, which they call an effective 25 mK (Suppl. Note 2).
  - "The readout pulse causes transitions between qubit states" (Suppl. Note 2C). They use this on purpose to initialize, with "a square cavity pulse of duration 160 µs".

### 1.4 QICK's own demo

- The only QICK qubit demo is tProc **v1**: [demo06], "06 – Qubit demos: working with a real qubit". Its header says the API has changed and "we cannot guarantee that it still behaves correctly when connected to a real qubit" (cell 0). No tProc v2 qubit demo exists in 0.2.442 (see `qick.md` §7).
- **Pulse Probe spectroscopy** (`PulseProbeSpectroscopyProgram`, cell 16):
  - The body is `pulse(qubit)`, then `sync_all(us2cycles(0.05))` ("align channels and wait 50ns"), then `measure(...)`. So the readout comes after the drive and **does not overlap it**.
  - The qubit pulse is `style="const"`.
- **Parameters** (cells 6 and 17):
  - `probe_length` = **2.0 µs**; `qubit_gain` = 10 DAC units (out of ±32766, so very weak).
  - `readout_length` = 3.0 µs; `relax_delay` = **500 µs**.
  - 400 points at 10 kHz steps around 4.743 GHz; 20 reps × 50 rounds; acquired with `threshold=` as a qubit population.
  - With T1 = 119.5 µs on this qubit ([QICKpaper] Fig. 14d), the repetition delay is ≈ 4 T1 and the probe is ≪ T1. **(inference)**
- Resonator spectroscopy uses `relax_delay` = 10 µs (cell 11), since the qubit is not driven there.

---

## 2. Trade-offs

### 2.1 Drive power: saturation and power broadening

- Contrast saturates at P_e = ½ and the line widens as √(1/T₂² + Ω_R²T₁/T₂) ([Blais21] Eq. 127 and Fig. 24; [Schuster05] Eq. 2 and Fig. 4).
- A search sweep is usually run power-broadened on purpose, to be easy to find. The linewidth / T₂ estimate comes from a power series extrapolated to zero ([Blais21] §VI.B.1; [Manucharyan09] Fig. 3 insets; [Nguyen19] §II).
- A long, strong pulse also excites multi-photon transitions such as 0–2/2. [SchusterPhD] §7.3 uses this to measure ω₁₂.

### 2.2 Readout on during the drive (CW or overlapping)

- **Advantage:** the readout sees the driven steady state directly. No T1 decay happens between drive and readout. This is the original method ([Schuster05]).
- **Cost:** readout photons shift the line by 2χn̄ and broaden it, up to number splitting in the strong-dispersive limit ([Blais21] §VI.B.2, Eq. 128, Fig. 25; [Krantz19] Eq. 51; [Gambetta06]; [Schuster07]). The labs that do it keep n̄ ≲ 1–2 ([Schuster05] Fig. 4 caption; [SchusterPhD] §8.2).
- Strong readout can itself cause transitions ([Somoroff23] Suppl. Note 2C), and "various spurious effects" ([Manucharyan09] SOM).
- **(inference)** The frequency you mark in a CW scan is the Stark-shifted frequency at that readout power. Pulsed gives the frequency at zero photons, which is the one later pulses will use.

### 2.3 Readout after the drive (pulsed)

- **Advantage:** "the sample is exposed to only one tone at a time" ([Manucharyan09] SOM). There is no Stark shift or measurement dephasing during the drive ([Wallraff05], Ramsey). The readout can be strong, which gives better SNR per shot.
- **Cost:** the qubit decays with T1 during the gap and the readout window. With the resonator response time 2/κ, the contrast is limited by T1 / (readout time) ([Wallraff05]: 85 % at T1/(2/κ) ≈ 15).
  - **(inference)** For a readout window t_ro, the averaged signal is reduced roughly by (T1/t_ro)(1 − e^(−t_ro/T1)). That is ≈ 0.99 for t_ro = 1.5 µs and T1 = 100 µs, but ≈ 0.43 for T1 = 1 µs.
- **Pulse length vs steady state.** The Lorentzian lineshape assumes steady state, so the drive must last several T1, T2 ([Blais21] Eq. 127 is a steady-state result; [Schuster05] "Bloch equations in steady state").
  - **(inference)** A shorter pulse still finds the qubit. The line is then set by the pulse length (Fourier width ~1/τ, with Rabi-like side lobes) rather than by T2. QICK's demo uses 2 µs on a T2* ≈ 150 µs qubit, so it is a "find the line" measurement, not a linewidth measurement.

### 2.4 Repetition delay, heating and duty cycle

- Labs wait several T1 between shots: ≈ 7 T1 in [Wallraff05] (50 µs at T1 ≈ 7 µs), ≈ 4 T1 in [demo06]/[QICKpaper] (500 µs at T1 ≈ 120 µs).
- **(inference)** If the delay is < T1, population carries over to the next shot. In AveragerProgramV2 the `reps` loop is outermost by default ([lib] asm_v2.py:2684, 2715), so consecutive shots step through frequency. The carry-over then lands on the *next* frequency point, which smears the line in the sweep direction and lowers the contrast. `reps_innermost=True` would keep the carry-over at the same frequency.
- **Unverified:** no source we read quantifies fridge heating from CW drive versus pulsed drive at spectroscopy powers. **(inference)** A CW drive for ~100 % duty cycle dissipates ~1/(duty cycle) more power in the attenuators than a pulsed one at the same amplitude.

### 2.5 Instrument

- CW two-tone needs only a VNA plus a second CW source ([Schuster05] Fig. 1a). It is the natural mode for a PNA-X with a second internal source **(inference)**.
- Pulsed two-tone needs an AWG/FPGA plus a digitizer ([Manucharyan09] SOM: E8267D + Tektronix AWG for the 6 µs pulse; [QICKpaper]).
- In QICK, a single `const` pulse is limited to < 2¹⁶ fabric cycles (≈ 106 µs). Longer tones need `mode="periodic"`. One readout window is limited to ≈ 118 µs to avoid sum overflow (`qick.md` §8, items 7–8). **(inference)** So a "CW" variant on QICK is in practice a long drive with an overlapping readout window, repeated, rather than a true CW tone.

---

## 3. Fluxonium specifics

- **Thermal population limits the 0–1 contrast, whatever the timing.** Saturation moves the populations from thermal to ½/½. So the signal is ∝ p₀ − p₁ = tanh(hf/2k_BT). **(inference, standard Boltzmann arithmetic)**
  - Transmon at 5 GHz, 50 mK: ≈ 1.0 (full contrast).
  - 163 MHz at 25 mK: p₀ = 0.578, so p₀ − p₁ = 0.156. This matches [Somoroff23] Suppl. Note 2.
  - 14 MHz at ~42 mK: p₀ − p₁ ≈ 0.01 ([Zhang21]: P(e) = 0.4955).
- **What fluxonium papers do instead:**
  - They map the higher, GHz transitions (0–2, 0–3, 1–2) and fit the Hamiltonian ([Manucharyan09] Fig. 3–4; [Nguyen19] Fig. 2). The 1–2 line is visible only *because* of thermal population ([Nguyen19] §II).
  - They prepare the qubit actively first (reset through higher levels in [Zhang21] Fig. 2a; readout-induced pumping in [Somoroff23] Suppl. Note 2C).
- **Weak matrix element at half flux.** The 0–1 transition needs a strong drive ([Zhang21] abstract). It is also parity-forbidden for 0–2 exactly at half flux ([Manucharyan09] Fig. 4A inset; [Nguyen19] §II).
- **Long T1.** Fluxonium T1 is 100 µs to ~1 ms ([Nguyen19] Table I; [Somoroff23] Fig. 2). A 50 µs repetition delay is far below that. **(inference)** For a qubit that starts thermal, the main cost is carry-over between frequency points (§2.4), not lost contrast.
- **Drive path.** A 14–500 MHz drive comes straight from a DAC in the first Nyquist zone. Whether the RFSoC 4x2 baluns pass it is an open hardware question (`qick.md` §7, "Fluxonium caveat"). **Unverified.**

---

## 4. Recommendation for our app

**Current scheme** ([app] `_Program._body`): qubit pulse (default 10 µs), `delay_auto(t=0.05)`, readout pulse (2 µs) with a 1.5 µs window, and `final_delay` = 50 µs. It is the same as the QICK demo and the [Manucharyan09] "saturating pulse followed immediately by readout pulse" scheme. **Keep it as the default for both qubit types.**

Suggested changes (each is a design decision for the user):

1. **Repetition delay.** The 50 µs default is short for a transmon with T1 ≳ 20 µs and for any fluxonium.
   - Either raise the default (QICK's demo uses 500 µs, ≈ 4 T1) or tie it to a stored T1 (e.g. 5 T1 once a T1 measurement exists).
   - Alternatively, set `reps_innermost=True` so that any carry-over stays at the same frequency point. Measure first whether that slows the in-tProc sweep.
2. **Offer an "Overlap readout" (CW-like) option, off by default.** The readout window would start inside the drive, for example during its last few µs, or the drive would cover the whole readout. Use it when:
   - **T1 is short** (≲ a few × the readout window), so pulsed contrast drops (§2.3).
   - It is a **first, broad search** with an unknown qubit, at high drive power, where the Stark shift (≈ 2χn̄) does not matter.
   - The user should keep the readout gain low (n̄ ≲ 1). The UI should say that the marked frequency is Stark-shifted, so a pulsed scan is needed before the marker is stored as `qubit_freq_mhz`.
   - On QICK this is bounded by ≈ 106 µs per pulse and ≈ 118 µs per window (§2.5). True CW would need periodic mode and is not worth it.
3. **Fluxonium.** Timing will not fix the 0–1 contrast at low frequency (§3). Better tools are:
   - a wide sweep that reaches the GHz transitions (0–2, 0–3, 1–2);
   - high drive gain with long pulses (weak matrix element);
   - later, an optional preparation step before the drive (reset or readout-induced pumping).
   - Check the DAC low-frequency path on the bench before relying on a sub-500 MHz drive.
4. **Linewidth / T2 from spectroscopy.** Make the qubit pulse ≫ T1, T2 (up to the ≈ 100 µs limit), keep the readout after the drive, and sweep the drive gain to extrapolate the linewidth to zero power ([Blais21] §VI.B.1). Otherwise treat the width as power- or Fourier-limited.
