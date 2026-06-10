"""Integration tests for region API with smart sorting."""
import httpx
import pytest

from app.main import app
from app.repository import AppSettingsRepository, RegionRepository
from app.routers.regions import seed_default_regions


@pytest.fixture(autouse=True)
async def setup_regions(test_db):
    """Seed default regions before each test."""
    # Also patch the region repository to use test_db
    import app.routers.regions as regions_module
    original_regions_db = regions_module.RegionRepository.__dict__.get("db")
    
    # Ensure regions repository uses test_db
    import app.repository.regions as regions_repo_module
    original_repo_db = regions_repo_module.db
    regions_repo_module.db = test_db
    
    try:
        await seed_default_regions()
        yield
    finally:
        regions_repo_module.db = original_repo_db


async def test_get_regions_sorted_by_current_flood_scope(test_db):
    """Test that GET /api/settings/regions sorts by current flood scope."""
    # Patch AppSettingsRepository to use test_db
    import app.repository.settings as settings_module
    original_db = settings_module.db
    settings_module.db = test_db
    
    try:
        # Set flood scope to nl-gr
        await AppSettingsRepository.update(flood_scope="nl-gr")
        
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/regions")
        
        assert response.status_code == 200
        regions = response.json()
        
        # Should have all default regions
        assert len(regions) > 0
        
        # nl-gr should be first (exact match)
        names = [r["name"] for r in regions]
        assert names[0] == "nl-gr"
        
        # Other NL regional codes should be near the top
        nl_regional = [n for n in names if n.startswith("nl-") and n not in ["nl-grq", "nl-lwr", "nl-dhr", "nl-ley", "nl-ens", "nl-ams", "nl-utc", "nl-rtm", "nl-ude", "nl-glz", "nl-ein", "nl-woe", "nl-mst"]]
        # All NL regional codes should appear before non-NL countries
        first_non_nl = next((i for i, n in enumerate(names) if not n.startswith("nl") and not n.startswith("eu")), len(names))
        last_nl_regional = max((names.index(n) for n in nl_regional), default=0)
        assert last_nl_regional < first_non_nl
    finally:
        settings_module.db = original_db


async def test_get_regions_sorted_by_explicit_scope(test_db):
    """Test that GET /api/settings/regions?sort_by_scope= overrides current scope."""
    import app.repository.settings as settings_module
    original_db = settings_module.db
    settings_module.db = test_db
    
    try:
        # Set flood scope to us
        await AppSettingsRepository.update(flood_scope="us")
        
        # But explicitly sort by de
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/regions?sort_by_scope=de")
        
        assert response.status_code == 200
        regions = response.json()
        names = [r["name"] for r in regions]
        
        # de should be first (exact match)
        assert names[0] == "de"
        
        # de-mitte should be second (alphabetically first among de-* regional codes)
        assert names[1] == "de-mitte"
        
        # All German regional codes should be grouped together near the top
        de_regional_codes = {"de-mitte", "de-nord", "de-ost", "de-sued", "de-west"}
        de_regional_positions = [names.index(n) for n in de_regional_codes if n in names]
        # They should all be before EU codes and other countries
        assert all(pos < 10 for pos in de_regional_positions)
    finally:
        settings_module.db = original_db


async def test_get_regions_sorted_alphabetically_when_no_scope(test_db):
    """Test that regions are alphabetically sorted when no flood scope is set."""
    import app.repository.settings as settings_module
    original_db = settings_module.db
    settings_module.db = test_db
    
    try:
        # Clear flood scope
        await AppSettingsRepository.update(flood_scope="")
        
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/regions")
        
        assert response.status_code == 200
        regions = response.json()
        names = [r["name"] for r in regions]
        
        # Should be alphabetically sorted
        assert names == sorted(names)
    finally:
        settings_module.db = original_db


async def test_get_regions_sorted_by_nl_iata_code(test_db):
    """Test sorting when flood scope is an IATA code."""
    import app.repository.settings as settings_module
    original_db = settings_module.db
    settings_module.db = test_db
    
    try:
        # Set flood scope to nl-ams (Amsterdam IATA)
        await AppSettingsRepository.update(flood_scope="nl-ams")
        
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/regions")
        
        assert response.status_code == 200
        regions = response.json()
        names = [r["name"] for r in regions]
        
        # nl-ams should be first (exact match)
        assert names[0] == "nl-ams"
        
        # NL regional codes should come before other IATA codes
        nl_regional_codes = {"nl-dr", "nl-fl", "nl-fr", "nl-ge", "nl-gr", "nl-li", "nl-nb", "nl-nh", "nl-ov", "nl-ut", "nl-ze", "nl-zh", "nl-noord", "nl-zuid", "nl-oost", "nl-west", "nl-midden"}
        other_nl_iata = {"nl-grq", "nl-lwr", "nl-dhr", "nl-ley", "nl-ens", "nl-utc", "nl-rtm", "nl-ude", "nl-glz", "nl-ein", "nl-woe", "nl-mst"}
        
        # Find positions
        regional_positions = [names.index(n) for n in nl_regional_codes if n in names]
        iata_positions = [names.index(n) for n in other_nl_iata if n in names and n != "nl-ams"]
        
        # All regional codes should come before other IATA codes (excluding exact match)
        if regional_positions and iata_positions:
            assert max(regional_positions) < min(iata_positions)
    finally:
        settings_module.db = original_db
