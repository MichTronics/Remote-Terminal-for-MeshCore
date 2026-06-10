"""
NL-Alert Bot for RemoteTerm

This script polls the NL-Alert API for emergency alerts and forwards them to a MeshCore channel.
Run this script periodically (e.g., every 15 minutes via cron or Task Scheduler).

Configuration:
- REMOTETERM_API_URL: URL to your RemoteTerm instance (default: http://localhost:8000)
- CHANNEL_KEY: The channel key to send alerts to (32-char hex)
- BOUNDING_BOX: Geographic area filter (min_lat, min_lng, max_lat, max_lng)
- STATE_FILE: Path to store seen alert IDs (default: nl_alert_state.json)

Usage:
    python example_nlalerd.py

Requirements:
    pip install requests

Example cron (every 15 minutes):
    */15 * * * * /usr/bin/python3 /path/to/example_nlalerd.py >> /var/log/nlalert.log 2>&1
Or on Windows to Run every 15 minutes:
    schtasks /create /tn "NL-Alert Bot" /tr "python d:\MyPython\Remote-Terminal-for-MeshCore\docs\example_nlalerd.py" /sc minute /mo 15
"""

import requests
import logging
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Set, Tuple, Optional

# ===========================
# Configuration
# ===========================

# RemoteTerm API URL
REMOTETERM_API_URL = os.getenv("REMOTETERM_API_URL", "http://localhost:8000")

# Channel key to send alerts to (32-char hex string)
# You can find channel keys in RemoteTerm Settings > Channels
CHANNEL_KEY = os.getenv("NL_ALERT_CHANNEL_KEY", "your_channel_key_here")

# Geographic bounding box filter (min_lat, min_lng, max_lat, max_lng)
# Example: Netherlands - adjust to your region of interest
# Default covers a region in the Netherlands around Groningen/Drenthe
BOUNDING_BOX = (
    float(os.getenv("NL_ALERT_MIN_LAT", "52.489637")),
    float(os.getenv("NL_ALERT_MIN_LNG", "5.351001")),
    float(os.getenv("NL_ALERT_MAX_LAT", "53.576271")),
    float(os.getenv("NL_ALERT_MAX_LNG", "7.240975"))
)

# State file to track seen alerts
STATE_FILE = Path(os.getenv("NL_ALERT_STATE_FILE", "nl_alert_state.json"))

# NL-Alert API URL
NL_ALERT_API_URL = "https://api.public-warning.app/api/v1/providers/nl-alert/alerts?filter=last-24h"

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nl_alert_bot")


# ===========================
# Helper Functions
# ===========================

def load_seen_alerts() -> Set[str]:
    """Load previously seen alert IDs from state file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                return set(data.get("seen_alerts", []))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Error loading state file: {e}")
            return set()
    return set()


def save_seen_alerts(seen_alerts: Set[str]):
    """Save seen alert IDs to state file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({"seen_alerts": list(seen_alerts)}, f, indent=2)
    except IOError as e:
        logger.error(f"Error saving state file: {e}")


def is_first_run() -> bool:
    """Check if this is the first run (no state file exists)."""
    return not STATE_FILE.exists()


def parse_area_polygon(area: list) -> list[Tuple[float, float]]:
    """
    Parse area polygon from NL-Alert format.
    
    Args:
        area: List of strings with space-separated lat,lng pairs
        
    Returns:
        List of (lat, lng) tuples
    """
    polygon = []
    for area_string in area:
        for coord_pair in area_string.strip().split():
            try:
                lat, lng = map(float, coord_pair.split(','))
                polygon.append((lat, lng))
            except ValueError:
                logger.warning(f"Invalid coordinate pair: {coord_pair}")
    return polygon


def is_in_bounding_box(polygon: list[Tuple[float, float]], bbox: Tuple[float, float, float, float]) -> bool:
    """
    Check if any point of the polygon is within the bounding box.
    
    Args:
        polygon: List of (lat, lng) tuples
        bbox: (min_lat, min_lng, max_lat, max_lng)
        
    Returns:
        True if any point intersects the bounding box
    """
    min_lat, min_lng, max_lat, max_lng = bbox
    
    for lat, lng in polygon:
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            return True
    
    return False


def extract_dutch_message(message: str) -> Optional[str]:
    """
    Extract Dutch portion of message (before " *** ").
    
    Args:
        message: Full message with Dutch and English sections
        
    Returns:
        Dutch message portion, or None if separator not found
    """
    if " *** " in message:
        dutch_part = message.split(" *** ")[0].strip()
        return dutch_part
    else:
        logger.warning("Message does not contain ' *** ' separator")
        return None


