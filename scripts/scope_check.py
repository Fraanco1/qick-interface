"""Check the qubit pulses on the oscilloscope (manual; the app must not be running).

Wiring: DAC_A -> a scope channel (CH1 unless given), PMOD0_0 -> scope CH2, DAC_B -> ADC_D (loopback), and
the scope's USB to the board (served by board/qick_service.py as "scope"). Tones are at 50-100 MHz so the
scope (200 MHz, 1 GS/s) shows the carrier. Sections:
  1-2. Two-tone and Rabi qubit pulses (flat, Gaussian, Gaussian edges) on DAC_A as a control line (fluxonium-like);
  3.   qubit pulse, delay and readout pulse all on DAC_A, no control line (transmon-like);
  4.   time between shots.
This script changes the scope's trigger, timebase and vertical settings.

    .venv/bin/python scripts/scope_check.py [channel of DAC_A, e.g. CH3]
"""
import sys
import time

import numpy as np
import Pyro4

from qick_interface.board import QickBoard
from qick_interface.measurements.rabi import Rabi, RabiParams
from qick_interface.measurements.two_tone import TwoTone, TwoToneParams
from qick_interface.profiles import SetupProfile

board = QickBoard()
scope = Pyro4.Proxy(Pyro4.locateNS(host="192.168.3.1", port=8888).lookup("scope"))
print(scope.query("*IDN?"))
profile = SetupProfile(chip="Scope check", lo_mhz=None, readout_dac="DAC_B", readout_adc="ADC_D",
                       control_dac="DAC_A", time_of_flight_us=0.292)
results = []
DAC_A = sys.argv[1] if len(sys.argv) > 1 else "CH1"  # the scope channel DAC_A is cabled to


def check(name, value, expected, tol, unit=""):
    good = abs(value - expected) <= tol
    results.append(good)
    print(f"  [{'PASS' if good else 'FAIL'}] {name}: {value:.4g}{unit} (expected {expected:.4g} ± {tol:.2g}{unit})")


def setup_scope(window_s):
    for cmd in (f"SELECT:{DAC_A} ON", "SELECT:CH2 ON", f"{DAC_A}:COUPLING DC", "CH2:COUPLING DC", f"{DAC_A}:POSITION 0",
                "CH2:SCALE 1.0", "CH2:POSITION -3", "HORIZONTAL:DELAY:MODE OFF", "HORIZONTAL:POSITION 10",
                "ACQUIRE:MODE SAMPLE", "TRIGGER:A:TYPE EDGE", "TRIGGER:A:EDGE:SOURCE CH2",
                "TRIGGER:A:EDGE:SLOPE RISE", "TRIGGER:A:LEVEL:CH2 0.9", "TRIGGER:A:MODE NORMAL",
                f"HORIZONTAL:SCALE {window_s / 10:.3e}"):
        scope.write(cmd)


def acquire():
    """One triggered acquisition of DAC_A's channel and CH2: (t, dac_a, ch2)."""
    scope.write("ACQUIRE:STOPAFTER SEQUENCE")
    scope.write("ACQUIRE:STATE RUN")
    t0 = time.time()
    while scope.query("ACQUIRE:STATE?") != "0":
        if time.time() - t0 > 5:
            raise RuntimeError("The scope did not trigger on CH2 (PMOD) within 5 s.")
        time.sleep(0.05)
    t, ch1 = scope.waveform(DAC_A)
    _, ch2 = scope.waveform("CH2")
    return np.asarray(t), np.asarray(ch1), np.asarray(ch2)


def acquire_ranged():
    """Acquire, adjusting DAC_A's volts/div until the pulse fills the screen without clipping."""
    scale = 0.2
    for _ in range(6):
        scope.write(f"{DAC_A}:SCALE {scale:.3g}")
        t, ch1, ch2 = acquire()
        peak = np.max(np.abs(ch1))
        if peak > 4.8 * scale:
            scale *= 2.5
        elif peak < 1.5 * scale:
            scale /= 2.5
        else:
            break
    return t, ch1, ch2


