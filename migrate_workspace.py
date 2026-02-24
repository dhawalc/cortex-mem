#!/usr/bin/env python3.12
"""
Migration script: Copy OpenClaw workspace files → AOMS structure.
Non-destructive - copies only, never deletes source files.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
import yaml
import json
import re
import httpx

WORKSPACE = Path("/home/dhawal/.openclaw/workspace")
AOMS_ROOT = Path("/home/dhawal/cortex-mem/cortex-mem")
AOMS_API = "http://localhost:9100"

async def migrate_user_md():
    """Convert USER.md → modules/identity/values.yaml"""
    user_md = WORKSPACE / "USER.md"
    if not user_md.exists():
        print("❌ USER.md not found")
        return
    
    content = user_md.read_text()
    
    # Extract structured data (simple parser)
    values = {
        "name": "Dhawal",
        "location": "Milpitas, CA",
        "timezone": "America/Los_Angeles",
        "updated_at": datetime.now().isoformat(),
    }
    
    # Parse basics section
    if match := re.search(r"## Basics\n(.*?)\n##", content, re.DOTALL):
        basics = match.group(1)
        if m := re.search(r"\*\*Name:\*\* (.+)", basics):
            values["name"] = m.group(1)
        if m := re.search(r"\*\*Location:\*\* (.+)", basics):
            values["location"] = m.group(1)
        if m := re.search(r"\*\*Timezone:\*\* (.+)", basics):
            values["timezone"] = m.group(1)
    
    # Parse work section
    if match := re.search(r"## Work\n(.*?)\n##", content, re.DOTALL):
        work = match.group(1).strip()
        values["work"] = [line.strip("- ") for line in work.split("\n") if line.startswith("-")]
    
    # Parse projects section
    if match := re.search(r"## Projects\n(.*?)\n##", content, re.DOTALL):
        projects = match.group(1).strip()
        values["projects"] = [line.strip("- **").split(":**")[0] for line in projects.split("\n") if line.startswith("- **")]
    
    # Write YAML
    target = AOMS_ROOT / "modules/identity/values.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as f:
        yaml.dump(values, f, default_flow_style=False, sort_keys=False)
    
    print(f"✅ Migrated USER.md → {target.relative_to(AOMS_ROOT)}")

async def migrate_memory_md():
    """Copy MEMORY.md → modules/memory/MEMORY.md"""
    memory_md = WORKSPACE / "MEMORY.md"
    if not memory_md.exists():
        print("❌ MEMORY.md not found")
        return
    
    target = AOMS_ROOT / "modules/memory/MEMORY.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(memory_md.read_text())
    
    print(f"✅ Copied MEMORY.md → {target.relative_to(AOMS_ROOT)}")

async def migrate_identity_md():
    """Copy IDENTITY.md → modules/identity/IDENTITY.md"""
    identity_md = WORKSPACE / "IDENTITY.md"
    if not identity_md.exists():
        print("❌ IDENTITY.md not found")
        return
    
    target = AOMS_ROOT / "modules/identity/IDENTITY.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(identity_md.read_text())
    
    print(f"✅ Copied IDENTITY.md → {target.relative_to(AOMS_ROOT)}")

async def migrate_soul_md():
    """Copy SOUL.md → modules/identity/voice.md"""
    soul_md = WORKSPACE / "SOUL.md"
    if not soul_md.exists():
        print("❌ SOUL.md not found")
        return
    
    target = AOMS_ROOT / "modules/identity/voice.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(soul_md.read_text())
    
    print(f"✅ Copied SOUL.md → {target.relative_to(AOMS_ROOT)}")

async def migrate_daily_logs():
    """Convert memory/YYYY-MM-DD.md → episodic/experiences.jsonl via API"""
    memory_dir = WORKSPACE / "memory"
    if not memory_dir.exists():
        print("❌ memory/ directory not found")
        return
    
    daily_logs = sorted(memory_dir.glob("????-??-??.md"))
    if not daily_logs:
        print("⚠️  No daily logs found")
        return
    
    async with httpx.AsyncClient() as client:
        for log_file in daily_logs:
            date = log_file.stem
            content = log_file.read_text()
            
            # Simple parser: extract ## headings as experiences
            sections = re.split(r"\n## ", content)
            for section in sections[1:]:  # Skip preamble
                lines = section.split("\n", 1)
                if len(lines) < 2:
                    continue
                
                title = lines[0].strip()
                body = lines[1].strip()
                
                # Write to AOMS via API
                payload = {
                    "tier": "episodic",
                    "type": "experience",
                    "payload": {
                        "ts": f"{date}T12:00:00Z",
                        "type": "observation",
                        "title": title,
                        "outcome": body[:200] + ("..." if len(body) > 200 else ""),
                        "tags": ["migrated", date],
                    }
                }
                
                response = await client.post(f"{AOMS_API}/memory/episodic", json=payload)
                if response.status_code == 200:
                    print(f"  ✓ {date}: {title[:50]}")
                else:
                    print(f"  ✗ {date}: {title[:50]} (status {response.status_code})")
    
    print(f"✅ Migrated {len(daily_logs)} daily logs")

async def migrate_docs():
    """Copy docs/*.md → modules/research/"""
    docs_dir = WORKSPACE / "docs"
    if not docs_dir.exists():
        print("❌ docs/ directory not found")
        return
    
    target_dir = AOMS_ROOT / "modules/research"
    target_dir.mkdir(parents=True, exist_ok=True)
    
    md_files = list(docs_dir.glob("*.md"))
    for doc in md_files:
        target = target_dir / doc.name
        target.write_text(doc.read_text())
    
    print(f"✅ Copied {len(md_files)} docs → {target_dir.relative_to(AOMS_ROOT)}")

async def main():
    print("=" * 60)
    print("OpenClaw Workspace → AOMS Migration")
    print("=" * 60)
    print()
    
    # Check AOMS service is running
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AOMS_API}/health")
            if response.status_code != 200:
                print("❌ AOMS service not responding")
                sys.exit(1)
    except Exception as e:
        print(f"❌ AOMS service not reachable: {e}")
        sys.exit(1)
    
    print("✓ AOMS service running\n")
    
    # Run migrations
    await migrate_user_md()
    await migrate_memory_md()
    await migrate_identity_md()
    await migrate_soul_md()
    await migrate_daily_logs()
    await migrate_docs()
    
    print()
    print("=" * 60)
    print("Migration complete!")
    print("=" * 60)
    print()
    print(f"AOMS root: {AOMS_ROOT}")
    print(f"Original workspace: {WORKSPACE} (untouched)")

if __name__ == "__main__":
    asyncio.run(main())
