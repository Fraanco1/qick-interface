# Keysight PNA-X (N5242B): how it works and how its UI behaves

Primary-source notes for making QICK Analyzer behave like the PNA-X the lab knows. Every claim cites Keysight's own VNA help, SCPI reference or an application note. Read in November 2026.

**About the sources.** Keysight now serves the PNA family help (N52xxB, which includes the N5242B PNA-X) at `https://helpfiles.keysight.com/csg/NA520xA/…`. Every `…/csg/N52xxB/<page>` URL returns *301 Moved Permanently* to the matching `…/csg/NA520xA/<page>` (checked with curl). The old `na.support.keysight.com/pna/help/…` host redirects to a generic support page. The help is shared across the family. Where a feature is specific to a model, the help says so, and these notes repeat that.

**Source tags** (append `#`/section names as given):

| Tag | URL |
|---|---|
| `[Sweep]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Sweep.htm |
| `[Points]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/DPoints.htm |
| `[Trig]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Trigger.htm |
| `[Noise]` | https://helpfiles.keysight.com/csg/NA520xA/S2_Opt/Trce_Noise.htm (Averaging, IF Bandwidth, Smoothing) |
| `[Fast]` | https://helpfiles.keysight.com/csg/NA520xA/S2_Opt/Fast_Swp.htm |
| `[Params]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Measurement_Parameters.htm |
| `[Power]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Power_Level.htm |
| `[Errors]` | https://helpfiles.keysight.com/csg/NA520xA/S3_Cals/Errors.htm |
| `[CalType]` | https://helpfiles.keysight.com/csg/NA520xA/S3_Cals/Select_Cal.htm |
| `[CalWiz]` | https://helpfiles.keysight.com/csg/NA520xA/S3_Cals/Calibration_Wizard.htm |
| `[CorrLvl]` | https://helpfiles.keysight.com/csg/NA520xA/S3_Cals/Error_Correction_and_Interpolation.htm |
| `[Format]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Data_Format.htm |
| `[Scale]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Scale.htm |
| `[PhaseAcc]` | https://helpfiles.keysight.com/csg/NA520xA/S2_Opt/Phase_Accy.htm (Electrical Delay, Phase Offset, aliasing) |
| `[GD]` | https://helpfiles.keysight.com/csg/NA520xA/Tutorials/Group_Delay6_5.htm |
| `[Math]` | https://helpfiles.keysight.com/csg/NA520xA/S4_Collect/Math_Operations.htm |
| `[Mkr]` | https://helpfiles.keysight.com/csg/NA520xA/S4_Collect/Markers.htm |
| `[TCW]` | https://helpfiles.keysight.com/csg/NA520xA/S0_Start/Traces_Channels_and_Windows.htm |
| `[Screen]` | https://helpfiles.keysight.com/csg/NA520xA/S1_Settings/Customize_Your_Analyzer_Screen.htm |
| `[Save]` | https://helpfiles.keysight.com/csg/NA520xA/S5_Output/SaveRecall.htm |
| `[SCPI-Swp]` | https://helpfiles.keysight.com/csg/NA520xA/Programming/GP-IB_Command_Finder/Sense/Sweep_SCPI.htm |
| `[SCPI-Data]` | https://helpfiles.keysight.com/csg/NA520xA/Programming/GP-IB_Command_Finder/Calculate/Data.htm |
| `[SCPI-FIFO]` | https://helpfiles.keysight.com/csg/NA520xA/Programming/GP-IB_Command_Finder/SystFIFO.htm |
| `[Ex-FIFO]` | https://helpfiles.keysight.com/csg/NA520xA/Programming/GPIB_Example_Programs/Setup_FastCW_and_FIFO.htm |
| `[AN-DR]` | Keysight AN 5980-2778, *Understanding and Improving Network Analyzer Dynamic Range*, https://www.keysight.com/us/en/assets/7018-06837/application-notes/5980-2778.pdf. Only the introduction could be read; WebFetch got that much, and curl received HTML instead of the PDF. |

Statements marked **(inference)** are our own reasoning, not something Keysight states.

---

## 1. Receivers and how S21 is computed

### Receivers
- Every model has **reference receivers** and **test-port receivers** ([Params] "Receiver Measurements"):
  - R1…R4 are the reference receivers. They "measure the signal as it leaves the analyzer source", so R1 measures the signal out of Port 1.
  - A, B, C, D are the test-port receivers. They "measure the signal out (or reflecting off) of the DUT". A measures the signal into port 1 and B the signal into port 2.
- Logical, "8510-style" notation ([Params] "Receiver Notation"): **aN** is the reference receiver of logical port N and **bN** is its test-port receiver. "b12/a1" is a ratioed measurement; "b10" alone is unratioed.

### S-parameters are predefined ratios
- "S-parameters are actually predefined ratio measurements. For example S11 is A/R1" ([Params] "Ratioed Measurements").
- Transmission is "B over R1" (B/R1) ([Errors] "Frequency Response Transmission Tracking Error"). So **S21 = B/R1 = b2/a1**, with the source on port 1.
- S<sub>out,in</sub>: *out* is the port whose receiver measures, *in* is the port where the source is applied. The analyzer switches the source between ports to measure forward and reverse ([Params] "S-Parameters").

### Unratioed (absolute) receivers
- Unratioed means one receiver with denominator 1. It "measures the absolute power going into" that receiver ([Params] "Unratioed (Absolute Power) Measurements").
- "Measuring phase using a single receiver yields meaningless data. Phase measurements must be a comparison of two signals" (same section).
- Averaging an unratioed trace: "The noise floor does not drop … as on ratioed measurements", and "Phase results may tend toward 0" because single-receiver phase is random ([Noise] "Averaging", Notes, "Unratioed measurements").
- Log Mag units for unratioed traces can be dBm, dBmV, dBµV or dBmA. Lin Mag can be U (ratio), W, V or A ([Format] "Format Unit").

### What an uncalibrated S21 contains
With correction off, B/R1 still contains every systematic error. For transmission these are **isolation** (leakage into B), **load match**, and **frequency-response transmission tracking**. Tracking is the difference between the B and R1 paths: "signal-separation devices, test cables, adapters, variations between the reference and test signal paths" ([Errors] "Systematic Errors", "Frequency Response Transmission Tracking Error"). Ratioing to R1 removes the source's own amplitude and phase drift. It does not remove the cables or the receiver path.

Error classes ([Errors]):
- **Systematic** errors are repeatable, so calibration characterizes and removes them.
- **Random** errors (noise, switch and connector repeatability) cannot be removed by correction.
- **Drift** (mostly thermal) is removed only by recalibrating.

### Calibration levels
These are relevant to S21 ([CalType] table and per-type sections):

| Cal type | Standards | Corrects | Accuracy |
|---|---|---|---|
| **Thru / Transmission Response** (isolation optional) | THRU (plus a LOAD per port for isolation) | Transmission tracking (and isolation) | Low |
| **Enhanced Response** (1→2 or 2→1) | OPEN/SHORT/LOAD on the source port, plus a THRU | Source-port directivity and source match, plus transmission tracking. Load match is used only to derive the tracking term. One direction only, so no reverse sweep | High |
| **Full 2-port SOLT** | SHORT, OPEN, LOAD, THRU (or ECal) | All 12 terms: directivity, source match, load match, isolation, reflection and transmission tracking, ×2 directions | High |
| TRL family | THRU, REFLECT, LINE | Same as SOLT | Very high |

- A **response cal** is "one term" and "does not correct for impedance mismatches" ([CorrLvl] "C Resp").
- Response cal **Normalize**: "After Normalize is pressed and the Cal is complete, the data trace is flat when the same physical connections are present … similar to Data/Memory, except that the response cal is saved with Cal data and can be applied to other like measurements" ([CalWiz] "Unguided Calibration (Response Cal)", Measure Mechanical Standards dialog).
- Without a cal kit, **Memory → Normalize** "performs the same function as Data=>Memory, then Data / Memory" ([Math] "Math / Memory"). Data/Memory is a complex division on linear data before formatting. Keysight recommends it "for normalization purposes, such as when comparing S21 traces 'before' and 'after'" ([Math] "(Data / Memory) and (Data - Memory)").
- Full 2-port correction needs forward **and** reverse sweeps even when only S21 is shown. N-port cal needs N(N−1) sweeps ([Fast] "Measurement Calibration Choice"). A response or 1-port cal costs about as much time as no correction (same section).
- **Correction-level indicator** on the status bar ([CorrLvl] "Viewing Correction Level"):
  - "C Resp" for a response cal.
  - "C-delta" when sweep time, IF bandwidth, stepped/analog mode or attenuator settings change after the cal ("calibration is uncertain").
  - Correction turns **off** if the span grows, or if start, stop or points change with interpolation off.
- Power level: "Error correction is fully accurate only for the power level at which a measurement calibration was performed". Ratioed measurements stay nearly accurate if the power changes within the same attenuator range ([Power] "Receiver Attenuation" area).

### Source level, attenuators and receiver attenuators
- Port power is set at the source output. Accurate power at the DUT needs a **Source Power Calibration** ([Power] "Power Settings"). The status bar shows **LVL** when the source cannot reach the requested power ([Power] "Source Unleveled").
- **Source attenuators.** With manual attenuation the port power covers a 60 dB window: 0 dB attenuation gives −30…+30 dBm, 10 dB gives −40…+20 dBm. Mechanical attenuators are "NOT allowed to switch continuously" ([Power] "Power and Attenuators").
- The reference receiver sits ahead of the source attenuator, so the PNA mathematically offsets the reported R-receiver power by the attenuation ([Power], note after the default-attenuation table).
- **Receiver attenuators** (an option) sit in front of A/B/C/D "to protect the VNA test port receivers from damage or compression". By default the reported power is offset by the attenuation ([Power] "Receiver Attenuators dialog box help").
- RF power is muted during band crossings and during retrace (the jump from stop back to start) ([Power] "Power ON and OFF during Sweep and Retrace").

---

## 2. IF bandwidth

- The received signal is converted to an IF and filtered digitally. **IFBW** is that filter's bandwidth, adjustable "down to a minimum of 1 Hz" ([Noise] "IF Bandwidth").
- "Each tenfold reduction in IF bandwidth lowers the noise floor by 10 dB. However, narrower IF bandwidths cause longer sweep times" (same section). The minimum measurable power is "set by the receiver's noise floor", which "depends on the IF bandwidth, averaging, and the test set configuration" ([AN-DR] "Dynamic range defined").
- Values common to all models: 1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 100, 150, 200, 300, 500, 700 Hz, 1k … 600k, 1M … 15M ([Noise] "IF Bandwidth dialog box help").
  - The 1-2-3-5-7 Hz sequence continues up to 500 kHz. Then come 280k, 360k and 600k, then 1M, 1.5M, 2M, 3M, 5M, 7M, 10M, 15M.
  - IFBWs above 600 kHz are meant for wideband pulsed measurements. They "do NOT provide faster sweep speeds for non-pulsed measurements" (same).
- Per channel; each segment can have its own IFBW. Changing IFBW after a cal gives "C-delta" ([Noise] "IF Bandwidth").
- **IFBW Shape:** Standard (side lobes ≈ −32 dBc), Gaussian (slower, very low side lobes), Rectangular (fastest, ≈ −13 dBc) ([Noise] "IFBW Shape").
- **LF Auto BW** (on by default) lowers the IFBW automatically at low frequencies ([Noise] "LF Auto BW").
- IFBW ≤ 1 kHz forces **stepped** sweep ([Sweep] "Sweep Mode").
- Averaging versus IFBW: "For minimizing very low noise, Averaging is more effective than reducing IF bandwidth. Generally, Averaging takes slightly longer" ([Noise] "Effects of Sweep Average").
- **(inference)** Per-point acquisition time scales roughly as 1/IFBW. For our boxcar integration of length τ, the equivalent noise bandwidth is about 1/τ. So "IFBW = 1/readout length" is the natural mapping, and 10× longer integration gives a 10 dB lower noise floor, as on the PNA.

---

## 3. Sweeps

### Sweep types
Set with `SENS:SWE:TYPE LINear|LOGarithmic|POWer|CW|SEGMent|PHASe` (UI path: **Sweep > Main > Sweep Type**) ([Sweep] "Sweep Type"; [SCPI-Swp] `SENSe:SWEep:TYPE`).

- **Linear Frequency:** start/stop (or center/span), points, power, IFBW. Shown on "a standard grid with ten equal horizontal divisions".
- **Log Frequency:** the source steps logarithmically and the x-axis is logarithmic. "Usually slower than a continuous sweep."
- **Power Sweep:** start and stop power at one **CW Freq**, swept in discrete steps. The range must fit one attenuator setting, because attenuators are not switched during a sweep. A preference decides whether power stays at the start or stop level at the end of the sweep.
- **CW Time:** "Sets the analyzer to a single frequency, and the data is displayed versus time." The parameters are CW Freq, Power, **Sweep Time** ("the duration of the measurement, which is displayed on the X-axis"), Points and IFBW.
- **Segment Sweep:** a table of non-overlapping frequency segments (overlaps are allowed only with "Arbitrary Segments", and then stepped mode only). Each segment can have its own points, power, IFBW, sweep time, dwell and delay. "X-Axis Point Spacing" spreads points evenly. The point limit is the total per channel.
- **Phase Sweep:** sweeps the phase between sources, −360° to +360°.

### Points
- 1 to 100,003 per channel; the default is **201** ([Points]; [SCPI-Swp] `SWEep:POINts`, default 201).
- Calibrate with the same number of points you measure with ([Points] Tips).

### Sweep time, dwell and delay
- **Auto sweep time** keeps "the fastest sweep time possible". You can only make it slower. Entering 0 s returns to the fastest ([Sweep] "Sweep Time"). The maximum is 86,400 s (1 day). Typed values are rounded **up** to a value the analyzer can achieve (same note).
- **Dwell Time:** "the time the source stays at each measurement point before the analyzer takes the data". Stepped sweep only; maximum 20 s ([Sweep] "Sweep Setup / Time").
- **Sweep Delay:** "time to wait just before acquisition begins for each sweep", added to dwell and to any external-trigger delay ([Sweep]; [SCPI-Swp] `SWEep:DWELl:SDELay`).
- **Stepped vs Analog** ([Sweep] "Sweep Mode"; [SCPI-Swp] `SWEep:GENeration`, default Analog):
  - **Stepped:** "the source is tuned, then waits the specified Dwell time, then takes response data, then tunes the source to the next frequency point". More accurate for electrically long devices.
  - **Analog:** data is taken "AS the source is sweeping". Faster.
  - Auto mode may pick either, and the user cannot tell which. Stepped is forced for IFBW ≤ 1 kHz, among other cases.
- **Fast Sweep** shortens source settling at the cost of frequency accuracy and a few dB of amplitude error, which "substantially ratio out" for S-parameters. Off by default ([Sweep] "Fast Sweep"; [SCPI-Swp] `SWEep:SPEed`).
- **Standard vs Point sweep:** standard sweeps all points for one source port, then the other. Point sweep measures every parameter at each point before stepping on, and "the display trace is updated as each data point is measured" ([Sweep] "Sweep Sequence").
- A **Sweep Indicator** is drawn on the trace when sweep time ≥ 0.3 s, or with point triggering. It sits "on the last data point that was measured by the receiver" ([Sweep] "Sweep Time").

### CW Time in detail
- **x-axis:** time within one sweep, from 0 to Sweep Time ([Sweep] "Sweep Type / CW Time").
- **Point spacing:** **(inference)** Sweep Time / (Points − 1).
  - Minimum spacing: Keysight gives no number. Auto sweep time is "the fastest sweep time possible" for the current points, IFBW and so on. That makes the minimum spacing the per-point acquisition time at that IFBW plus overhead.
  - Longer Sweep Time spreads the same number of points over more time.
- The first point is not at t = 0: "the marker can not be set to 0 … because the marker indicates the time to acquire the first point of the trace" ([Mkr] "Marker Setup / Stimulus"). `SENS:SWE:TIME:STARt?` "Returns the time the first point of a Time Sweep is measured" ([SCPI-Swp]).
- **End of sweep:** a CW Time sweep is an ordinary sweep of N points.
  - Under **Internal + Continuous** triggering a new trigger is issued "as soon as the previous measurement is complete" ([Trig] "Trigger Source"). The channel immediately re-sweeps and the trace is redrawn from the left, overwriting the old one. With sweep time ≥ 0.3 s the sweep indicator shows the write position.
  - **(inference)** The re-arm gap between sweeps means the stream has small holes at the sweep boundaries. The display is a "rolling window that restarts", not a scrolling strip chart.
- **Marker functions** in CW Time: Marker→Start/Stop/Center/Span/CW Freq do not apply. Marker→Ref Level and Marker→Delay work in the Standard class ([Mkr] "Marker Functions" table).
- CITI files saved in CW Time cannot be recalled ([Save] "Recalling Data files").
- **Fast CW + FIFO, the truly gapless stream.** This is SCPI only, on N522xB and N524xB (the N5242B qualifies), and needs the FIFO option S93118A/B or S930900A/B.
  - `SENS:SWE:TYPE:FACW <n>` "Enables Fast CW sweep and sets the number of data points". It needs Sweep Type = CW and FIFO on. `-1` (2³²−1) means "infinite point count (i.e., go forever)" ([SCPI-Swp] `SWEep:TYPE:FACW`).
  - The 4 GB FIFO "can be emptied as it is being filled, which means that the VNA can be used to acquire an infinite amount of data".
  - FIFO data is "the raw data after averaging and ratioing has been applied, but prior to any calibration, formatting". `SYST:FIFO:DATA? n` returns re/im pairs and clears them ([SCPI-FIFO]).
  - Example sequence ([Ex-FIFO]): define A/R1 and B/R1, IFBW 600 kHz (≈400 kpts/s), point averaging count 1, then `SENS:SWE:MODE HOLD`, `SYST:FIFO ON`, `SYST:FIFO:DATA:CLEAR`, `SENS:SWE:TYPE CW` and `FACW`.

---

## 4. Triggering
UI path: **Trigger > Main > Trigger…**, or right-click Trig in the status bar ([Trig]).

- **Source**, global for all channels ([Trig] "Trigger Source"). "A valid trigger signal can be generated only when the analyzer is not sweeping."
  - **Internal:** "Continuous trigger signals are sent by the analyzer as soon as the previous measurement is complete."
  - **Manual:** one trigger per press of *Trigger!* or per command.
  - **External:** a BNC or AUX input.
- **Scope** ([Trig] "Trigger Scope"):
  - **Global:** every channel not in Hold is triggered. This is the default.
  - **Channel:** only the next non-Hold channel. This enables point mode.
  - **Active Channel.**
- **Channel trigger state**, per channel ([Trig] "Channel Trigger State"; [SCPI-Swp] `SWEep:MODE`, default CONTinuous):
  - **Continuous:** unlimited triggers.
  - **Groups:** N triggers, then Hold (N from 1 to 2e6).
  - **Single:** one trigger, then Hold.
  - **Hold:** none.
  - Continuous, Single and Hold apply to the **active channel only**.
- **Trigger mode** per signal; needs Manual or External source and Channel scope ([Trig] "Trigger Mode"):
  - **Channel:** all traces of the channel.
  - **Sweep:** all traces sharing a source port.
  - **Point:** one data point per trigger.
  - **Segment:** one segment per trigger.
- **Sweep order:** traces are swept in source-port order. Then triggering "continues to the next channel that is not in HOLD" ([Trig] "Trace Sweep Order").
- **Restart** stops the current sweep. A single channel in Continuous "starts sweeping the first sweep" again ([Trig] "Restart").
- **Saving data:** "always trigger a single measurement, and then allow the channel to go into Hold" before saving ([Save] "Save Data").
- Averaging and triggering are independent. "Setting averaging factor to 4 has NO effect on the number of triggers" ([Noise] Notes, "Triggering").

**Continuous CW Time stream on the front panel:**
1. Sweep Type CW Time.
2. Trigger Source Internal.
3. Channel in Continuous.

The instrument re-sweeps back-to-back and redraws each sweep. A gapless stream exists only through Fast CW + FIFO over SCPI (§3).

---

## 5. Averaging and smoothing ([Noise])

- **Sweep averaging:** "Each data point is based on the average of the same data point measured over consecutive sweeps."
  - After n = factor sweeps it keeps running as an exponential average: `NewAvg = NewData/n + OldAvg·(n−1)/n`. "Data from the first n sweeps … never diminishes to zero."
  - **Restart** clears the average.
  - An **Average Counter** on screen shows the number of sweeps averaged ("Sweep Averaging Formula", "Notes").
- **Point averaging:** each point is measured `factor` times and averaged before stepping to the next point. It restarts automatically each sweep, and the counter is **not** updated.
- **Factor:** 1 to 65,536, per channel ("Average Factor"; "Channel-wide scope"). Averaging acts on complex data, so it can be on during or after a cal without invalidating it ("Calibration" note).
- **Smoothing:** a moving average over adjacent points of the **formatted** trace. The aperture is set in points or as a % of span, per trace.
  - Auto-off in Polar and Smith.
  - "Do not use smoothing for high-resonance devices … It may introduce misleading information" ("Trace Smoothing", Tips).
  - UI path: **Avg BW > Smoothing**.

---

## 6. Formats, scale and delay

### Formats
UI path: **Format** hardkey, or right-click the trace status ([Format]).
- **Log Mag** (dB).
- **Lin Mag** (U for ratioed, W for unratioed).
- **Phase:** ±180°, "wraps every 180 degrees".
- **Unwrapped Phase:** unwrapped point to point. It is wrong if adjacent points differ by more than 180°.
- **Positive Phase:** 0–360°.
- **Group Delay** (s).
- **Real, Imaginary.**
- **SWR** (reflection only).
- **Polar, Smith, Inverse Smith.**
- **Complex.**
- UI path for formats: **Format > Format 1 or Format 2** ([Format] "How to set the Display Format").
- **Group delay:** −Δφ/Δω over a frequency **aperture**, which must be quoted alongside the result. A narrow aperture gives more detail but more noise ([GD] "What Is Aperture?"). Phase aliasing above 180° per step can flip the sign of the group delay ([PhaseAcc] "Spacing Between Frequency Points").

### Scale
UI path: **Scale > Main** ([Scale]).
- **Scale/div:** 0.001 to 500 dB/div. In Polar and Smith it sets the outer circle.
- **Reference Level:** −500 to 500 (dB).
- **Reference Position:** "Zero is the bottom line of the screen and ten is the top line. Default position is five (middle)." That gives **10 vertical divisions**. The x-axis also has "ten equal horizontal divisions" ([Sweep] "Linear Frequency").
- **Autoscale:** "the smallest possible scale factor that will allow all the displayed data to fit onto 80 percent of the vertical grid", with the reference value chosen to centre the trace. Stimulus and reference position are untouched. Double-clicking the y-axis labels autoscales. **Autoscale All** works on every trace in the window.
- **Scale Coupling:** Off (default), Window or All, for traces with the same format.
- **Mag Offset / Mag Slope** (dB, slope from 0 Hz): **Scale > Constants**.
- **Electrical Delay** ([PhaseAcc] "Electrical Delay"): "simulates a variable length of lossless transmission line … to compensate for the linear phase shift through a device", per trace. It is set in time or in distance with a velocity factor (coax or waveguide). UI path: **Scale > Electrical Delay**.
- **Phase Offset:** up to 360°, used like a reference level for phase. UI path: **Scale > Constants > Phase Offset** ([PhaseAcc] "Phase Offset").
- **Marker→Delay** sets electrical delay from the phase slope at the marker, which "effectively flattens the phase trace around the active marker". Ratioed measurements only ([Mkr] "Marker Functions").

---

## 7. Markers ([Mkr])

- **Count:** 15 regular markers plus 1 **Reference** marker per trace. UI path: **Marker > Marker 1-7 / 8-15 / Reference** ("Number of … Markers").
- **Types** ("Marker Setup"):
  - **Normal:** fixed x, follows y.
  - **Delta:** relative to the reference marker, which turns on automatically.
  - **Fixed:** frozen x and y, for before/after comparisons.
  - **Discrete:** only measured points; otherwise values are interpolated.
  - **Coupled:** All or Channel, matching markers on other traces by number.
  - **Noise marker:** value normalized to 1 Hz.
  - **Marker format:** can differ from the trace format, e.g. Log/Phase.
- **Search** (**Search** hardkey, or Marker Search dialog; "Search Type"):
  - Max and Min.
  - Peak, with excursion and threshold; also Peak Left/Right and Next.
  - Multi-Peak.
  - Target, Target Left/Right and Multi-Target, with transition +, − or both.
  - **Bandwidth** and **Notch**.
  - Compression, PSAT and PNOP.
  - **Search Range:** full span or a user span, shown as small triangles on the x-axis. "Search Within" uses a dragged zoom box.
- **Tracking:** "Check to cause the marker to search for the specified criteria with each new sweep." While tracking, the marker's stimulus cannot be moved by hand. Execute performs a single search.
- **Bandwidth/Notch search** ("Bandwidth Search", "Notch Search"):
  - Reference to the active marker or to the peak. The level is in dB, e.g. −3 dB.
  - Readouts: **BW** = High − Low, **Center** = (High + Low)/2, **Low**, **High**, **Q** = Center/BW, **Loss** = the value at the center.
  - Notch search is the dip version, which fits a hanger resonance in |S21|. **Log Mag only.**
- **Marker functions** (**Marker > Marker→Functions**): Marker→Start, Stop, Center, Ref Level, Delay, Span (from a delta marker), CW Freq. They "do not work with channels that are in CW or Segment Sweep mode", except as noted in the table in §3.
- **Readout:** large readout, active trace only, readouts per trace, decimal places, position. There is also a **Marker Table** ("How to change Marker Display settings").

---

## 8. UI layout

### Traces, channels and windows ([TCW])
- **Trace:** a series of data points. Settings are per trace: parameter, format, scale, smoothing, correction on/off, electrical delay, phase offset, trace math, markers.
- **Channel:** up to 500 channels hold traces. Settings are per channel: frequency range, power, calibration, IFBW, points, sweep, average, trigger (part of it). "All traces that are assigned to a channel share the same channel settings."
- **Window:** for viewing only. Up to 100 traces each, "completely independent of channels". The window number is in the lower-left corner. The **stimulus annotation** (channel, start, stop) is at the bottom of each window ([Screen] "Frequency/Stimulus").
- **Trace status labels** sit above the grid. Clicking one makes that trace and its channel active. Right-clicking gives Format, Scale and so on ([TCW] "How to Select a Trace"; [Format]).
- **New measurement dialog** (Meas): tabs S-Parameter, Receivers (Ratioed num/denom/source port, Unratioed), Waves (aN/bN). Options for channel number and "Create in New Window" ([Params] "New / Change Measurement dialog").

### Hardkey → softtab paths
These are the paths quoted in the help pages above:

| Group | Key paths seen in the help |
|---|---|
| Stimulus | **Freq**; **Power > Main** (Power Level, RF Power on/off, Port Power, Leveling & Offsets); **Sweep > Main** (Sweep Type, Number of Points), **Sweep > Sweep Timing**, **Sweep > Segment Table**; **Trigger > Main** |
| Response | **Meas** (S-parameter, receivers); **Format** (Format 1/2); **Scale > Main** (Scale, Ref Level, Ref Position, Autoscale, Coupling), **Scale > Constants** (Mag Offset/Slope, Phase Offset), **Scale > Electrical Delay**; **Display** (Display Setup, Window Setup, Customize Display); **Avg BW > Main** (Averaging, IF BW, LF Auto BW), **Avg BW > Smoothing**; **Cal > Main** (Basic Cal, Correction, Other Cals > Response Cal) |
| Marker/Analysis | **Marker** (Marker 1–7, 8–15, Reference, Marker→Functions); **Search** (Main: Max/Min, Peak, Target, Multi Peak & Target, Bandwidth & Notch, …, with Tracking); **Math/Memory** (Data→Memory, Normalize, Data/Mem) |
| Trace/Utility | **Trace** (Trace 1-7, Trace Setup, Trace Manager, Trace Title); **Save Recall** (Save Other > Save Data…); **System** (Main, Preferences) |

Sources: [Sweep], [Trig], [Power], [Scale], [PhaseAcc], [Noise], [CalWiz], [Mkr], [Math], [TCW], [Screen], [Save], [Format], each page's "Using Hardkey/SoftTab/Softkey" box.

### Status bar
Along the bottom ([Screen] "Status Bar"):
- active trace and active channel
- trigger source
- **channel trigger state** (Hold/Single/Continuous)
- **IF bandwidth**
- **correction level** (F = full, R = response, − = none, plus C-delta)
- reference (internal/external)
- source power cal
- Service indicator
- **RF power**
- display update
- error messages
- GPIB LCL/RMT
- clock

Many items can be right-clicked to change the setting. The **Average Counter** is shown per channel ([Noise]). **LVL** appears when the source is unleveled ([Power]).

---

## 9. Saving data ([Save])

- **File types:** **.prn**, **.sNp** (Touchstone v1.0), **.cti** (CITIfile), **.csv**, **.mdf** (MDIF). Path: **Save Recall > Save Other > Save Data…** ("File Type").
- **Data Type** ("Data Settings"):
  - **Corrected** is complex data after error correction and fixturing, before post-processing ("Tap 1").
  - **Formatted** is the displayed data ("Tap 2", FDATA), including math, gating, phase offset, mag offset and smoothing.
  - SCPI reads the same stages ([SCPI-Data]):
    - `SDATA`/`RDATA`: complex, corrected if correction is on. A different access point returns raw, uncorrected data.
    - `FDATA`: formatted, two numbers per point only for Polar and Smith.
    - `FMEM`/`SMEM`: memory.
- **sNp:**
  - The header carries model, firmware, date and "!Correction: S21(Full 2 Port SOLT,1,2)", followed by `# Hz S RI R 50` or `DB`/`MA`.
  - .s2p rows are `f, S11, S21, S12, S22` as re/im (or dB/ang, mag/ang) pairs.
  - Missing parameters are zero-filled (−200 dB).
  - "Response cals will save uncorrected data" ("SNP Data Output", "What is Saved").
