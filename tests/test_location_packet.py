"""
Tests for LOCATION tracker packet (0x0D) parsing and processing,
and Trackers-channel GROUP_DATA (0x06) decryption.
"""

import hashlib
import hmac

import pytest
from Crypto.Cipher import AES

from app.channel_constants import TRACKERS_CHANNEL_KEY
from app.decoder import (
    GROUP_DATA_TRACKER_TYPE,
    PayloadType,
    decrypt_group_data,
    decrypt_trackers_location,
    parse_location,
)


def build_mcl1_payload(
    *,
    node_id: str = "12345678",
    lat_micro: int = 37774900,
    lon_micro: int = -122419400,
    altitude: int = 50,
    speed_cm: int = 150,
    heading_centi: int = 9000,
    satellites: int = 8,
    battery_mv: int = 3700,
    timestamp: int = 1718582400,
    name: str | None = None,
) -> bytes:
    name_bytes = name.encode("utf-8") if name else b""
    payload = bytearray(32 + len(name_bytes))
    payload[0:4] = b"MCL1"
    payload[4] = 1
    payload[5] = 0
    payload[6:10] = bytes.fromhex(node_id)
    payload[10:14] = lat_micro.to_bytes(4, "big", signed=True)
    payload[14:18] = lon_micro.to_bytes(4, "big", signed=True)
    payload[18:20] = altitude.to_bytes(2, "big", signed=True)
    payload[20:22] = speed_cm.to_bytes(2, "big", signed=False)
    payload[22:24] = heading_centi.to_bytes(2, "big", signed=False)
    payload[24] = satellites
    payload[25:27] = battery_mv.to_bytes(2, "big", signed=False)
    payload[27:31] = timestamp.to_bytes(4, "big", signed=False)
    payload[31] = len(name_bytes)
    if name_bytes:
        payload[32 : 32 + len(name_bytes)] = name_bytes
    return bytes(payload)


def build_encrypted_trackers_group_data(mcl1_body: bytes) -> bytes:
    channel_key = bytes.fromhex(TRACKERS_CHANNEL_KEY)
    plain = (
        GROUP_DATA_TRACKER_TYPE.to_bytes(2, "little")
        + bytes([len(mcl1_body)])
        + mcl1_body
    )
    pad_len = (16 - len(plain) % 16) % 16
    if pad_len == 0:
        pad_len = 16
    plain += bytes(pad_len)

    ciphertext = AES.new(channel_key, AES.MODE_ECB).encrypt(plain)
    channel_secret = channel_key + bytes(16)
    mac = hmac.new(channel_secret, ciphertext, hashlib.sha256).digest()[:2]
    channel_hash = hashlib.sha256(channel_key).digest()[:1]
    return channel_hash + mac + ciphertext


def test_parse_location_basic():
    """Test parsing a minimal LOCATION packet."""
    # Build a minimal LOCATION packet (32 bytes)
    payload = bytearray(32)

    # Magic: "MCL1" (bytes 0-3)
    payload[0:4] = b"MCL1"

    # Version: 1 (byte 4)
    payload[4] = 1

    # Flags: 0 (byte 5, reserved)
    payload[5] = 0

    # Node ID: first 4 bytes of public key (bytes 6-9)
    payload[6:10] = bytes.fromhex("12345678")

    # Lat: 37.7749 degrees = 37774900 microdegrees (bytes 10-13, int32 LE)
    lat_micro = 37774900
    payload[10:14] = lat_micro.to_bytes(4, "big", signed=True)

    # Lon: -122.4194 degrees = -122419400 microdegrees (bytes 14-17, int32 LE)
    lon_micro = -122419400
    payload[14:18] = lon_micro.to_bytes(4, "big", signed=True)

    # Altitude: 50 metres (bytes 18-19, int16 LE)
    payload[18:20] = (50).to_bytes(2, "big", signed=True)

    # Speed: 150 cm/s = 1.5 m/s (bytes 20-21, uint16 LE)
    payload[20:22] = (150).to_bytes(2, "big", signed=False)

    # Heading: 9000 centidegrees = 90.00 degrees (bytes 22-23, uint16 LE)
    payload[22:24] = (9000).to_bytes(2, "big", signed=False)

    # Satellites: 8 (byte 24)
    payload[24] = 8

    # Battery: 3700 mV (bytes 25-26, uint16 LE)
    payload[25:27] = (3700).to_bytes(2, "big", signed=False)

    # Timestamp: 1718582400 (bytes 27-30, uint32 LE)
    payload[27:31] = (1718582400).to_bytes(4, "big", signed=False)

    # Name length: 0 (byte 31)
    payload[31] = 0

    # Parse
    result = parse_location(bytes(payload))

    assert result is not None
    assert result.magic == "MCL1"
    assert result.version == 1
    assert result.flags == 0
    assert result.node_id == "12345678"
    assert abs(result.lat - 37.7749) < 0.0001
    assert abs(result.lon - (-122.4194)) < 0.0001
    assert result.altitude == 50
    assert abs(result.speed - 1.5) < 0.01
    assert abs(result.heading - 90.0) < 0.01
    assert result.satellites == 8
    assert result.battery == 3700
    assert result.timestamp == 1718582400
    assert result.name is None


