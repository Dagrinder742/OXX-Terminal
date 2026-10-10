import pytest
from engine import (analyze, Params, COIL, UP, DOWN, CHOP,
                    effective_seconds, zscore, fair_p_up)


def test_all_equal_is_coil():
    assert analyze(86000, 86000, 86000).verdict == COIL


def test_tiny_same_direction_steps_are_not_momentum():
    # The false-flag case: +0.02 then +0.03 used to be "HEAVY BUY-SIDE MOMENTUM"
    assert analyze(86000, 86000.02, 86000.05).verdict == COIL


def test_real_accelerating_up():
    assert analyze(86000, 86060, 86160).verdict == UP


def test_mirror_is_down():
    assert analyze(86000, 85940, 85840).verdict == DOWN


def test_decelerating_same_direction_is_chop():
    assert analyze(86000, 86100, 86150).verdict == CHOP


def test_opposite_directions_is_chop():
    assert analyze(86000, 86100, 86000 + 20 + 30).verdict == CHOP


def test_one_flat_leg_is_not_momentum():
    # leg 1 flat, leg 2 moves: not a trend by this definition
    assert analyze(86000, 86000, 86120).verdict == CHOP


def test_zero_or_negative_anchor_raises():
    with pytest.raises(ValueError):
        analyze(0, 1, 2)


def test_band_matches_original_formula():
    assert analyze(86000, 86060, 86160).band == pytest.approx(160 * 0.6)


def test_accel_ratio_zero_means_same_direction_only():
    p = Params(accel_ratio=0.0)
    assert analyze(86000, 86100, 86150, p).verdict == UP


# ---------- distance-over-time model ----------
def test_effective_seconds_subtracts_40():
    assert effective_seconds(300) == pytest.approx(260)
    assert effective_seconds(60) == pytest.approx(20)


def test_effective_seconds_refuses_inside_averaging_window():
    with pytest.raises(ValueError):
        effective_seconds(59)


def test_at_target_is_fifty_fifty():
    assert fair_p_up(82800, 82800, 300) == pytest.approx(0.5)


def test_up_and_down_are_symmetric():
    up = fair_p_up(82900, 82800, 300)
    down = fair_p_up(82700, 82800, 300)
    assert up + down == pytest.approx(1.0)


def test_higher_price_means_higher_probability():
    assert fair_p_up(82850, 82800, 300) > fair_p_up(82820, 82800, 300) > 0.5


def test_same_gap_matters_more_with_less_time():
    assert fair_p_up(82900, 82800, 100) > fair_p_up(82900, 82800, 800)


def test_zscore_sign_follows_price_vs_target():
    assert zscore(82700, 82800, 300) < 0 < zscore(82900, 82800, 300)


def test_screenshot_case_is_near_fifty():
    # Screenshot: now 82,799.29 vs target 82,800.88 with 4:55 (295 s) left.
    # With the default 40% vol guess this is about 49%, not the 45% shown.
    assert fair_p_up(82799.29, 82800.88, 295) == pytest.approx(0.4933, abs=0.002)
