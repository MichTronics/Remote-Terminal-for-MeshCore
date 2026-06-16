"""
Debug script to check if a LOCATION packet node_id matches any contacts.
"""
import asyncio
import sys
from app.database import get_session
from app.repository.contacts import ContactRepository

async def check_node_match(node_id: str):
    """Check if any contacts match the given node_id prefix."""
    async with get_session() as session:
        contacts = await ContactRepository.get_all()
        
    print(f"\nSearching for contacts matching node_id: {node_id}")
    print(f"Total contacts: {len(contacts)}\n")
    
    matches = []
    for c in contacts:
        if c.public_key.lower().startswith(node_id.lower()):
            matches.append(c)
            print(f"✅ MATCH FOUND:")
            print(f"   Name: {c.name or '(no name)'}")
            print(f"   Public Key: {c.public_key}")
            print(f"   Current Location: {c.lat}, {c.lon}")
            print(f"   Last Seen: {c.last_seen}")
            print()
    
    if not matches:
        print("❌ No contacts found matching this node_id")
        print("\nShowing all contacts (first 10 chars of public key):")
        for c in contacts[:20]:  # Show first 20
            print(f"   {c.public_key[:10]}... - {c.name or '(no name)'} at {c.lat}, {c.lon}")
    
    return matches

if __name__ == "__main__":
    node_id = sys.argv[1] if len(sys.argv) > 1 else "109da48c"
    asyncio.run(check_node_match(node_id))
