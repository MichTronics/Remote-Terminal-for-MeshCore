"""Region management API endpoints."""
import logging
import time

from fastapi import APIRouter, HTTPException, Query

from app.models import Region, RegionCreate
from app.packet_processor import derive_meshcore_region_key
from app.repository import AppSettingsRepository, RegionRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/regions", tags=["settings", "regions"])

# Common region codes to seed on first startup We might have to figure out a other way
# as world wide this gone be like 20000+ regions, but for testing/demo purposes we can start with a smaller set of common regions.
DEFAULT_REGIONS = [
    # Country codes (ISO 3166-1 alpha-2)
    "us", "ca", "mx",  # North America
    "nl", "de", "uk", "gb", "fr", "es", "it", "be", "ch", "at", "se", "no", "dk", "fi", "pl", "cz", # Europe
    "au", "nz",  # Oceania
    "jp", "kr", "cn", "in", "sg",  # Asia
    "br", "ar", "cl",  # South America
    "za",  # Africa
    "eu", "eu-west", "eu-east", "eu-north", "eu-south", "europe", "bx", # European regions (bx = Benelux)
    # Common regional/local codes Holland/Netherlands
    "nl-dr", "nl-fl", "nl-fr", "nl-ge", "nl-gr", "nl-li", "nl-nb", "nl-nh", "nl-ov", "nl-ut", "nl-ze", "nl-zh",
    "nl-noord", "nl-zuid", "nl-oost", "nl-west", "nl-midden",
    # Common city/local codes Holland/Netherlands
    "nl-hag", "nl-ein", "nl-ams", "nl-aer", "nl-dev", "nl-lid", "nl-ass", "nl-ede", "nl-ens", "nl-rtm",
    # Common regional/local codes Germany
    "de-nord", "de-west", "de-mitte", "de-ost", "de-sued", "de-ni", "de-nw",
    # Common regional/local codes United Kingdom
    "eng", "eng-ne", "eng-nw", "eng-se", "eng-sw",
    # NL IATA Regions (for testing/demo purposes)
    "nl-grq", "nl-lwr", "nl-dhr", "nl-ley", "nl-ens", "nl-ams", "nl-utc", "nl-rtm", "nl-ude", "nl-glz", "nl-ein", "nl-woe", "nl-mst",
]

# Region classification for smart sorting
REGION_CATEGORIES = {
    # Netherlands regional codes
    "nl-regional": {
        "nl-dr", "nl-fl", "nl-fr", "nl-ge", "nl-gr", "nl-li", "nl-nb", "nl-nh", "nl-ov", "nl-ut", "nl-ze", "nl-zh",
        "nl-noord", "nl-zuid", "nl-oost", "nl-west", "nl-midden",
        "nl-hag", "nl-ein", "nl-ams", "nl-aer", "nl-dev", "nl-lid", "nl-ass", "nl-ede", "nl-ens", "nl-rtm", "nl-bx",
    },
    # Netherlands IATA codes
    "nl-iata": {
        "nl-grq", "nl-lwr", "nl-dhr", "nl-ley", "nl-ens", "nl-ams", "nl-utc", "nl-rtm", "nl-ude", "nl-glz", "nl-ein", "nl-woe", "nl-mst",
    },
    # Germany regional codes
    "de-regional": {
        "de-nord", "de-west", "de-mitte", "de-ost", "de-sued", "de-ni", "de-nw",
    },
    # UK regional codes
    "uk-regional": {
        "eng", "eng-ne", "eng-nw", "eng-se", "eng-sw",
    },
    # Country codes
    "country": {
        "us", "ca", "mx", "nl", "de", "uk", "gb", "fr", "es", "it", "be", "ch", "at", "se", "no", "dk", "fi", "pl", "cz", "bx",
        "au", "nz", "jp", "kr", "cn", "in", "sg", "br", "ar", "cl", "za",
    },
    # European region codes
    "eu-regional": {
        "eu", "eu-west", "eu-east", "eu-north", "eu-south", "europe",
    },
}


