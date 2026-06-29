"""Gateway-bridge path filtering shared by spam detection and MQTT fanout."""

from __future__ import annotations

from typing import Any

from app.path_utils import parse_packet_envelope, split_path_hex

# Default GWNL / community MQTT bridge gateways (full public keys, lowercase).
DEFAULT_GATEWAY_PUBKEYS: tuple[str, ...] = (
    "1228d131fa4b13c78a7aefee124e5c7fe51a8555115220d64d1df749b5a7de8c",
    "753c3a558d71c52669cf59d67dd9be41725efd8af113b2f2f36925bde002f5b1",
    "db371c0634d23dd4dc72556366f6cd19578ac91eb85257ea259af8f8bb1d14e0",
    "6cfa92bb8d6270c0b2675047824352462c741aa9ce9c93bba777693a0bd5b972",
    "40b8bacb92538bdaa3d45abb759dd8cfcefaefc5a8f1e77d0f3dc6b7b5452429",
    "82e422e3a9d279d31df8794439dd92803db0658c9d6579cc717bbc0f266070dd",
    "2092ae5d57ff8836f2047a1f74f695084247aac2b85cdc5d4ecf7cb9f2ad3c0e",
    "8fb483861e77a9e8021ed546510ba6deb9e7708dd2330c407f05e085a8f6e31a",
    "7d5abd286e07f4995dda8a220d044ef2f13949fcc4f3621e4a69bfc20519259a",
    "d26506b1ed9c8a839bfca3b1ab0afe64a6e30fb47cb0d742d2f81efbee2a17e2",
    "eb46b319cd2dac975ae178d07d57806fd6b8a4d5301027d76fbd3b3f8df3e3f8",
    "66cca85f210d7af515f8c5760aa222ba1072762446b7fddaef36308a3a12513b",
    "049314d147f018f44633be5b8a4852279295bb5eced77488c451ec83ebc28afa",
    "6a2ef6c39e04437244decfddfe7053a5de0749ef8ed7203f27315cd40a0ce609",
    "bcbc1ef856631a102cc5bc6cee2f4f490fd4533691f8d85d8c4ef3c881d9f4bc",
)


def parse_gateway_pubkeys(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def gateway_pubkeys_from_configured(configured: str) -> frozenset[str]:
    configured = configured.strip()
    if configured.lower() == "none":
        return frozenset()
    if configured:
        parsed = parse_gateway_pubkeys(configured)
        return parsed if parsed else frozenset(DEFAULT_GATEWAY_PUBKEYS)
    return frozenset(DEFAULT_GATEWAY_PUBKEYS)


def is_gateway_hop(hop: str, gateway_pubkeys: frozenset[str]) -> bool:
    """Return True when a path hop token matches a configured gateway public key prefix."""
    if not gateway_pubkeys:
        return False
    hop_lower = hop.lower()
    return any(gateway.startswith(hop_lower) for gateway in gateway_pubkeys)


def path_last_hop_is_gateway(
    path_hex: str,
    path_len: int,
    gateway_pubkeys: frozenset[str],
) -> bool:
    """Return True when the final path hop is a configured gateway bridge node."""
    if not gateway_pubkeys or not path_hex or path_len <= 0:
        return False
    tokens = split_path_hex(path_hex.upper(), path_len)
    if not tokens:
        return False
    return is_gateway_hop(tokens[-1], gateway_pubkeys)


def raw_packet_last_hop_is_gateway(
    raw_hex: str,
    gateway_pubkeys: frozenset[str],
) -> bool:
    """Decode a raw RF packet and test whether its last path hop is a gateway node."""
    if not gateway_pubkeys or not raw_hex:
        return False
    try:
        raw_bytes = bytes.fromhex(raw_hex)
    except ValueError:
        return False
    envelope = parse_packet_envelope(raw_bytes)
    if envelope is None or envelope.hop_count <= 0:
        return False
    return path_last_hop_is_gateway(
        envelope.path.hex(),
        envelope.hop_count,
        gateway_pubkeys,
    )


def should_skip_mqtt_raw_packet_broadcast(data: dict[str, Any]) -> bool:
    """Return True when a raw_packet WS/fanout payload should not be relayed to MQTT."""
    from app.services.spam_live_tracker import spam_live_tracker

    return raw_packet_last_hop_is_gateway(
        str(data.get("data") or ""),
        spam_live_tracker.gateway_pubkeys,
    )
