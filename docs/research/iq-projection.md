# Reducing Rabi I/Q to one signal: is the projection sound?

Rabi turns the averaged complex S21 at each sweep point into one real trace. It projects the points onto the direction of largest variance in the I/Q plane (PCA), after centring them on their mean ([app] measurements/rabi.py:196–201). It then fits a damped cosine and reads the π point from the fit (lines 208–241). This note checks the physics behind that projection, what other frameworks do, where a variance-based projection fails, and whether our code is right. Read in November 2026. Papers were read in full from the arXiv PDFs with `pdftotext`. Framework code was cloned on 2026-11-05 at the commits listed below.

**Source tags**

| Tag | Source |
|---|---|
| `[Krantz19]` | P. Krantz et al., "A quantum engineer's guide to superconducting qubits", Appl. Phys. Rev. 6, 021318 (2019), arXiv:1904.06560 |
| `[Blais21]` | A. Blais et al., "Circuit quantum electrodynamics", RMP 93, 025005 (2021), arXiv:2005.12667 |
| `[Blais04]` | A. Blais et al., "Cavity quantum electrodynamics for superconducting electrical circuits", PRA 69, 062320 (2004), arXiv:cond-mat/0402216 |
| `[Gambetta06]` | J. Gambetta et al., "Qubit-photon interactions in a cavity: measurement-induced dephasing and number splitting", PRA 74, 042318 (2006), arXiv:cond-mat/0602322 |
| `[Gambetta08]` | J. Gambetta et al., "Quantum trajectory approach to circuit QED: quantum jumps and the Zeno effect", PRA 77, 012112 (2008), arXiv:0709.4264 |
| `[Walter17]` | T. Walter et al., "Rapid high-fidelity single-shot dispersive readout of superconducting qubits", PR Applied 7, 054020 (2017), arXiv:1701.06933 |
| `[Sank16]` | D. Sank et al., "Measurement-induced state transitions in a superconducting qubit: beyond the rotating wave approximation", PRL 117, 190503 (2016), arXiv:1606.05721 |
| `[Chen16]` | As in `pulse-shapes.md` (leakage to \|2⟩), arXiv:1509.05470 |
| `[lib]` | Installed QICK 0.2.442, `.venv/lib/python3.12/site-packages/qick/<file>` |
| `[demo06]`, `[tut07]` | https://github.com/openquantumhardware/qick `qick_demos/06_qubit_demos.ipynb` and `docs/source/tutorials/07_Advanced_Generators_And_Readouts.ipynb`, `main` at 80753a9 (2026-10-30), cell numbers. Tutorial 07 is newer than our 0.2.442. |
| `[qiskit]` | qiskit-experiments **0.8.2** (f0d4a78). `Rabi` was removed in 0.9.0 with the rest of the pulse experiments (`docs/release_notes.rst`, "remove-pulse-deprecations"), so 0.8.2 is the last version with it. |
| `[qibocal]` | qiboteam/qibocal `main` at 031cc76 (2026-11-04) |
| `[quantify]` | quantify-os/quantify-core `main` at 344c8bc (2025-08-18) |
| `[laboneq]` | zhinst/laboneq-applications `main` at 225b07f (2026-10-29) |
| `[app]` | Our code under `src/qick_interface/` at 69ef93f |

Statements marked **(inference)** are our own reasoning. Statements marked **(computed)** come from short numpy scripts that call our `_project` and `_fit_damped_cosine` on synthetic data. Neither is a source.

---

## Short answer: the claims checked