def smart_sort_regions(regions: list[Region], current_scope: str) -> list[Region]:
    """Sort regions based on relevance to the current flood scope.
    
    Priority order depends on the current scope:
    1. Exact match (always first)
    2. Same country regional codes (e.g., for "nl-gr" → other "nl-*" regional codes)
    3. Same country IATA codes (e.g., for "nl-gr" → "nl-grq", "nl-ams", etc.)
    4. Country code itself (e.g., "nl")
    5. Other European regions (if current scope is European)
    6. All other regions (alphabetically)
    """
    if not current_scope:
        # No scope set - return alphabetically
        return sorted(regions, key=lambda r: r.name.lower())
    
    scope_lower = current_scope.lower()
    
    # Detect country prefix (e.g., "nl" from "nl-gr")
    country_prefix = scope_lower.split("-")[0] if "-" in scope_lower else scope_lower
    
    def get_sort_key(region: Region) -> tuple[int, str]:
        """Return (priority, name) tuple for sorting."""
        name_lower = region.name.lower()
        
        # Priority 0: Exact match
        if name_lower == scope_lower:
            return (0, name_lower)
        
        # Priority 1: Same country regional codes
        regional_key = f"{country_prefix}-regional"
        if regional_key in REGION_CATEGORIES and name_lower in REGION_CATEGORIES[regional_key]:
            return (1, name_lower)
        
        # Priority 2: Same country IATA codes
        iata_key = f"{country_prefix}-iata"
        if iata_key in REGION_CATEGORIES and name_lower in REGION_CATEGORIES[iata_key]:
            return (2, name_lower)
        
        # Priority 3: Country code itself
        if name_lower == country_prefix:
            return (3, name_lower)
        
        # Priority 4: European regions (if current scope is European)
        if country_prefix in {"nl", "de", "uk", "gb", "fr", "es", "it", "be", "ch", "at", "se", "no", "dk", "fi", "pl", "cz", "bx", "eu"}:
            if name_lower in REGION_CATEGORIES["eu-regional"]:
                return (4, name_lower)
        
        # Priority 5: Everything else
        return (5, name_lower)
    
    return sorted(regions, key=get_sort_key)

async def seed_default_regions() -> None:
    """Ensure default public regions exist in the database."""
    existing_regions = await RegionRepository.get_all()
    existing_names = {r.name for r in existing_regions}
    
    regions_created = 0
    for region_name in DEFAULT_REGIONS:
        if region_name not in existing_names:
            try:
                # Derive key from name for public regions
                key_bytes = derive_meshcore_region_key(region_name)
                await RegionRepository.create(
                    name=region_name,
                    key=key_bytes,
                    is_public=True,
                )
                regions_created += 1
            except Exception:
                logger.warning("Failed to seed region '%s'", region_name, exc_info=True)
    
    if regions_created > 0:
        logger.info("Seeded %d default regions", regions_created)


@router.get("", response_model=list[Region])
async def get_regions(
    sort_by_scope: str | None = Query(
        default=None,
        description="Sort regions by relevance to this flood scope (e.g., 'nl-gr'). If omitted, uses current app flood_scope.",
    ),
) -> list[Region]:
    """Get all defined MeshCore transport regions.
    
    Regions are intelligently sorted based on the current or provided flood scope:
    - Exact match appears first
    - Same-country regional codes
    - Same-country IATA codes  
    - Country code
    - Related regional groups
    - All others alphabetically
    """
    regions = await RegionRepository.get_all()
    
    # Determine which scope to use for sorting
    if sort_by_scope is None:
        # Use current app flood_scope
        settings = await AppSettingsRepository.get()
        sort_scope = settings.flood_scope
    else:
        sort_scope = sort_by_scope
    
    # Apply smart sorting
    return smart_sort_regions(regions, sort_scope)


@router.post("", response_model=Region, status_code=201)
async def create_region(request: RegionCreate) -> Region:
    """Create a new MeshCore transport region."""
    # Check if region already exists
    existing = await RegionRepository.get_by_name(request.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Region '{request.name}' already exists")

    # Validate region configuration
    if not request.is_public and not request.key:
        raise HTTPException(
            status_code=400,
            detail="Private regions must provide an explicit 16-byte hex key",
        )

    # Derive or store the region key
    if request.is_public:
        # Public region - derive key from name and store it for faster lookup
        key_bytes = derive_meshcore_region_key(request.name)
    else:
        # Private region - use provided key
        assert request.key is not None  # Validated above
        key_bytes = bytes.fromhex(request.key)

    region = await RegionRepository.create(
        name=request.name,
        key=key_bytes,
        is_public=request.is_public,
    )

    logger.info(
        "Created region '%s' (%s)",
        region.name,
        "public" if region.is_public else "private",
    )
    return region


@router.delete("/{name}", status_code=204)
async def delete_region(name: str) -> None:
    """Delete a MeshCore transport region."""
    deleted = await RegionRepository.delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Region '{name}' not found")
    logger.info("Deleted region '%s'", name)
