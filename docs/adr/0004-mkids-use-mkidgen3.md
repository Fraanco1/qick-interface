# MKIDs use Mazin Lab's MKIDGen3 stack, outside this app

Multiplexed MKID readout uses Mazin Lab's complete MKIDGen3 implementation: their firmware, board server and their own GUI (MazinLab/readout-gui). This app covers only transmon and fluxonium chips. The QICK firmware on the board can't read many resonators at once, and MKIDGen3 already targets the RFSoC 4x2 with the same I/Q topology we have, so reimplementing its screens here would duplicate their work.

## Consequences

- MKIDs run on their own SD card / PYNQ image (MKIDGen3 needs a newer, patched PYNQ), so the board runs either QICK or MKIDGen3, never both.
- MKIDGen3's firmware must be built from source (no prebuilt bitstream), and their GUI expects their IF board; our LO and mixers need a stand-in. See docs/research/mkidgen3.md.