- **.prn/.csv:** stimulus plus data pairs per parameter. PRN holds the formatted, corrected active trace only ("*.prn Files", "*.csv Files").
- **Memory traces:** cannot be saved to sNp. They can go to CTI, CSV or MDF with Scope = Displayed Traces (same; [Math]).
- **Recall:** recalled sNp/CITI data is shown in **Log Mag**, and the channel is put in **Hold** ("Recalling Data files").
- Instrument state and calibration are separate file types (.csa, .cst, .sta, .cal) ("Instrument State / Calibration Files").

---

## Implications for our app

### Copy these

1. **Name things the PNA way.**
   - "IF BW" is the readout integration bandwidth, about 1/readout length. Show it in the status bar.
   - "Sweep Time", "Points", "Dwell" for our settling wait, "Sweep Delay".
   - Trigger states **Continuous / Single / Hold / Groups**.
   - Avg factor with an on-screen **Average Counter**, and **Restart**.

2. **CW Time sweep type** (what the user calls a "continuous stream of S21"):
   - Inputs: CW Freq, Power, Points, Sweep Time (Auto = fastest), IFBW.
   - x-axis: 0…Sweep Time in seconds, 10 divisions. Point spacing is Sweep Time/(Points−1). Its floor is integration time plus per-point overhead, as with PNA Auto sweep time.
   - With **Continuous** triggering, re-sweep as soon as the last sweep finishes. Redraw the trace from the left over the old one, with a **sweep indicator** at the last written point.
   - Single → one sweep, then Hold (the state to save data in). Hold → freeze.
   - On the RFSoC we can do better than the PNA front panel. Keep the tone on and stream integrated IQ windows back-to-back in one QICK program (the "Fast CW + FIFO" equivalent). The UI can show either:
     - PNA-style per-sweep redraw. This is the default, because it is what users know.
     - Optionally, a scrolling strip chart.
   - First point at t > 0: label it as the end of the first integration window.

