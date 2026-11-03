# Marki MMIQ-0416LS I/Q mixer (transmon line)

Source: Marki datasheet, Rev -, 2021-03-01 (`~/Documents/Balseiro/Tesis/Mixers/MMIQ-0416LS-Passive GaAs MMIC IQ Mixer.pdf`).

| Parameter | Value | Datasheet page |
|---|---|---|
| RF and LO range | 4–16 GHz | 6 (Electrical Specifications) |
| IF (I and Q) range | DC–6 GHz | 6 |
| Relative IF response at 3 GHz | about −0.5 to −1 dB (8 GHz RF) | 8 (Relative IF Response) |
| LO drive | 7–16 dBm, 13 nominal | 5 (Recommended Operating Conditions) |
| Max RF/IF input | 6 dBm (recommended), 26 dBm absolute | 5 |
| Conversion loss | about 8–10 dB at 7–10 GHz (USB/LSB I+Q upconversion) | 8–9 |
| Upconversion sideband suppression (uncalibrated) | about 25–30 dBc at 7–10 GHz | 8–9 |
| I/Q phase balance | about 92–95° at 6–10 GHz | 9 |
| I/Q amplitude balance | about 0 dB at 6–12 GHz | 9 |
| LO to RF isolation | about 50–60 dB (LO 6–8 GHz) | 7 |

## Frequency plan for the transmon (readout ≈ 7 GHz, qubit ≈ 10 GHz, LO ≤ 7 GHz)

- One LO at about 6.8 GHz, upper sideband for both tones:
  - readout IF ≈ 0.2 GHz (also within the ADC's first Nyquist zone, ≤ 2.21 GHz, after real down-conversion),
  - qubit IF ≈ 3.2 GHz (within the DACs' first Nyquist zone, ≤ 4.9 GHz, and the mixer's 6 GHz IF range).
- The readout tone's image (LO − IF ≈ 6.6 GHz) is suppressed only about 25–30 dB uncalibrated; check it doesn't land on another resonator.
- Phase imbalance of 2–5° means the app must calibrate the I/Q phase offset and gain ratio per LO frequency.
