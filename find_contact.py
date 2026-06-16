"""Find a specific contact by full or partial public key."""
import asyncio
import sys

async def find_contact(search_key: str):
    from app.database import db
    from app.repository.contacts import ContactRepository
    
    if db._connection is None:
        await db.connect()
    
    contacts = await ContactRepository.get_all()
    
    print(f"\nSearching for contact: {search_key}")
    print(f"Total contacts in database: {len(contacts)}\n")
    
    # Try exact match first
    for c in contacts:
        if c.public_key.lower() == search_key.lower():
            print("✅ EXACT MATCH FOUND:")
            print(f"   Name: {c.name or '(no name)'}")
            print(f"   Public Key: {c.public_key}")
            print(f"   Location: {c.lat}, {c.lon}")
            print(f"   Last Seen: {c.last_seen}")
            print(f"   On Radio: {bool(c.on_radio)}")
            return
    
    # Try prefix match
    matches = []
    for c in contacts:
        if c.public_key.lower().startswith(search_key.lower()):
            matches.append(c)
    
    if matches:
        print(f"✅ Found {len(matches)} contact(s) starting with '{search_key}':")
        for c in matches:
            print(f"\n   Name: {c.name or '(no name)'}")
            print(f"   Public Key: {c.public_key}")
            print(f"   Location: {c.lat}, {c.lon}")
            print(f"   Last Seen: {c.last_seen}")
            print(f"   On Radio: {bool(c.on_radio)}")
    else:
        print(f"❌ No contact found matching '{search_key}'")
        print(f"\n💡 This means the LOCATION packet is from a node you haven't seen advertise yet.")
        print(f"   The node needs to send an ADVERTISEMENT packet first to register its full public key.")

if __name__ == "__main__":
    search = sys.argv[1] if len(sys.argv) > 1 else "109da48ca8fb1ff1fa2dd1348e365fb63ad82cad0552d8831caa9bf7625ba75e"
    asyncio.run(find_contact(search))
