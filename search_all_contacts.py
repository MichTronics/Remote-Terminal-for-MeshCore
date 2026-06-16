"""Search ALL contacts for the tracker node_id (no limit)."""
import asyncio

async def search_all_contacts():
    from app.database import db
    from app.repository.contacts import ContactRepository
    
    if db._connection is None:
        await db.connect()
    
    # Get ALL contacts by setting a very high limit
    contacts = await ContactRepository.get_all(limit=999999)
    print(f"Total contacts in database: {len(contacts)}\n")
    
    target_prefix = "109da48c"
    
    print(f"Searching for contact starting with '{target_prefix}'...\n")
    
    for c in contacts:
        if c.public_key.lower().startswith(target_prefix.lower()):
            print(f"✅ FOUND IT!")
            print(f"   Name: {c.name or '(no name)'}")
            print(f"   Public Key: {c.public_key}")
            print(f"   Location: {c.lat}, {c.lon}")
            print(f"   Last Seen: {c.last_seen}")
            print(f"   On Radio: {bool(c.on_radio)}")
            print(f"\n✅ This contact SHOULD be updated by LOCATION packets!")
            print(f"   The node_id {target_prefix} matches this public key.")
            return
    
    print(f"❌ No contact found starting with '{target_prefix}'")
    print(f"\nSearching by GPS coordinates near the tracker location (52.7°N, 5.2°E)...")
    
    matches_by_location = []
    for c in contacts:
        if c.lat and c.lon and 52.65 < c.lat < 52.75 and 5.15 < c.lon < 5.35:
            matches_by_location.append(c)
            print(f"\n   Name: {c.name or '(no name)'}")
            print(f"   Public Key (first 16): {c.public_key[:16]}...")
            print(f"   Location: {c.lat}, {c.lon}")
            print(f"   Node ID (first 8 chars): {c.public_key[:8].lower()}")
    
    if matches_by_location:
        print(f"\n\nFound {len(matches_by_location)} contact(s) near the tracker location.")
        print(f"But NONE of them have public keys starting with '109da48c'.")
        print(f"\nThis means the LOCATION packet's node_id doesn't match any stored contact.")

if __name__ == "__main__":
    asyncio.run(search_all_contacts())
