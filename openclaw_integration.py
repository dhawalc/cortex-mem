#!/usr/bin/env python3.12
"""
OpenClaw integration module for dual-write to AOMS.

Usage in OpenClaw:
    from openclaw_memory.openclaw_integration import sync_to_aoms
    
    # After writing to workspace
    await sync_to_aoms("episodic", {
        "ts": "2026-02-23T20:00:00Z",
        "type": "achievement",
        "title": "Task completed",
        "outcome": "Success",
        "tags": ["openclaw"]
    })
"""
import asyncio
import httpx
from typing import Dict, Any, Optional
from pathlib import Path
import logging

AOMS_API = "http://localhost:9100"
logger = logging.getLogger("openclaw.aoms")

async def sync_to_aoms(
    tier: str,
    payload: Dict[str, Any],
    entry_type: str = None,
    silent: bool = False
) -> Optional[str]:
    """
    Write entry to AOMS (dual-write pattern).
    
    Args:
        tier: "episodic", "semantic", or "procedural"
        payload: Entry data (must match JSONL schema)
        entry_type: Entry type (e.g., "experience", "fact", "skill")
        silent: If True, log errors but don't raise
    
    Returns:
        Entry ID if successful, None if failed
    """
    # Auto-detect entry type from payload if not specified
    if entry_type is None:
        if "type" in payload and tier == "episodic":
            entry_type = "experience"
        elif "subject" in payload and tier == "semantic":
            entry_type = "fact"
        elif "skill_name" in payload and tier == "procedural":
            entry_type = "skill"
        else:
            entry_type = "unknown"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{AOMS_API}/memory/{tier}",
                json={"tier": tier, "type": entry_type, "payload": payload}
            )
            
            if response.status_code == 200:
                data = response.json()
                entry_id = data.get("id")
                if not silent:
                    logger.info(f"Synced to AOMS: {tier}/{entry_type} ({entry_id})")
                return entry_id
            else:
                logger.error(f"AOMS sync failed: {response.status_code} {response.text}")
                if not silent:
                    raise RuntimeError(f"AOMS sync failed: {response.status_code}")
                return None
    
    except Exception as e:
        logger.error(f"AOMS sync error: {e}")
        if not silent:
            raise
        return None

async def sync_memory_md(content: str, silent: bool = False) -> bool:
    """
    Sync MEMORY.md updates to AOMS.
    
    Writes to modules/memory/MEMORY.md in AOMS.
    """
    try:
        aoms_root = Path("/home/dhawal/cortex-mem/cortex-mem")
        target = aoms_root / "modules/memory/MEMORY.md"
        target.write_text(content)
        
        if not silent:
            logger.info("Synced MEMORY.md to AOMS")
        return True
    
    except Exception as e:
        logger.error(f"MEMORY.md sync error: {e}")
        if not silent:
            raise
        return False

async def sync_daily_log(date: str, content: str, silent: bool = False) -> bool:
    """
    Sync daily log to AOMS (extracts structured events).
    
    Args:
        date: YYYY-MM-DD
        content: Markdown content of daily log
        silent: If True, log errors but don't raise
    """
    import re
    
    try:
        # Parse ## headings as experiences
        sections = re.split(r"\n## ", content)
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            for section in sections[1:]:  # Skip preamble
                lines = section.split("\n", 1)
                if len(lines) < 2:
                    continue
                
                title = lines[0].strip()
                body = lines[1].strip()
                
                # Write to AOMS
                payload = {
                    "tier": "episodic",
                    "type": "experience",
                    "payload": {
                        "ts": f"{date}T12:00:00Z",
                        "type": "observation",
                        "title": title,
                        "outcome": body[:200] + ("..." if len(body) > 200 else ""),
                        "tags": ["daily-log", date],
                    }
                }
                
                response = await client.post(f"{AOMS_API}/memory/episodic", json=payload)
                if response.status_code != 200:
                    logger.warning(f"Failed to sync log entry: {title[:30]}")
        
        if not silent:
            logger.info(f"Synced daily log: {date}")
        return True
    
    except Exception as e:
        logger.error(f"Daily log sync error: {e}")
        if not silent:
            raise
        return False

# Convenience function for common OpenClaw pattern
async def log_achievement(title: str, outcome: str, tags: list = None):
    """Log an achievement to both workspace and AOMS."""
    from datetime import datetime
    
    await sync_to_aoms(
        tier="episodic",
        entry_type="experience",
        payload={
            "ts": datetime.now().isoformat(),
            "type": "achievement",
            "title": title,
            "outcome": outcome,
            "tags": tags or [],
        },
        silent=True  # Don't crash if AOMS is down
    )

async def log_error(title: str, error: str, tags: list = None):
    """Log an error to both workspace and AOMS."""
    from datetime import datetime
    
    await sync_to_aoms(
        tier="episodic",
        entry_type="failure",
        payload={
            "ts": datetime.now().isoformat(),
            "type": "error",
            "title": title,
            "outcome": error,
            "tags": tags or [],
        },
        silent=True
    )

async def log_fact(subject: str, predicate: str, object: str, confidence: float = 1.0, source: str = "openclaw"):
    """Log a semantic fact to AOMS."""
    from datetime import datetime
    
    await sync_to_aoms(
        tier="semantic",
        entry_type="fact",
        payload={
            "ts": datetime.now().isoformat(),
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "confidence": confidence,
            "source": source,
            "tags": [],
        },
        silent=True
    )

# Test if AOMS is available
async def is_aoms_available() -> bool:
    """Check if AOMS service is reachable."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{AOMS_API}/health")
            return response.status_code == 200
    except:
        return False

if __name__ == "__main__":
    # Test integration
    async def test():
        print("Testing AOMS integration...")
        
        # Check if available
        available = await is_aoms_available()
        print(f"AOMS available: {available}")
        
        if available:
            # Test write
            entry_id = await sync_to_aoms(
                tier="episodic",
                entry_type="experience",
                payload={
                    "ts": "2026-02-23T20:54:00Z",
                    "type": "test",
                    "title": "Integration test",
                    "outcome": "Success",
                    "tags": ["test"],
                }
            )
            print(f"Written entry: {entry_id}")
    
    asyncio.run(test())