| Claim | Verdict |
|---|---|
| (a) The averaged readout is S = (1−p)·S0 + p·S1, so it lies on the segment between the \|0⟩ and \|1⟩ responses. | **Holds, and more robustly than stated.** The dispersive field is displaced by αg·Πg + αe·Πe ([Gambetta08] Eqs. A8–A9), so its mean is the population-weighted mix of the two pointer states. Averaging is linear in the initial populations even with T1 decay during the window, ring-up, or measurement-induced transitions. Those effects move or shrink the segment but don't bend it (§1.2). What does bend it: a third populated level (\|2⟩), a nonlinear receiver, and drift during the run. |
| (b) The segment's direction depends on readout frequency, cables and LO phase. | **Holds.** The readout frequency sets where S0 and S1 sit ([Blais21] Eqs. 110–113, Fig. 19; [Krantz19] Fig. 19). Cables and the LO phase rotate everything by a common factor (inference, from [Krantz19] Eqs. 162–163 and `s21.md` §7). |
| (c) I or Q alone scales with the segment's angle. | **Holds.** I = Re S0 + p·\|ΔS\|·cos β: the contrast is \|ΔS\|·cos β, and it vanishes when β = 90° (inference, elementary). |
| (d) Magnitude can nearly vanish when reading between the dressed frequencies. | **Half right.** The magnitude doesn't vanish. Its **contrast** vanishes to first order: \|S0\| = \|S1\| at the midpoint and all the information is in the phase ([Krantz19] §V.B; [Blais21] Eq. 112 with δr = 0). Worse, \|S\| is then **not monotonic** in p: it dips at p = ½. A magnitude Rabi then oscillates at **twice** the Rabi frequency and the fit returns **half** the π pulse **(computed)**, §1.3. |
| (e) Phase is roughly but not exactly linear in p. | **Holds.** Phase is monotonic in p whenever the origin is off the segment, so its extrema fall at the π point. It isn't linear: for ±45° pointers it deviates by 3.3 % of its swing, for ±20° by 0.6 % **(computed)**. |
| (f) PCA is a sound reduction. | **Sound for finding the π point, with known gaps.** It is what Qibocal does by default and what LabOne Q does when no calibration states are measured. Qiskit Experiments does the same with an SVD (§2). The gaps are an arbitrary sign, an arbitrary offset and an axis that is meaningless without signal (§3). |

**Bug check of `rabi.py` (§4):** no error in the PCA or the π-point formula. The π point is unchanged under a sign flip **(computed)**. One display defect: the sign of Tr1 is chosen by the eigensolver, not by physics. It flips at random from round to round when the I/Q axis is near the diagonal (§4.2, finding F1). One known limit, already documented in `pulse-shapes.md` §3.3: with Gaussian edges the π length is wrong by half a period once the edges alone rotate more than π/2 (finding F2).

---

## 1. Physics

### 1.1 Two pointer states

- In the dispersive regime the resonator frequency depends on the qubit state, ωr ± χ ([Blais21] Eq. 107; [Krantz19] §V.A, Eq. 146).
- Driving the resonator leaves a qubit-state-dependent coherent state: cg\|g, αg⟩ + ce\|e, αe⟩ ([Blais21] Eq. 108). The same holds in [Blais04] §V.A: "\|ψ⟩ = α\|↑, θ⟩ + β\|↓, −θ⟩".
- The steady-state amplitudes are αe/g = −ε/((δr ± χ) − iκ/2) ([Blais21] Eq. 110). Heterodyne detection maps each one to a point in the I/Q plane ([Krantz19] Eqs. 162–163, Fig. 19(c), Fig. 22(c)).
- Exactly within the dispersive approximation, the polaron transformation gives `a → a + Πα` with Πα = αg·Πg + αe·Πe ([Gambetta08] App. A, Eqs. A8–A9). **(inference)** Taking the trace gives ⟨a⟩ = ρgg·αg + ρee·αe. The mean output field is the population-weighted mix of the two pointers, and coherences don't enter. Averaging many shots therefore gives S = (1−p)·S0 + p·S1.

### 1.2 What keeps it a straight line, and what bends it

**(inference)** A quantum expectation value is linear in the initial density matrix, the master equation is linear, and so are averaging over shots and a linear receiver. So the averaged, integrated readout is an affine function of the initial populations, whatever happens inside the window. With only \|0⟩ and \|1⟩ populated it is an affine function of p, which is the segment. Each effect below changes *where* S0 and S1 are, but not the straight line:

