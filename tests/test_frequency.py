import pytest

from qick_interface.frequency import FrequencyError, plan_sweep
from qick_interface.profiles import SetupProfile


def profile(lo_mhz, sideband="upper"):
    return SetupProfile(chip="Test chip", chip_type="transmon", lo_mhz=lo_mhz, sideband=sideband)


def test_upper_sideband_puts_rf_above_lo_and_image_below():
    plan = plan_sweep(profile(6000.0), rf_start=6100.0, rf_stop=6200.0)

    assert (plan.if_start, plan.if_stop) == (100.0, 200.0)
    assert (plan.image_start, plan.image_stop) == (5900.0, 5800.0)


def test_lower_sideband_puts_rf_below_lo_and_image_above():
    plan = plan_sweep(profile(7000.0, "lower"), rf_start=6800.0, rf_stop=6900.0)

    assert (plan.if_start, plan.if_stop) == (200.0, 100.0)
    assert (plan.image_start, plan.image_stop) == (7200.0, 7100.0)


def test_without_lo_rf_equals_if_and_there_is_no_image():
    plan = plan_sweep(profile(None), rf_start=500.0, rf_stop=1500.0)

    assert (plan.if_start, plan.if_stop) == (500.0, 1500.0)
    assert (plan.image_start, plan.image_stop) == (None, None)


def test_rf_on_the_wrong_side_of_lo_is_rejected():
    with pytest.raises(FrequencyError, match="upper sideband"):
        plan_sweep(profile(6000.0, "upper"), rf_start=5950.0, rf_stop=6050.0)


def test_if_above_the_adc_first_nyquist_zone_is_rejected():
    with pytest.raises(FrequencyError, match="2211.84 MHz"):
        plan_sweep(profile(None), rf_start=2000.0, rf_stop=2500.0)


def test_zero_or_negative_frequencies_are_rejected_without_lo():
    with pytest.raises(FrequencyError, match="above 0"):
        plan_sweep(profile(None), rf_start=0.0, rf_stop=100.0)
