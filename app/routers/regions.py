"""Region management API endpoints."""
import logging
import time

from fastapi import APIRouter, HTTPException

from app.models import Region, RegionCreate
from app.packet_processor import derive_meshcore_region_key
from app.repository import RegionRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/regions", tags=["settings", "regions"])

# Common region codes to seed on first startup We might have to figure out a other way
# as world wide this gone be like 20000+ regions, but for testing/demo purposes we can start with a smaller set of common regions.
DEFAULT_REGIONS = [
    # Country codes (ISO 3166-1 alpha-2)
    "us", "ca", "mx",  # North America
    "nl", "de", "uk", "gb", "fr", "es", "it", "be", "ch", "at", "se", "no", "dk", "fi", "pl", "cz", "bx", # Europe
    "au", "nz",  # Oceania
    "jp", "kr", "cn", "in", "sg",  # Asia
    "br", "ar", "cl",  # South America
    "za",  # Africa
    "eu", "eu-west", "eu-east", "eu-north", "eu-south", "europe", "bx", # European regions
    # Common regional/local codes Holland/Netherlands
    "nl-dr", "nl-fl", "nl-fr", "nl-ge", "nl-gr", "nl-li", "nl-nb", "nl-nh", "nl-ov", "nl-ut", "nl-ze", "nl-zh",
    "nl-noord", "nl-zuid", "nl-oost", "nl-west", "nl-midden",
    # Common regional/local codes Germany
    "de-nord", "de-west", "de-mitte", "de-ost", "de-sued",
    # Common regional/local codes United Kingdom
    "eng", "eng-ne", "eng-nw", "eng-se", "eng-sw",
    # NL IATA Regions (for testing/demo purposes)
    "nl-grq", "nl-lwr", "nl-dhr", "nl-ley", "nl-ens", "nl-ams", "nl-utc", "nl-rtm", "nl-ude", "nl-glz", "nl-ein", "nl-woe", "nl-mst",
]

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
async def get_regions() -> list[Region]:
    """Get all defined MeshCore transport regions."""
    return await RegionRepository.get_all()


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