- **T1 during readout.** Decay inside the window makes an excited shot look partly like a ground shot ([Krantz19] §V.C: the qubit "relaxes … during the readout", with a count on the "wrong" side; [Walter17] p. 3: transition errors grow as 1 − e^(−τ/T1)). In the average this shrinks the effective \|1⟩ point toward S0: less contrast, same line. [Gambetta08] Eq. 3.15 (ż = −γ1(z + 1)) shows the population evolution is linear.
- **Ring-up and a window that isn't in steady state.** The pointers follow time-dependent paths α(t) before reaching steady state ([Blais21] Eqs. 109a–b, Fig. 18; [Walter17] Fig. 1(c); [Krantz19] Fig. 22(b), the readout delay τrd). The window integrates each path to one fixed complex number per state. Still two points.
- **Readout power.** Above a fraction of n_crit the dispersive picture fails. The pointer blobs distort ("bananization", [Blais21] §V.C.2), and readout drives qubit transitions, "often at … n̄ ∼ 1 − 10" ([Blais21] §V.C.2), sometimes out of the two-level subspace ([Sank16] abstract). Measurement-induced dephasing is [Gambetta06]. All of these are linear in the initial state, so they reduce or move the contrast but don't bend the average (inference).

What does bend the trajectory or make it non-affine in p:

- **A third populated level.** Each transmon level j pulls the resonator by its own χj ([Blais21] Eqs. 40–41; Eqs. 61–62 for fluxonium and other multilevel circuits). A drive that leaks population into \|2⟩ ([Chen16]; more likely with short, strong pulses, see `pulse-shapes.md`) adds a third pointer S2. The average then moves in the triangle S0–S1–S2, not along the segment (inference). For an amplitude Rabi, leakage grows with amplitude, so the path curves at the strong end of the sweep.
- **Receiver nonlinearity** (amplifier or ADC compression). It is not quantum, but it is the one thing that makes the map from field to I/Q nonlinear (inference).
- **Drift during the run** (LO phase, amplifier gain, a flux-tunable resonator). It moves S0 and S1 over time. It shows up as scatter perpendicular to, or along, the segment, not as a function of p (inference).
- **Coherence-dependent readout** beyond the dispersive approximation. [Gambetta08] App. A shows coherences drop out *within* it. We found no source that sizes the correction outside it. Not verified.

### 1.3 Readout frequency: magnitude vs phase

- In steady state |αe/g| = 2ε/√((κ/2)² + (δr ± χ)²) and φe/g = arctan((δr ± χ)/(κ/2)) ([Blais21] Eqs. 112–113). With the drive at the bare frequency (δr = 0) the two magnitudes are equal and the phases are ±arctan(2χ/κ) ([Blais21] text after Eq. 113). Krantz says the same: "the reflected magnitude is identical for \|0⟩ and \|1⟩, and all information about the qubit state is encoded in the phase θ" when probing "just in-between" ([Krantz19] §V.B, Fig. 19(b)). Probing at one of the pulled frequencies, ωr ± χ, the information is mostly in the transmitted amplitude instead ([Blais04] §V.A, Figs. 6–7).
- Separation in the I/Q plane, \|S1 − S0\|, is what sets distinguishability, and it is largest at the midpoint ([Krantz19] Fig. 19 caption). χ = κ/2 maximizes the long-time SNR ([Blais21] Eq. 117).
- **Cables, LO and the reference phase** multiply every point by the same complex factor (S21 is a ratio of phasors, `s21.md`; absolute phase is meaningless, `s21.md` §7). That factor rotates and scales the segment about the origin. It changes I and Q individually. It does **not** change \|S\| or the phase relative to the mean (inference). An *additive* offset, such as LO leakage or an ADC DC offset, does move the origin, and with it the magnitude and phase traces (inference).

**Geometry of the four reductions (inference, elementary; checked numerically):**

| Reduction | Behaviour along the segment |
|---|---|
| Projection on the segment direction | Exactly affine in p. The contrast is \|ΔS\|. |
| I or Q alone | Affine in p. The contrast is \|ΔS\|·cos β, where β is the segment's angle to the axis. It is zero when the segment is perpendicular. |
| Phase arg S | Monotonic in p (if the origin is off the line), not linear. The extrema land at p's extrema, so the π point is right; the cosine shape is slightly distorted. |
| Magnitude \|S\| | Distance from the origin to a point moving on a line: convex in p, with a minimum at the foot of the perpendicular. Monotonic only if that foot is outside the segment. At the midpoint frequency the foot is at p = ½. |