def test_parse_location_with_name():
    """Test parsing a LOCATION packet with a node name."""
    name = "TrackerNode"
    name_bytes = name.encode("utf-8")

    # Build packet: 32 bytes + name length
    payload = bytearray(32 + len(name_bytes))

    # Magic: "MCL1"
    payload[0:4] = b"MCL1"
    payload[4] = 1  # version
    payload[5] = 0  # flags
    payload[6:10] = bytes.fromhex("ABCDEF01")  # node_id

    # Location: 0,0
    payload[10:14] = (0).to_bytes(4, "big", signed=True)  # lat
    payload[14:18] = (0).to_bytes(4, "big", signed=True)  # lon
    payload[18:20] = (0).to_bytes(2, "big", signed=True)  # altitude
    payload[20:22] = (0).to_bytes(2, "big", signed=False)  # speed
    payload[22:24] = (0).to_bytes(2, "big", signed=False)  # heading
    payload[24] = 0  # satellites
    payload[25:27] = (0).to_bytes(2, "big", signed=False)  # battery
    payload[27:31] = (0).to_bytes(4, "big", signed=False)  # timestamp

    # Name
    payload[31] = len(name_bytes)
    payload[32 : 32 + len(name_bytes)] = name_bytes

    # Parse
    result = parse_location(bytes(payload))

    assert result is not None
    assert result.name == name
    assert result.node_id == "abcdef01"


def test_parse_location_negative_altitude():
    """Test parsing a LOCATION packet with negative altitude (below sea level)."""
    payload = bytearray(32)
    payload[0:4] = b"MCL1"
    payload[4] = 1
    payload[5] = 0
    payload[6:10] = bytes.fromhex("11111111")

    # Dead Sea: ~31.5 lat, 35.5 lon, -430m altitude
    payload[10:14] = (31500000).to_bytes(4, "big", signed=True)
    payload[14:18] = (35500000).to_bytes(4, "big", signed=True)
    payload[18:20] = (-430).to_bytes(2, "big", signed=True)

    payload[20:22] = (0).to_bytes(2, "big", signed=False)
    payload[22:24] = (0).to_bytes(2, "big", signed=False)
    payload[24] = 0
    payload[25:27] = (0).to_bytes(2, "big", signed=False)
    payload[27:31] = (0).to_bytes(4, "big", signed=False)
    payload[31] = 0

    result = parse_location(bytes(payload))

    assert result is not None
    assert result.altitude == -430
    assert abs(result.lat - 31.5) < 0.0001
    assert abs(result.lon - 35.5) < 0.0001


def test_parse_location_invalid_magic():
    """Test that invalid magic is rejected."""
    payload = bytearray(32)
    payload[0:4] = b"XXXX"  # Invalid magic
    payload[4] = 1

    result = parse_location(bytes(payload))
    assert result is None


