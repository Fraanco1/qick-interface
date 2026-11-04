"""Runs on the RFSoC: settings of the RF data converter that QICK does not expose, shared with the lab PC
over Pyro4 as "converters".

The two DACs are on different converter tiles (DAC_A: tile 2, DAC_B: tile 0), and the delay between
them changes at every power-up by whole fabric cycles (1.63 ns). Each DAC's coarse delay (0-40 samples
of 0.10 ns, PG269 "Coarse Delay") can cancel it. See docs/research/dac-tile-sync.md.
"""
import Pyro4
import xrfdc

DAC_BLOCKS = {"DAC_A": (2, 0), "DAC_B": (0, 0)}  # board label -> (tile, block), from the firmware config


@Pyro4.expose
class Converters:
    def __init__(self, soc):
        self._soc = soc

    def dac_delay_samples(self, port: str) -> int:
        return int(self._block(port).CoarseDelaySettings["CoarseDelay"])

    def set_dac_delay_samples(self, port: str, samples: int) -> int:
        """Delay one DAC's output by whole samples (0-40); returns the value read back."""
        settings = dict(self._block(port).CoarseDelaySettings)
        settings.update(CoarseDelay=int(samples), EventSource=xrfdc.EVNT_SRC_IMMEDIATE)
        self._block(port).CoarseDelaySettings = settings
        return self.dac_delay_samples(port)

    def _block(self, port):
        tile, block = DAC_BLOCKS[port]
        return self._soc.rf.dac_tiles[tile].blocks[block]
