"""Geo hints from learned advert first-hop neighbor relationships."""

from __future__ import annotations

from typing import Any

from app.models import Contact
from app.path_utils import hash_mode_from_hop_token
from app.repository.contact_advert_neighbors import ContactAdvertNeighborRepository
from app.services.spam_path_analysis import contact_has_valid_coords


def centroid_from_contacts(contacts: list[Contact]) -> tuple[float, float] | None:
    points = [
        (float(contact.lat), float(contact.lon))
        for contact in contacts
        if contact_has_valid_coords(contact.lat, contact.lon)
    ]
    if not points:
        return None
    lat = sum(point[0] for point in points) / len(points)
    lon = sum(point[1] for point in points) / len(points)
    return lat, lon


async def enrich_hop_geos_from_advert_neighbors(
    hop_tokens: list[str] | tuple[str, ...],
    hop_geos: dict[str, dict[str, Any]],
    *,
    default_path_hash_mode: int | None = None,
) -> None:
    """Fill missing hop coordinates using contacts known to neighbor that hop."""
    for hop in hop_tokens:
        existing = hop_geos.get(hop, {})
        if existing.get("lat") is not None and existing.get("lon") is not None:
            continue

        hop_hash_mode = hash_mode_from_hop_token(hop)
        if hop_hash_mode is None:
            hop_hash_mode = default_path_hash_mode

        try:
            contacts = await ContactAdvertNeighborRepository.list_contacts_for_neighbor_hop(
                hop,
                path_hash_mode=hop_hash_mode,
            )
        except RuntimeError:
            continue
        if not contacts:
            continue

        centroid = centroid_from_contacts(contacts)
        if centroid is None:
            continue

        anchor = next(
            (
                contact
                for contact in contacts
                if contact_has_valid_coords(contact.lat, contact.lon)
            ),
            contacts[0],
        )
        hop_geos[hop] = {
            "name": anchor.name,
            "public_key": anchor.public_key,
            "lat": centroid[0],
            "lon": centroid[1],
            "geo_source": "advert_neighbor",
            "advert_neighbor_count": len(contacts),
        }