def envelope(t, v, f_mhz):
    """|analytic signal| of v, smoothed over one carrier period."""
    v = v - np.median(v)
    spectrum = np.fft.fft(v)
    h = np.zeros(v.size)
    h[0] = 1
    h[1:(v.size + 1) // 2] = 2
    if v.size % 2 == 0:
        h[v.size // 2] = 1
    env = np.abs(np.fft.ifft(spectrum * h))
    n = max(1, int(round(1 / (f_mhz * 1e6) / (t[1] - t[0]))))
    return np.convolve(env, np.ones(n) / n, mode="same")


def above(t, x, level):
    """Times x first rises above and last falls below `level` (interpolated)."""
    on = np.flatnonzero(x >= level)
    i, j = on[0], on[-1]
    rise = t[i - 1] + (level - x[i - 1]) / (x[i] - x[i - 1]) * (t[i] - t[i - 1])
    fall = t[j] + (x[j] - level) / (x[j] - x[j + 1]) * (t[j + 1] - t[j])
    return rise, fall


def marker_edges(t, ch2):
    """PMOD rising and falling edges at half height. The levels come from the resting level and the
    top, not min/max: the line rings for ~100 ns after each edge (down to −1.8 V, back up to +0.8 V).
    A ring that crosses again within 5 µs of an edge is not a new edge."""
    low, high = np.median(ch2), np.percentile(ch2, 99.9)
    up = ch2 >= (low + high) / 2
    rises, falls = (t[1:][up[1:] & ~up[:-1]], t[1:][~up[1:] & up[:-1]])
    keep = lambda edges: edges[np.r_[True, np.diff(edges) > 5e-6]] if edges.size else edges
    return keep(rises), keep(falls)


def carrier_mhz(t, v):
    v = v - v.mean()
    n = 16 * v.size
    f = np.fft.rfftfreq(n, t[1] - t[0])
    return f[np.argmax(np.abs(np.fft.rfft(v * np.hanning(v.size), n)))] / 1e6


def pulse(t, ch1, ch2, f_mhz):
    """The qubit pulse on DAC_A and the PMOD marker on CH2, in µs from the PMOD rising edge."""
    rises, falls = marker_edges(t, ch2)
    marker_on = rises[np.argmin(np.abs(rises))]  # the edge the scope triggered on
    marker_off = falls[falls > marker_on][0]
    env = envelope(t, ch1, f_mhz)
    start, end = above(t, env, env.max() / 2)
    flat = (t > start + 0.25 * (end - start)) & (t < end - 0.25 * (end - start))
    return {"marker_us": (marker_off - marker_on) * 1e6, "start_us": (start - marker_on) * 1e6,
            "fwhm_us": (end - start) * 1e6, "amplitude_v": np.median(env[flat]), "peak_v": env.max(),
            "freq_mhz": carrier_mhz(t[flat], ch1[flat]), "high_v": ch2.max()}


def play(program):
    board.play(program)
    time.sleep(0.3)


def show(name, p):
    print(f"\n{name}: pulse {p['fwhm_us']:.3f} µs (FWHM) at {p['freq_mhz']:.2f} MHz, {p['amplitude_v'] * 1e3:.0f} mV "
          f"(peak {p['peak_v'] * 1e3:.0f} mV); starts {p['start_us'] * 1e3:+.0f} ns from the PMOD edge; "
          f"PMOD high {p['marker_us']:.3f} µs at {p['high_v']:.2f} V")


base_tt = TwoToneParams(qubit_start_mhz=50, qubit_stop_mhz=50, readout_freq_mhz=550, qubit_length_us=2.0,
                        qubit_gain=0.5, scope_qubit_freq_mhz=50.0)
try:
    # 1. Two-tone: a flat pulse of the set length and frequency, with PMOD high exactly as long
    setup_scope(4e-6)
    play(TwoTone.sequence(board.soccfg, profile, base_tt))
    t, ch1, ch2 = acquire_ranged()
    ref = pulse(t, ch1, ch2, 50)
    show("Two-tone, 50 MHz, 2 µs, gain 0.5", ref)
    check("pulse length", ref["fwhm_us"], 2.0, 0.01, " µs")
    check("carrier", ref["freq_mhz"], 50.0, 0.1, " MHz")
    check("PMOD high for the pulse length", ref["marker_us"], 2.0, 0.01, " µs")
    latency_ns = ref["start_us"] * 1e3

    play(TwoTone.sequence(board.soccfg, profile, base_tt.model_copy(update={"qubit_gain": 0.25})))
    p = pulse(*acquire(), 50)
    show("Two-tone, gain 0.25", p)
    check("amplitude ratio gain 0.25 / 0.5", p["amplitude_v"] / ref["amplitude_v"], 0.5, 0.02)
    check("same start from the PMOD edge", p["start_us"] * 1e3, latency_ns, 3, " ns")

    play(TwoTone.sequence(board.soccfg, profile, base_tt.model_copy(update={"scope_qubit_freq_mhz": 100.0})))
    p = pulse(*acquire_ranged(), 100)
    show("Two-tone, 100 MHz", p)
    check("carrier", p["freq_mhz"], 100.0, 0.2, " MHz")

    # 2. Rabi: a flat pulse of the typed length; a Gaussian of the set σ at the typed gain
    rabi = RabiParams(qubit_freq_mhz=50, readout_freq_mhz=550, qubit_gain=0.5, sweep="length", scope_length_us=1.0)
    setup_scope(2e-6)
    play(Rabi.sequence(board.soccfg, profile, rabi))
    p = pulse(*acquire_ranged(), 50)
    show("Rabi length, 1 µs, gain 0.5", p)
    check("pulse length", p["fwhm_us"], 1.0, 0.01, " µs")
    check("PMOD high for the pulse length", p["marker_us"], 1.0, 0.01, " µs")
    check("amplitude matches two-tone at the same gain", p["amplitude_v"] / ref["amplitude_v"], 1.0, 0.03)

    gauss = rabi.model_copy(update={"sweep": "amplitude", "sigma_us": 0.1, "scope_gain": 0.5})
    setup_scope(1e-6)
    play(Rabi.sequence(board.soccfg, profile, gauss))
    p = pulse(*acquire_ranged(), 50)
    show("Rabi amplitude, Gaussian σ 0.1 µs, gain 0.5", p)
    check("Gaussian FWHM (2.355 σ)", p["fwhm_us"], 0.2355, 0.01, " µs")
    check("PMOD high for 4σ", p["marker_us"], 0.4, 0.01, " µs")
    check("peak / flat pulse at the same gain (QICK: 0.5)", p["peak_v"] / ref["amplitude_v"], 0.5, 0.03)

    # Gaussian edges (flat_top): 4σ rise, the flat part, 4σ fall; QICK plays the flat part at half the gain
    edges = rabi.model_copy(update={"shape": "gaussian edges", "edge_sigma_us": 0.02, "scope_length_us": 0.3})
    setup_scope(1e-6)
    play(Rabi.sequence(board.soccfg, profile, edges))
    p = pulse(*acquire_ranged(), 50)
    show("Rabi length, Gaussian edges σ 20 ns, flat 0.3 µs, gain 0.5", p)
    check("FWHM (flat + 2 × 1.177 σ)", p["fwhm_us"], 0.3 + 2 * 1.1774 * 0.02, 0.01, " µs")
    check("PMOD high for the whole pulse (flat + 8σ)", p["marker_us"], 0.3 + 8 * 0.02, 0.01, " µs")
    check("flat part / flat pulse at the same gain (QICK: 0.5)", p["amplitude_v"] / ref["amplitude_v"], 0.5, 0.03)

    # 3. Transmon-like: qubit pulse, delay and readout pulse on the same DAC (no control line)
    transmon = profile.model_copy(update={"readout_dac": "DAC_A", "control_dac": None})
    for name, params, qubit_us in (
            ("Gaussian σ 0.1 µs, then readout after the default delay",
             RabiParams(qubit_freq_mhz=50, readout_freq_mhz=90, sigma_us=0.1, scope_gain=0.5, readout_gain=0.5,
                        readout_pulse_us=1.0), 0.4),
            ("flat 0.3 µs, then a half-height readout after 200 ns",
             RabiParams(sweep="length", qubit_freq_mhz=50, readout_freq_mhz=90, qubit_gain=0.5, scope_length_us=0.3,
                        readout_gain=0.25, readout_pulse_us=1.0, readout_gap_us=0.2), 0.3)):
        setup_scope(2e-6)
        play(Rabi.sequence(board.soccfg, transmon, params))
        t, ch1, ch2 = acquire_ranged()
        rises, _ = marker_edges(t, ch2)
        t0 = rises[np.argmin(np.abs(rises))] + latency_ns * 1e-9  # when DAC_A starts the shot
        qubit_end = t0 + qubit_us * 1e-6
        readout_start = qubit_end + params.readout_gap_us * 1e-6
        env = envelope(t, ch1, 50)
        middle = (t > readout_start + 0.2e-6) & (t < readout_start + (params.readout_pulse_us - 0.2) * 1e-6)
        level = np.median(env[middle])
        after = t > qubit_end + 10e-9  # past the qubit pulse (a flat one drops below half the readout level)
        on = after & (env > level / 2)
        start, end = t[np.flatnonzero(on)[0]], t[np.flatnonzero(on)[-1]]
        qubit = (t > t0 + 0.25 * qubit_us * 1e-6) & (t < t0 + 0.75 * qubit_us * 1e-6)
        print(f"\nTransmon-like, {name}: readout {(start - t0) * 1e9:.0f}–{(end - t0) * 1e9:.0f} ns after the shot starts")
        check("readout starts after qubit pulse + delay", (start - t0) * 1e6, qubit_us + params.readout_gap_us, 0.006, " µs")
        check("readout length", (end - start) * 1e6, params.readout_pulse_us, 0.01, " µs")
        check("readout carrier", carrier_mhz(t[middle], ch1[middle]), 90.0, 0.2, " MHz")
        check("qubit carrier", carrier_mhz(t[qubit], ch1[qubit]), 50.0, 1.0, " MHz")

    # 4. Time between shots: PMOD edges over a few milliseconds
    for delay in (100.0, 500.0):
        setup_scope(4 * (delay + 5) * 1e-6)
        play(TwoTone.sequence(board.soccfg, profile, base_tt.model_copy(update={"final_delay_us": delay})))
        t, _, ch2 = acquire()
        edges, _ = marker_edges(t, ch2)
        period = np.median(np.diff(edges)) * 1e6
        print(f"\nRepetition delay {delay:g} µs: {len(edges)} PMOD edges, one every {period:.2f} µs")
        shot = 2.0 + 0.05 + max(2.0, 0.292 + 1.5)  # qubit pulse, gap, readout pulse (or window)
        check("shot period", period, delay + shot, 1.0, " µs")
finally:
    board.silence()
    scope.write("ACQUIRE:STOPAFTER RUNSTOP")
    scope.write("ACQUIRE:STATE RUN")

print(f"\nPMOD-to-DAC_A latency: the pulse starts {latency_ns:+.0f} ns from the PMOD edge (cables included).")
print(f"{sum(results)} of {len(results)} checks passed")
