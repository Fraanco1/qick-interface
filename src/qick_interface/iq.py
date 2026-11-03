"""Settings shared by everything that plays a tone on the I/Q output path."""
from .board import gen_channel
from .profiles import SetupProfile


def iq_output(soccfg, profile: SetupProfile, gain: float) -> dict:
    """I and Q gens, gains and Q phase. The larger of I and Q gets `gain`;
    the sign of the Q phase picks the sideband."""
    i_gain = gain / max(1.0, profile.iq_gain_ratio)
    sign = 1 if profile.sideband == "upper" else -1
    return {"gen": gen_channel(soccfg, profile.i_dac), "gain": i_gain,
            "q_gen": gen_channel(soccfg, profile.q_dac), "q_gain": i_gain * profile.iq_gain_ratio,
            "q_phase": sign * profile.iq_phase_deg}