3. **Averaging semantics:**
   - Offer **Sweep** averaging: an exponential running mean once the count reaches the factor, with Restart.
   - Offer **Point** averaging: N repeats per point. This is our "averages per round". Our "rounds" correspond to sweep averaging.
   - Average complex IQ, never magnitudes.
   - Smoothing applies to the formatted trace only, never in Polar/Smith. Warn that smoothing distorts high-Q resonances.

4. **Formats and Scale:**
   - LogMag, LinMag, Phase (±180), Unwrapped, Group Delay with a stated aperture, Real, Imag, Polar.
   - Scale/div, Ref Level, Ref Position 0–10 (default 5).
   - Autoscale fits 80 % of the grid and centres the trace. Double-click the axis to autoscale.
   - Electrical Delay and Phase Offset under Scale. **Marker→Delay** flattens phase at the marker; our fitted-delay removal fits here.

5. **Markers:**
   - 15 + Reference per trace; Delta; Discrete vs interpolated.
   - Search Max/Min/Peak/Target with **Tracking** (re-search every sweep). Tracking Min on a CW-time trace is not useful; on frequency sweeps it is.
   - **Notch search** for hanger resonators: Center, BW, Q = Center/BW, Loss, level −3 dB. Log Mag only.
   - Marker→Center/Span/CW Freq/Ref Level. **Marker→CW Freq** is the natural way to go from a resonator sweep to CW Time.