def remove_urls(text: str) -> str:
    """Remove URLs from text."""
    # Remove http/https URLs
    text = re.sub(r'https?://\S+', '', text)
    # Remove www. URLs
    text = re.sub(r'www\.\S+', '', text)
    # Clean up extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_nl_alerts() -> list:
    """Fetch alerts from NL-Alert API."""
    try:
        logger.info(f"Fetching alerts from {NL_ALERT_API_URL}")
        response = requests.get(NL_ALERT_API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except requests.RequestException as e:
        logger.error(f"Error fetching NL-Alert data: {e}")
        return []


def send_to_channel(message: str) -> bool:
    """
    Send message to RemoteTerm channel.
    
    Args:
        message: Message to send
        
    Returns:
        True if successful, False otherwise
    """
    try:
        url = f"{REMOTETERM_API_URL}/api/messages/channel"
        payload = {
            "channel_key": CHANNEL_KEY,
            "text": message
        }
        
        logger.info(f"Sending alert to channel: {message[:50]}...")
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Alert sent successfully")
        return True
    except requests.RequestException as e:
        logger.error(f"Error sending message to RemoteTerm: {e}")
        return False


def process_alert(alert: dict, seen_alerts: Set[str], first_run: bool) -> bool:
    """
    Process a single alert and send if it's new and relevant.
    
    Args:
        alert: Alert dictionary from API
        seen_alerts: Set of previously seen alert IDs
        first_run: Whether this is the first run
        
    Returns:
        True if alert was processed and sent, False otherwise
    """
    alert_id = alert.get("id")
    alert_type = alert.get("type")
    message = alert.get("message", "")
    start_at = alert.get("start_at")
    stop_at = alert.get("stop_at")
    area = alert.get("area", [])
    
    # Create unique key from ID and start_at
    alert_key = f"{alert_id}_{start_at}"
    
    # Skip if already seen
    if alert_key in seen_alerts:
        logger.debug(f"Skipping already seen alert: {alert_id}")
        return False
    
    # Add to seen set
    seen_alerts.add(alert_key)
    
    # Check if alert has already stopped
    if stop_at and isinstance(stop_at, str):
        try:
            stop_time = datetime.fromisoformat(stop_at.replace('Z', '+00:00'))
            now = datetime.now(stop_time.tzinfo)
            if now > stop_time:
                logger.info(f"Skipping expired alert {alert_id} (stopped at {stop_at})")
                return False
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse stop_at time for alert {alert_id}: {e}")
    
    # If first run, just store without sending
    if first_run:
        logger.info(f"First run: storing alert {alert_id} without sending")
        return False
    
    # Check type is "alert"
    if alert_type != "alert":
        logger.info(f"Skipping non-alert type: {alert_type}")
        return False
    
    # Ignore test messages
    if message.startswith("TESTBERICHT"):
        logger.info(f"Skipping test message: {alert_id}")
        return False
    
    # Check area is within bounding box
    if area:
        polygon = parse_area_polygon(area)
        if not is_in_bounding_box(polygon, BOUNDING_BOX):
            logger.info(f"Skipping alert outside bounding box: {alert_id}")
            return False
    
    # Extract Dutch message
    dutch_message = extract_dutch_message(message)
    if not dutch_message:
        logger.warning(f"Could not extract Dutch message from alert: {alert_id}")
        return False
    
    # Remove URLs
    clean_message = remove_urls(dutch_message)
    
    # Format alert for sending
    if start_at and isinstance(start_at, str):
        start_time = datetime.fromisoformat(start_at.replace('Z', '+00:00'))
        formatted_message = f"🚨 NL-Alert ({start_time.strftime('%d-%m %H:%M')})\n{clean_message}"
    else:
        formatted_message = f"🚨 NL-Alert\n{clean_message}"
    
    # Send to channel
    return send_to_channel(formatted_message)


def main():
    """Main execution function."""
    logger.info("=== NL-Alert Bot Starting ===")
    
    # Validate configuration
    if CHANNEL_KEY == "your_channel_key_here":
        logger.error("CHANNEL_KEY not configured! Set NL_ALERT_CHANNEL_KEY environment variable.")
        sys.exit(1)
    
    # Load seen alerts
    seen_alerts = load_seen_alerts()
    first_run = is_first_run()
    
    if first_run:
        logger.info("First run detected - will store alerts without sending")
    
    logger.info(f"Previously seen alerts: {len(seen_alerts)}")
    logger.info(f"Bounding box: {BOUNDING_BOX}")
    
    # Fetch alerts
    alerts = fetch_nl_alerts()
    logger.info(f"Retrieved {len(alerts)} alerts from API")
    
    # Process each alert
    new_count = 0
    sent_count = 0
    
    for alert in alerts:
        if process_alert(alert, seen_alerts, first_run):
            sent_count += 1
            new_count += 1
        elif alert.get("id") and f"{alert.get('id')}_{alert.get('start_at')}" not in seen_alerts:
            new_count += 1
    
    # Save updated seen alerts
    save_seen_alerts(seen_alerts)
    
    logger.info(f"Processed {new_count} new alerts, sent {sent_count} messages")
    logger.info("=== NL-Alert Bot Complete ===")


if __name__ == "__main__":
    main()
