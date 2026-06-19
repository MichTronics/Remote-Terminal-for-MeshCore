"""Tests for spam fluke episode history filter."""

from app.services.spam_detection_settings import is_fluke_episode


def test_is_fluke_episode_discards_short_low_volume_burst():
    assert is_fluke_episode(
        total_packets=20,
        duration_secs=120,
        max_packets=35,
        max_duration_secs=300,
    )


def test_is_fluke_episode_keeps_when_packet_cap_reached():
    assert not is_fluke_episode(
        total_packets=35,
        duration_secs=120,
        max_packets=35,
        max_duration_secs=300,
    )


def test_is_fluke_episode_keeps_when_duration_exceeds_window():
    assert not is_fluke_episode(
        total_packets=20,
        duration_secs=301,
        max_packets=35,
        max_duration_secs=300,
    )


def test_is_fluke_episode_disabled_when_packet_cap_zero():
    assert not is_fluke_episode(
        total_packets=5,
        duration_secs=60,
        max_packets=0,
        max_duration_secs=300,
    )
