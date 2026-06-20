PUBLIC_CHANNEL_KEY = "8B3387E9C5CDEA6AC9E5EDBAA115CD72"
PUBLIC_CHANNEL_NAME = "Public"

# MeshCore GPS trackers publish MCL1 location bodies on this encrypted group-data channel.
TRACKERS_CHANNEL_KEY = "5F303AC5075F800F0F47113199D51053"
TRACKERS_CHANNEL_NAME = "Trackers"


def is_public_channel_key(key: str) -> bool:
    return key.upper() == PUBLIC_CHANNEL_KEY


def is_public_channel_name(name: str) -> bool:
    return name.casefold() == PUBLIC_CHANNEL_NAME.casefold()