def test_parse_location_too_short():
    """Test that packets shorter than 32 bytes are rejected."""
    payload = bytearray(20)  # Too short

    result = parse_location(bytes(payload))
    assert result is None


def test_parse_location_invalid_coordinates():
    """Test that invalid coordinates are rejected."""
    payload = bytearray(32)
    payload[0:4] = b"MCL1"
    payload[4] = 1
    payload[5] = 0
    payload[6:10] = bytes.fromhex("22222222")

    # Invalid latitude: 91 degrees (out of range)
    payload[10:14] = (91000000).to_bytes(4, "big", signed=True)
    payload[14:18] = (0).to_bytes(4, "big", signed=True)

    payload[18:20] = (0).to_bytes(2, "big", signed=True)
    payload[20:22] = (0).to_bytes(2, "big", signed=False)
    payload[22:24] = (0).to_bytes(2, "big", signed=False)
    payload[24] = 0
    payload[25:27] = (0).to_bytes(2, "big", signed=False)
    payload[27:31] = (0).to_bytes(4, "big", signed=False)
    payload[31] = 0

    result = parse_location(bytes(payload))
    assert result is None


def test_parse_location_max_name_length():
    """Test that the maximum name length (24 bytes) is accepted."""
    name = "X" * 24  # Max length
    name_bytes = name.encode("utf-8")

    payload = bytearray(32 + len(name_bytes))
    payload[0:4] = b"MCL1"
    payload[4] = 1
    payload[5] = 0
    payload[6:10] = bytes.fromhex("33333333")
    payload[10:14] = (0).to_bytes(4, "big", signed=True)
    payload[14:18] = (0).to_bytes(4, "big", signed=True)
    payload[18:20] = (0).to_bytes(2, "big", signed=True)
    payload[20:22] = (0).to_bytes(2, "big", signed=False)
    payload[22:24] = (0).to_bytes(2, "big", signed=False)
    payload[24] = 0
    payload[25:27] = (0).to_bytes(2, "big", signed=False)
    payload[27:31] = (0).to_bytes(4, "big", signed=False)
    payload[31] = len(name_bytes)
    payload[32 : 32 + len(name_bytes)] = name_bytes

    result = parse_location(bytes(payload))
    assert result is not None
    assert result.name == name


def test_parse_location_name_exceeds_max():
    """Test that name length exceeding 24 bytes is rejected."""
    name = "X" * 25  # Exceeds max
    name_bytes = name.encode("utf-8")

    payload = bytearray(32 + len(name_bytes))
    payload[0:4] = b"MCL1"
    payload[4] = 1
    payload[5] = 0
    payload[6:10] = bytes.fromhex("44444444")
    payload[10:31] = bytes(21)  # Zero-fill coordinates and other fields
    payload[31] = len(name_bytes)
    payload[32 : 32 + len(name_bytes)] = name_bytes

    result = parse_location(bytes(payload))
    assert result is None


def test_payload_type_location_exists():
    """Test that PayloadType.LOCATION is defined."""
    assert PayloadType.LOCATION == 0x0D
    assert PayloadType.GROUP_DATA == 0x06
    assert PayloadType.ATLAS == 0x0C


def test_decrypt_trackers_group_data():
    """Trackers GROUP_DATA decrypts to the embedded MCL1 body."""
    mcl1 = build_mcl1_payload(name="TrailTracker")
    encrypted = build_encrypted_trackers_group_data(mcl1)

    inner = decrypt_group_data(
        encrypted,
        bytes.fromhex(TRACKERS_CHANNEL_KEY),
        expected_data_type=GROUP_DATA_TRACKER_TYPE,
    )
    assert inner == mcl1

    location = decrypt_trackers_location(encrypted)
    assert location is not None
    assert location.name == "TrailTracker"
    assert location.node_id == "12345678"
    assert abs(location.lat - 37.7749) < 0.0001
    assert abs(location.speed - 1.5) < 0.01