**(computed)** Pointers at ±45° and ±20° about a common rotation, with Rabi π at x = 0.40, run through our fit:

| Trace | π point fitted, ±45° | π point fitted, ±20° |
|---|---|---|
| PCA projection | 0.400 | 0.400 |
| Phase | 0.400 | 0.400 |
| I (at one arbitrary rotation) | 0.400 | 0.400 |
| \|S\| | **0.200** | **0.200** |

The magnitude trace keeps some contrast, so "can nearly vanish" is too strong. But that contrast is at twice the Rabi frequency. A magnitude Rabi read at the midpoint gives a wrong π pulse, and the R² gate does not catch it, because the doubled cosine fits well.

---

## 2. What the open frameworks do

| Framework | Reduction for a Rabi without single-shot | Sign / reference | With g/e references |
|---|---|---|---|
| **QICK demos** | None. Rabi in [demo06] is acquired *thresholded* (`acquire(soc, threshold=…)`, cells 20, 23) after a single-shot calibration (cell 14). | The calibration rotates the I/Q data by θ = −arctan2(ye − yg, xe − xg), using the g and e medians (cell 3). It stores the angle as the readout phase (`res_phase`) and the threshold (cell 14). | The plot's y axis is "Qubit Population". `acquire(threshold, angle)` projects I·cos θ + Q·sin θ and thresholds each shot ([lib] qick_asm.py:2096–2111). The angle is given by the user, so it is a stored per-qubit rotation. |
| QICK tutorial 07 (main, not 0.2.442) | Shows rotating raw I/Q by the measured mean phase (cable delay), either on the up- or down-conversion phase ([tut07] cells 8–9, 18–19). | Fixed angle, stored. | — |
| **Qiskit Experiments 0.8.2** | Default for kerneled data: `dimensionality_reduction=SVD`, `normalization=True` ([qiskit] data_processing/processor_library.py:128–129). Single shots are averaged, then SVD, then `MinMaxNormalize` to [0, 1] (lines 67–72; nodes.py:105–125). Other options: `ABS`, `REAL`, `IMAG` (nodes.py:847–853). | The SVD is trained on the same experiment's data (curve_analysis/base_curve_analysis.py:383–384). It centres on the mean (nodes.py:294–299) and takes the first left singular vector (line 302). The sign is fixed so the axis's I component is positive (line 306): a convention, not physics. | Discriminated (`meas_level=2`) data goes through `Probability` (processor_library.py:131–133). |
| | Rabi fit: `amp·cos(2π·freq·x + phase) + base`, with amp in ±2·max, phase in [−π, π] (curve_analysis/standard_analysis/oscillation.py:89–91). The π amplitude is π/(2π·freq), so the fitted **phase is ignored** (library/calibration/rough_amplitude_cal.py:216–221). | The sign doesn't matter for the π point: the amplitude is free and the phase unused. | — |
| **Qibocal** | `rabi_amplitude_signal` / `rabi_length_signal`: `acquisition_type=INTEGRATION`, then `PCA().fit_transform(quadratures)[:, 0]` (protocols/rabi/amplitude_signal.py:109, 141; length_signal.py:146). | scikit-learn's PCA sign rule (not checked here). π point = (T/2)·(round(1 + φ/π) − φ/π) (utils.py:273–295, used at 395, 421). This is **the same formula as ours** (§4.3). | `rabi_amplitude` uses `AcquisitionType.DISCRIMINATION` and `probability(…, state=1)` (amplitude.py:79, 83). The classifier stores angle = −atan2 of (mean1 − mean0) (fitting/classifier/qubit_fit.py:93–94). |
| **Quantify** | `RabiAnalysis` rotates by the angle of (farthest point − point at x ≈ 0), then fits the real part (analysis/single_qubit_timedomain.py:616–647). With rotation off it fits \|S21\| (line 650). | **Physical sign:** the zero-drive point is the reference, so the trace rises from \|0⟩. `RabiModel` fixes phase = π (minimum at x = 0), amplitude ≥ 0, and amp180 = 1/(2f) (analysis/fitting_models.py:569–573, 587). | `rotate_to_calibrated_axis`: rotate by arg(S1 − S0), divide by \|S1 − S0\|, subtract S0. The result is 0 at \|0⟩ and 1 at \|1⟩ (analysis/calibration.py:14–40). It is used when the data end with calibration points (single_qubit_timedomain.py:87–88, 108–114). Without them T1 and Ramsey also fall back to \|S21\| (line 114). |
| **LabOne Q applications** | No calibration traces: PCA, coded like ours (covariance, `np.linalg.eig`, largest eigenvalue) (analysis/calibration_traces_rotation.py:38–72; used at 222–225). | No sign fix. The π-amplitude code says so: "if pca is done, it can happen that the pi-pulse amplitude is in pi_amps_bottom". It takes the first extremum after the first π/2 crossing (analysis/amplitude_rabi.py:241–252). | **Default:** the experiment measures g and e calibration traces (`use_cal_traces=True`, `cal_states="ge"`, experiments/options.py:121–126). The data are projected on the g→e line and normalized to its length, giving 0 at g and 1 at e (calibration_traces_rotation.py:99–153; `do_pca=False`, analysis/options.py:153–157). |

