"""Tests for region smart sorting."""
import time

import pytest

from app.models import Region
from app.routers.regions import smart_sort_regions


@pytest.fixture
def sample_regions() -> list[Region]:
    """Create a sample list of regions for testing."""
    now = int(time.time())
    return [
        Region(id=1, name="us", key="0" * 32, is_public=True, created_at=now),
        Region(id=2, name="nl", key="1" * 32, is_public=True, created_at=now),
        Region(id=3, name="nl-gr", key="2" * 32, is_public=True, created_at=now),
        Region(id=4, name="nl-nh", key="3" * 32, is_public=True, created_at=now),
        Region(id=5, name="nl-grq", key="4" * 32, is_public=True, created_at=now),
        Region(id=6, name="nl-ams", key="5" * 32, is_public=True, created_at=now),
        Region(id=7, name="de", key="6" * 32, is_public=True, created_at=now),
        Region(id=8, name="de-nord", key="7" * 32, is_public=True, created_at=now),
        Region(id=9, name="eu", key="8" * 32, is_public=True, created_at=now),
        Region(id=10, name="uk", key="9" * 32, is_public=True, created_at=now),
    ]


def test_smart_sort_with_nl_gr_scope(sample_regions: list[Region]) -> None:
    """Test sorting with nl-gr as the current scope."""
    sorted_regions = smart_sort_regions(sample_regions, "nl-gr")
    names = [r.name for r in sorted_regions]
    
    # nl-gr should be first (exact match)
    assert names[0] == "nl-gr"
    
    # Other NL regional codes should follow (nl-nh)
    assert names[1] == "nl-nh"
    
    # Then NL IATA codes (nl-ams, nl-grq)
    assert names[2] in ["nl-ams", "nl-grq"]
    assert names[3] in ["nl-ams", "nl-grq"]
    
    # Then country code nl
    assert names[4] == "nl"
    
    # Then EU regional code
    assert names[5] == "eu"
    
    # Finally others (de, de-nord, uk, us)
    remaining = names[6:]
    assert "de" in remaining
    assert "de-nord" in remaining
    assert "uk" in remaining
    assert "us" in remaining


def test_smart_sort_with_de_scope(sample_regions: list[Region]) -> None:
    """Test sorting with de as the current scope."""
    sorted_regions = smart_sort_regions(sample_regions, "de")
    names = [r.name for r in sorted_regions]
    
    # de should be first (exact match)
    assert names[0] == "de"
    
    # de-nord should be high priority (same country regional)
    assert names[1] == "de-nord"
    
    # EU should follow for European countries
    assert names[2] == "eu"


def test_smart_sort_with_empty_scope(sample_regions: list[Region]) -> None:
    """Test sorting with no scope - should be alphabetical."""
    sorted_regions = smart_sort_regions(sample_regions, "")
    names = [r.name for r in sorted_regions]
    
    # Should be alphabetically sorted
    assert names == sorted(names)


def test_smart_sort_with_nl_iata_scope(sample_regions: list[Region]) -> None:
    """Test sorting with an IATA code like nl-grq."""
    sorted_regions = smart_sort_regions(sample_regions, "nl-grq")
    names = [r.name for r in sorted_regions]
    
    # nl-grq should be first (exact match)
    assert names[0] == "nl-grq"
    
    # Other NL regional codes should have higher priority than other IATA
    # (because regional codes are checked before IATA)
    nl_regional_indices = [names.index("nl-gr"), names.index("nl-nh")]
    nl_iata_index = names.index("nl-ams")
    
    # Regional codes should come before other IATA codes
    assert all(idx < nl_iata_index for idx in nl_regional_indices)


def test_smart_sort_preserves_all_regions(sample_regions: list[Region]) -> None:
    """Test that sorting doesn't lose any regions."""
    sorted_regions = smart_sort_regions(sample_regions, "nl-gr")
    
    assert len(sorted_regions) == len(sample_regions)
    assert set(r.name for r in sorted_regions) == set(r.name for r in sample_regions)


def test_smart_sort_with_unknown_scope(sample_regions: list[Region]) -> None:
    """Test sorting with an unknown scope falls back to alphabetical."""
    sorted_regions = smart_sort_regions(sample_regions, "zz-unknown")
    names = [r.name for r in sorted_regions]
    
    # Should be mostly alphabetical (unknown scope won't match anything)
    # All regions should have priority 5 (everything else)
    assert names == sorted(names)
