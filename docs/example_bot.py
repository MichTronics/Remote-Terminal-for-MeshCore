# Example bot for #noordtest channel
# This bot responds to "!test" with hop count information
#
# To use this bot:
# 1. Go to Settings > Fanout in the RemoteTerm web interface
# 2. Create a new Bot fanout config
# 3. Paste this entire code
# 4. Configure the scope to listen to the #noordtest channel
# 5. Enable the bot

def bot(sender_name, sender_key, message_text, is_dm, channel_key, channel_name, sender_timestamp, received_at, path, is_outgoing=False, path_bytes_per_hop=None, packet_hash=None, region_name=None, **kwargs):
    """
    Responds to !test command in #noordtest channel with hop count, delay, and region information.
    
    Parameters:
        sender_name: Display name of the sender (may be None)
        sender_key: 64-char hex public key of sender for DMs, None for channel messages
        message_text: The message content (for channels, this is without the "sender: " prefix)
        is_dm: True for direct messages, False for channel messages
        channel_key: 32-char hex channel key for channel messages, None for DMs
        channel_name: Channel name (e.g. "#noordtest" with hash), None for DMs
        sender_timestamp: Sender's timestamp from the message (may be None)
        received_at: Unix timestamp when message was received by this radio (may be None)
        path: Hex-encoded routing path (may be None)
        is_outgoing: True if this is our own outgoing message
        path_bytes_per_hop: Number of bytes per routing hop (1, 2, or 3), if known
        packet_hash: MeshCore packet hash (first 16 hex chars of SHA256, uppercase), if known
        region_name: MeshCore transport region name (e.g., "us", "nl"), if identified
        **kwargs: Forward compatibility for future parameters
    """
    
    # Only respond to DMs or specific channels
    allowed_channels = ["#testnoord", "#test", "#bot"]
    if not is_dm and channel_name not in allowed_channels:
        return None

    # Ignore our own outgoing messages to prevent loops
    if is_outgoing:
        return None
    
    # Only respond to !test command (case-insensitive)
    if message_text.strip().lower() != "!regio":
        return None
    
    # Start building the response with sender name
    sender = sender_name or f"Unknown"
    response = f"✨️ Received from {sender}"
    
    # Calculate number of hops from path data
    if path and isinstance(path, str) and path_bytes_per_hop:
        # Path is a hex string representing routing hops
        # Each hop is encoded in 1, 2, or 3 bytes depending on path_hash_mode
        # Convert hex string length to byte count, then divide by bytes per hop
        path_bytes = len(path) // 2  # 2 hex chars = 1 byte
        hop_count = path_bytes // path_bytes_per_hop
        if hop_count == 0:
            response += f" 📨 direct connection"
        else:
            response += f" 📨 with {hop_count} hop{'s' if hop_count != 1 else ''}"
        
    elif path and isinstance(path, str):
        # Legacy: assume 1-byte hops if path_bytes_per_hop not provided
        hop_count = len(path) // 2
        if hop_count == 0:
            response += f" 📨 direct connection"
        else:
            response += f" 📨 with {hop_count} hop{'s' if hop_count != 1 else ''}"
    
    # Calculate message delay if both timestamps are available
    if sender_timestamp and received_at and isinstance(sender_timestamp, int) and isinstance(received_at, int):
        delay_seconds = received_at - sender_timestamp
        if delay_seconds >= 0:
            response += f"⏳ It took {delay_seconds} second{'s' if delay_seconds != 1 else ''} to reach me"
    
    # Add region information if available
    if region_name:
        response += f". 🌐 Region: {region_name}"
    else:
        response += f". 🌐 Regio not set/unknown"
    
    return response


# NOTE: Timing and region information are available!
# ===================================================
# This bot demonstrates how to use:
# - received_at: Unix timestamp when message was received by this radio
# - sender_timestamp: Unix timestamp when sender created the message
# - region_name: MeshCore transport region (e.g., "us", "nl", "eu")
# - sender_name: Display name of the sender
# - path_bytes_per_hop: Hop encoding size (1, 2, or 3 bytes)
#
# Example output:
# "Test received from Mussel with 3 hops. It took 5 seconds to reach me. Region: nl"
#
# The delay calculation (received_at - sender_timestamp) shows how long the message
# took to propagate through the mesh network from sender to receiver.