**Pattern.** Every framework uses calibrated references when it has them: g/e single-shot (QICK, Qibocal) or g/e calibration traces (LabOne Q, Quantify). Without references, two (Qibocal, LabOne Q) use PCA on the sweep's own data, and Qiskit uses the equivalent SVD. Quantify instead uses the zero-drive point plus the farthest point, which fixes the sign physically. Qiskit is the only one that fixes the PCA sign at all, and its rule (I > 0) is arbitrary. [Krantz19] §V.C states the principle: project onto "the axis for which their relative separation in the complex plane is maximized", with the footnote "we have the freedom to choose projections".

---

## 3. Pitfalls of a variance-based projection, and remedies

| Pitfall | What happens | Remedy |
|---|---|---|
| **No oscillation (noise only)** | The axis follows the noise and is random. PCA picks the direction of largest noise, so the projected trace has its variance biased upward (inference). | Our R² ≥ 0.8 gate. In 200 noise-only runs it reported no π point **(computed)**; [app] tests/test_rabi.py:50–60 covers this. |
| **Low contrast vs anisotropic noise** | With Q noise 3× the I noise, the median axis error is 28° when contrast ≈ I noise, 20° at 3×, 3° at 10× **(computed)**. Projecting off-axis by δ only costs a factor cos δ (6 % at 20°), so the π point survives wherever the fit itself is meaningful (inference). Possible sources of anisotropy: LO phase noise and slow phase drift, which spread points tangentially to S (inference). | A stored axis, measured once at high SNR. |
| **Sign ambiguity** | The eigenvector sign is not defined by `numpy.linalg.eigh`. In this env (numpy 2.5.4) it follows a rule tied to the dominant component. Near \|I\| = \|Q\| it is random: at a 45° axis, 52 of 100 noise realizations came out one way **(computed)**. The π point doesn't care (§4.3), but Tr1 can flip between rounds and between runs. | Fix the sign physically. Make the trace increase from the point at zero drive (Quantify), or use a g reference. |
| **Arbitrary offset and scale** | Centring on the mean makes the trace's zero the sweep's average population, not \|0⟩, and the scale is \|ΔS\| in a.u. Traces from runs with different sweeps aren't comparable even with the same sign. | Normalize with g/e references: 0 at \|0⟩, 1 at \|1⟩ (Quantify, LabOne Q). |
| **Curved trajectory** (\|2⟩ leakage) | PCA picks the best-fit line through a curved path. The projection mixes in \|2⟩ population, and the cosine fit absorbs it as distortion (inference). | Look at the raw I/Q path. Reduce leakage (longer or DRAG pulses). Three-state references once single-shot exists. |
| **Axis changes between runs** | Each run (and each round, in our live updates) recomputes the axis. Two Rabi runs at different readout settings can't be overlaid (inference). | A stored rotation per chip (and readout frequency). |

