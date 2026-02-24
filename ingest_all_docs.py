#!/usr/bin/env python3.12
"""Ingest all research docs into Cortex L0/L1/L2."""
import asyncio
import httpx
from pathlib import Path
import sys

AOMS_API = "http://localhost:9100"
RESEARCH_DIR = Path("/home/dhawal/cortex-mem/cortex-mem/modules/research")

async def ingest_all():
    """Ingest all markdown files in research directory."""
    md_files = sorted(RESEARCH_DIR.glob("*.md"))
    
    print(f"Found {len(md_files)} markdown files to ingest\n")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, doc_path in enumerate(md_files, 1):
            content = doc_path.read_text()
            title = doc_path.stem.replace('_', ' ').replace('-', ' ').title()
            
            print(f"[{i}/{len(md_files)}] Ingesting: {title}")
            print(f"  Size: {len(content):,} chars")
            
            try:
                response = await client.post(
                    f"{AOMS_API}/cortex/ingest",
                    json={
                        "title": title,
                        "content": content,
                        "hierarchy_path": f"/research/{doc_path.stem}",
                        "doc_type": "research",
                        "tags": ["research", "migrated"]
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"  ✅ L0: {data['l0_tokens']} tokens, L1: {data['l1_tokens']} tokens, L2: {data['l2_tokens']} tokens")
                    print(f"  📄 doc_id: {data['doc_id'][:16]}...")
                else:
                    print(f"  ❌ Error: {response.status_code} {response.text[:100]}")
            
            except Exception as e:
                print(f"  ❌ Exception: {e}")
            
            print()
    
    # Summary
    response = await client.get(f"{AOMS_API}/cortex/documents")
    if response.status_code == 200:
        docs = response.json()["documents"]
        total_l0 = sum(d["l0_tokens"] for d in docs)
        total_l1 = sum(d["l1_tokens"] for d in docs)
        total_l2 = sum(d["l2_tokens"] for d in docs)
        
        print("=" * 60)
        print(f"Ingestion complete: {len(docs)} documents")
        print(f"Total L0 tokens: {total_l0:,} ({100*total_l0/total_l2:.1f}% of L2)")
        print(f"Total L1 tokens: {total_l1:,} ({100*total_l1/total_l2:.1f}% of L2)")
        print(f"Total L2 tokens: {total_l2:,}")
        print(f"Token reduction (L0): {100*(1-total_l0/total_l2):.1f}%")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(ingest_all())