6. **Status bar:** channel, trigger state, IFBW, correction level (`—`, `R` for response/normalized), RF on/off, and the average counter.

7. **Saving:**
   - Touchstone `.s2p`, which fills only S21 (zeros elsewhere is what the PNA does uncorrected).
   - CSV, with a choice of **Formatted** (as displayed) or **Unformatted/complex** (re/im before formatting).
   - A header line stating the correction state (e.g. `!Correction: S21(Response/Normalize)` or `none`).
   - For CW Time, the stimulus column is time in seconds.

### Computing and normalizing S21 without a reference receiver

- The PNA's raw S21 is B/R1. R1 cancels the source's amplitude and phase. We have no R1, so our "S21" is the **unratioed b2** in ADC units: an absolute receiver reading. The PNA's own caveats for unratioed traces apply:
  - Absolute phase is arbitrary. Ours is deterministic only because the DAC and ADC NCOs are phase-coherent on one board.
  - Averaging behaves differently.
- Label the current trace honestly, PNA style: unit "dB (ADC)" or "dBFS", not "dB".
- **Equivalent of R1 (inference):** a stored **loopback/thru reference**. Measure the bench loopback, or the cryostat line with the chip bypassed if possible, at the same frequencies, power, gain and IFBW. Store it as complex data and divide: `S21 = b2_DUT / b2_thru`. This is exactly the PNA **Thru Response cal ("Normalize")**, or **Data→Memory then Data/Memory**: a one-term correction of transmission tracking, with no match or isolation correction. Copy the PNA rules:
  - Interpolate only inside the stored range. Invalidate the reference if the span grows or the points change without interpolation.
  - Show **C-delta**-style "uncertain" when IFBW, power/gain, sweep time or settling change after normalization.
  - Store the reference with the setup profile, as the PNA stores a response cal in the Cal Set.