**Contrast vs population.** Without references, the y axis is "signal", not population. A Rabi that reaches 0.8 instead of 1 (thermal population, detuning, T1 in the window) is indistinguishable from a smaller \|ΔS\|. Population needs either references with known preparation (calibration traces) or single-shot thresholds. Both still carry readout-error bias unless corrected ([Walter17] p. 3–4, errors split into overlap and transition errors).

---

## 4. Our implementation

### 4.1 `_project` ([app] measurements/rabi.py:196–201)

- **Centring:** `z = s21 − s21.mean()`. `np.cov` would centre again, which is harmless. The projection uses the centred z, as Qiskit (nodes.py:294–299) and LabOne Q (calibration_traces_rotation.py:51–52) do.
- **eigh:** `np.cov(np.vstack([z.real, z.imag]))` is the 2×2 covariance (rows are variables). `eigh` is right for a symmetric matrix. It returns eigenvalues in ascending order with eigenvectors as **columns**, so `v[:, np.argmax(w)]` is the principal axis. LabOne Q's code is equivalent with `eig` (line 59). Correct.
- **Projection:** z·axis = Re z·a₀ + Im z·a₁. Correct, and for noiseless straight-line data it equals ±(p − p̄)·\|ΔS\| (§1.3).
- **Equivalence with SVD:** the principal eigenvector of the covariance is the first left singular vector of the centred 2×N matrix, which is what Qiskit uses (inference, standard linear algebra).

### 4.2 Finding F1 (display, low severity): Tr1's sign is set by the eigensolver