def test_decrypt_trackers_group_data_rejects_wrong_data_type():
    """GROUP_DATA with a non-tracker data_type is ignored."""
    channel_key = bytes.fromhex(TRACKERS_CHANNEL_KEY)
    mcl1 = build_mcl1_payload()
    plain = (0x0100).to_bytes(2, "little") + bytes([len(mcl1)]) + mcl1
    pad_len = (16 - len(plain) % 16) % 16
    if pad_len == 0:
        pad_len = 16
    plain += bytes(pad_len)
    ciphertext = AES.new(channel_key, AES.MODE_ECB).encrypt(plain)
    channel_secret = channel_key + bytes(16)
    mac = hmac.new(channel_secret, ciphertext, hashlib.sha256).digest()[:2]
    channel_hash = hashlib.sha256(channel_key).digest()[:1]
    encrypted = channel_hash + mac + ciphertext

    assert decrypt_trackers_location(encrypted) is None


def test_location_packet_decryption_info():
    """Test that decoded LOCATION info is formatted for display."""
    from app.decoder import parse_location

    # Build a LOCATION packet
    payload = bytearray(32)
    payload[0:4] = b"MCL1"
    payload[4] = 1  # version
    payload[5] = 0  # flags
    payload[6:10] = bytes.fromhex("ABCD1234")  # node_id

    # San Francisco coordinates
    payload[10:14] = (37774900).to_bytes(4, "big", signed=True)  # lat
    payload[14:18] = (-122419400).to_bytes(4, "big", signed=True)  # lon
    payload[18:20] = (50).to_bytes(2, "big", signed=True)  # altitude
    payload[20:22] = (150).to_bytes(2, "big", signed=False)  # speed (1.5 m/s)
    payload[22:24] = (9000).to_bytes(2, "big", signed=False)  # heading (90°)
    payload[24] = 8  # satellites
    payload[25:27] = (3700).to_bytes(2, "big", signed=False)  # battery
    payload[27:31] = (1718582400).to_bytes(4, "big", signed=False)  # timestamp
    payload[31] = 0  # no name

    location = parse_location(bytes(payload))
    assert location is not None

    # Verify the location can be formatted into a display message
    display_name = f"Node {location.node_id[:8]}"
    message = (
        f"📍 {display_name}: {location.lat:.6f}, {location.lon:.6f} "
        f"(alt: {location.altitude}m, speed: {location.speed:.1f}m/s, "
        f"hdg: {location.heading:.1f}°, sats: {location.satellites}, "
        f"batt: {location.battery}mV)"
    )

    # Verify message contains key location data
    assert "37.7749" in message
    assert "-122.4194" in message
    assert "50m" in message
    assert "1.5m/s" in message
    assert "90.0°" in message
    assert "sats: 8" in message
    assert "3700mV" in message


def test_tracker_decrypted_info_includes_speed_and_heading_fields():
    """Tracker decoded raw-packet info includes speed and heading as structured fields."""
    from app.packet_processor import _tracker_decrypted_info

    payload = bytearray(32)
    payload[0:4] = b"MCL1"
    payload[4] = 1
    payload[5] = 0
    payload[6:10] = bytes.fromhex("ABCD1234")
    payload[10:14] = (37774900).to_bytes(4, "big", signed=True)
    payload[14:18] = (-122419400).to_bytes(4, "big", signed=True)
    payload[18:20] = (50).to_bytes(2, "big", signed=True)
    payload[20:22] = (150).to_bytes(2, "big", signed=False)
    payload[22:24] = (9000).to_bytes(2, "big", signed=False)
    payload[24] = 8
    payload[25:27] = (3700).to_bytes(2, "big", signed=False)
    payload[27:31] = (1718582400).to_bytes(4, "big", signed=False)
    payload[31] = 0

    location = parse_location(bytes(payload))
    assert location is not None

    result = _tracker_decrypted_info(location, "TrackerNode")

    assert result["decrypted"] is True
    assert result["is_tracker"] is True
    assert result["node_id"] == "abcd1234"
    assert abs(result["speed"] - 1.5) < 0.01
    assert abs(result["heading"] - 90.0) < 0.01