- Offer both flows: a quick **Memory → Normalize** (Data/Mem on the current trace) and a named **Response cal** saved with the setup.
- **Isolation term (optional):** measure with DAC power off, or the line terminated, and subtract it before dividing. This mirrors the "Isolation (optional)" step of the Thru Response cal.
- Full 2-port SOLT, enhanced response and match correction are **not achievable**. We have no couplers, no a-waves and no second direction. Do not imply them.
- A cold thru is rarely available on a dilution fridge. In practice the "normalization" users want is usually **Data/Memory** against an off-resonance or flux-detuned trace. Offer that as a first-class action.

### What doesn't apply to a pulsed RFSoC system
- **Analog (swept) mode, Fast Sweep, band crossings, retrace power blanking, ALC/LVL, mechanical source and receiver attenuators, LF Auto BW, IFBW Shape options.** Our DDS retunes per point, so we are always "stepped". Dwell = our settling time. Attenuation lives in the external chain (and the 4x2 DAC/ADC gain), not in switchable steps.
- **Forward/reverse sweeps, point sweep vs standard sweep, multiport cal sweep counts.** We have one source and one receiver.
- **Trigger scope, multiple channels sweeping in turn.** Useful only if we ever add channels. For now one channel, with Continuous/Single/Hold and an optional external trigger later.
- **Pulsed mode** has no PNA front-panel equivalent in this list. The PNA's wideband IFBW (>600 kHz) exists for pulsed measurements. Our "pulsed" sweep is closer to a PNA pulsed-RF measurement than to CW, and "IFBW" there means 1/readout-window.