- **Where:** [app] measurements/rabi.py:199–201.
- **What:** the eigenvector's sign is not physical. In our env it switches with the axis angle, and it is random near the diagonals: 45° gave 52/100, 225° gave 56/100 **(computed)**. Rabi re-projects the cumulative average every round (rabi.py:185–186), so the live Signal and Fit traces can flip upside down mid-run. Two runs can also come out with opposite signs.
- **Effect on results:** none on the π point (§4.3). It does affect what Tr1 shows and Marker readouts on it, and the mV trace's sign (rabi.py:189–191).
- **Fix options (decision for the user):**
  - Orient the axis so the signal increases away from the point nearest zero drive (Quantify's rule).
  - Orient it toward a stored \|1⟩ direction.
  - At least fix it deterministically, as Qiskit does with I > 0. That is still arbitrary and still discontinuous where the I component crosses zero.

### 4.3 The fit and the π point (lines 208–241)

- **Sign invariance.** After the fit, the code makes the amplitude positive by adding π to the phase (lines 233–234). A sign flip of y therefore shifts φ by π, k = round(φ/π) by 1, and x_π = ((k+1)π − φ)/(2πf) is unchanged. Checked: 0.400984 for both signs **(computed)**. Correct.
- **Reference point is x = 0, not the sweep start.** k = round(φ/π) picks the cosine extremum nearest **x = 0**, and x_π is the next one. That is physically right: zero drive means \|0⟩, wherever the sweep starts. A sweep from gain 0.25 still returned 0.3999 for a true 0.40 **(computed)**. The code comment at line 236 ("the start of the sweep sits on an extremum") and the docstring ("half a Rabi period from the start") say "start", but the code means x = 0. The comment should be corrected (inference; the behaviour is right).
- **Same formula as Qibocal.** Qibocal's (T/2)·(round(1 + φ/π) − φ/π) ([qibocal] utils.py:273–295) is algebraically the same, since round(1 + u) = 1 + round(u). Qiskit and Quantify instead use 1/(2f) and ignore the phase (§2). That works only if the oscillation is anchored at x = 0, which the phase handling here generalizes.
- **Finding F2 (known limit, already in `pulse-shapes.md` §3.3):** with **Gaussian edges**, the edges alone rotate the qubit by θe. Once θe > π/2, the extremum nearest x = 0 *is* the π point, and the code returns the next extremum, which is the 2π point. Our script: θe = 0.45π gives 0.220 (true 0.220), θe = 0.55π gives **0.579** (true 0.180), θe = 0.8π gives **0.480** (true 0.080) **(computed)**. **(inference)** The root cause is the sign ambiguity: without knowing which extremum is \|0⟩, the code has to assume the one nearest x = 0. A g reference, or a known sign as in F1, would let the code pick the extremum whose signal is nearest \|0⟩ and remove the limit.
- **Other points** (no bugs):
  - The decay is referenced to x = 0, as `pulse-shapes.md` §3.3 notes.
  - The R² gate uses the centred, normalized data, which is correct.
  - Start > Stop is not forbidden by `RabiParams` (rabi.py:26–27). With a descending x, `not x[0] <= x_pi <= x[-1]` always rejects the π point. The result is no π point, not a wrong one (inference; not run on hardware).

### 4.4 Tr2 phase (line 188)

`angle(s21 · e^(−i·arg mean))` is the phase relative to the mean, which removes the arbitrary absolute phase (`s21.md` §7). It is monotonic in p, so it is a valid second view (§1.3). It shares the projection's lack of a physical sign: its direction depends on which side of the origin the segment passes.

---

## Recommendation for this app

Keep PCA as the default reduction. It is the best linear one-dimensional reduction without references. Physics says the averaged path is a straight segment for a two-level qubit (§1.2). Two of the frameworks we read (Qibocal, LabOne Q without calibration traces) do exactly this, and Qiskit does the same with an SVD. The π point it gives is independent of sign, cable phase and readout frequency. Avoid magnitude as a Rabi trace: it can return half the π pulse (§1.3). What PCA lacks is a physical sign, a physical zero and a stable axis. Those come from references, which is what every framework uses when it has them.

**Decisions for the user:**

1. **Tr1's sign (F1).** Orient the projection so it increases away from the zero-drive end (Quantify's rule, no extra measurement)? Fix it to an arbitrary convention? Or leave it?
2. **What Tr1/Tr2 offer.** Keep "projection + phase", or add a trace selector for raw I, Q, \|S\| and phase, so the user can see when the path is curved or the axis is noise? An I/Q-plane plot of the sweep (as Qibocal draws, [qibocal] utils.py:115–130) would show curvature and the axis directly.
3. **Stored rotation per chip.** Save the PCA angle (and, with F1's sign rule, the direction) with the chip's readout settings. Later runs and other measurements (T1, Ramsey) would then reuse it instead of refitting, which makes traces comparable. It is only valid for the same readout frequency, power and wiring.
4. **References in the sweep.** Add optional g/e calibration points to the Rabi program (no pulse, and a π pulse at the stored π gain) and normalize to 0 at \|0⟩ and 1 at \|1⟩, as LabOne Q does by default and Quantify supports. This also fixes F2. It costs two points per sweep and needs a π pulse first.
5. **Single-shot readout** (not built). Once it exists, do as QICK's demo and Qibocal do: calibrate the g/e angle and threshold, then report population via `acquire(threshold, angle)` ([lib] qick_asm.py:2096–2111). Rabi becomes "excited population". That needs `acquire` per-shot data and a calibration step in the app.
6. **The F2 limit.** Leave it documented as it is, or fix it through 1 or 4?
7. **Fix the code comment** at rabi.py:236 and the docstring: the reference is x = 0, not the sweep start.

---

## What we could not verify

- **The eigenvector sign convention of `numpy.linalg.eigh`** is not documented. The pattern in §3 and §4.2 was observed on numpy 2.5.4 with this env's LAPACK and may differ elsewhere.
- **scikit-learn's PCA sign rule** (used by Qibocal): not checked. The system scikit-learn failed to import, and the project env has none.
- **Readout of coherences beyond the dispersive approximation**: no source found that sizes it (§1.2).
- **Gambetta et al. 2007**, "Protocols for optimal readout…" (cited by [Blais21] for non-Gaussian marginals under T1): not read.
- **Hardware behaviour.** Nothing here was run on the board. The numbers marked **(computed)** come from synthetic data through our functions. We have not checked whether our bench sees noise anisotropy or drift large enough to tilt the axis.
- **Other frameworks** (Labber, QCoDeS-based lab code, Presto, the Schuster-lab QICK experiment repos): not surveyed.
