#!/usr/bin/env python3.12
"""
Daemon integration module for AOMS.

Usage in Daemon:
    from daemon_integration import AOMemoryClient
    
    # Replace Daemon's Cortex queries with AOMS
    aoms = AOMemoryClient()
    results = await aoms.smart_query("trading strategies with Sharpe > 1.4", token_budget=2000)
"""
import asyncio
import httpx
from typing import Dict, Any, Optional, List
import logging

AOMS_API = "http://localhost:9100"
logger = logging.getLogger("daemon.aoms")

class AOMemoryClient:
    """Daemon client for AOMS with Cortex L0/L1/L2 support."""
    
    def __init__(self, base_url: str = AOMS_API):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def smart_query(
        self,
        query: str,
        token_budget: int = 2000,
        directory: str = None,
        tier: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Smart query with auto-escalation (L0 → L1 → L2).
        
        Args:
            query: Search query
            token_budget: Max tokens to return
            directory: Filter by hierarchy path (e.g., "/research", "/strategies")
            tier: Filter by tier (["episodic", "semantic"])
        
        Returns:
            {
                "query": str,
                "total_tokens": int,
                "results": [{"tier": "l0"|"l1"|"l2", "content": str, "score": float, ...}]
            }
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/cortex/query",
                json={
                    "query": query,
                    "token_budget": token_budget,
                    "directory": directory,
                }
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"AOMS smart_query failed: {e}")
            raise
    
    async def write_episode(
        self,
        episode_type: str,
        title: str,
        outcome: str,
        tags: List[str] = None,
        metadata: Dict[str, Any] = None,
    ) -> Optional[str]:
        """
        Write episode to AOMS episodic memory.
        
        Returns:
            Entry ID if successful
        """
        from datetime import datetime
        
        payload = {
            "ts": datetime.now().isoformat(),
            "type": episode_type,
            "title": title,
            "outcome": outcome,
            "tags": tags or [],
        }
        
        if metadata:
            payload.update(metadata)
        
        try:
            response = await self.client.post(
                f"{self.base_url}/memory/episodic",
                json={"tier": "episodic", "type": "experience", "payload": payload}
            )
            response.raise_for_status()
            return response.json().get("id")
        
        except Exception as e:
            logger.error(f"AOMS write_episode failed: {e}")
            return None
    
    async def write_fact(
        self,
        subject: str,
        predicate: str,
        object: str,
        confidence: float = 1.0,
        source: str = "daemon",
    ) -> Optional[str]:
        """Write fact to AOMS semantic memory."""
        from datetime import datetime
        
        payload = {
            "ts": datetime.now().isoformat(),
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "confidence": confidence,
            "source": source,
            "tags": [],
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}/memory/semantic",
                json={"tier": "semantic", "type": "fact", "payload": payload}
            )
            response.raise_for_status()
            return response.json().get("id")
        
        except Exception as e:
            logger.error(f"AOMS write_fact failed: {e}")
            return None
    
    async def write_skill(
        self,
        skill_name: str,
        category: str,
        success_rate: float,
        when_to_use: str,
        avg_duration: str = None,
    ) -> Optional[str]:
        """Write skill to AOMS procedural memory."""
        from datetime import datetime
        
        payload = {
            "ts": datetime.now().isoformat(),
            "skill_name": skill_name,
            "category": category,
            "success_rate": success_rate,
            "when_to_use": when_to_use,
            "tags": [],
        }
        
        if avg_duration:
            payload["avg_duration"] = avg_duration
        
        try:
            response = await self.client.post(
                f"{self.base_url}/memory/procedural",
                json={"tier": "procedural", "type": "skill", "payload": payload}
            )
            response.raise_for_status()
            return response.json().get("id")
        
        except Exception as e:
            logger.error(f"AOMS write_skill failed: {e}")
            return None
    
    async def search_memory(
        self,
        query: str,
        tier: List[str] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """
        Search AOMS memory (episodic/semantic/procedural).
        
        Returns:
            {"query": str, "total": int, "results": [...]}
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/memory/search",
                json={"query": query, "tier": tier, "limit": limit}
            )
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"AOMS search failed: {e}")
            raise
    
    async def adjust_weight(
        self,
        entry_id: str,
        task_score: float,
    ) -> bool:
        """
        Adjust memory weight based on task outcome (reinforcement learning).
        
        Args:
            entry_id: Memory entry ID
            task_score: 0.0-1.0 (>0.7 = boost, <0.3 = decay)
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/memory/weight",
                json={"entry_id": entry_id, "task_score": task_score}
            )
            response.raise_for_status()
            return True
        
        except Exception as e:
            logger.error(f"AOMS weight adjustment failed: {e}")
            return False
    
    async def health(self) -> Dict[str, Any]:
        """Check AOMS health."""
        response = await self.client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

# Convenience functions for Daemon consciousness loop
async def log_consciousness_cycle(
    phase: str,
    outcome: str,
    duration_ms: int,
    model: str,
):
    """Log consciousness loop cycle to AOMS."""
    aoms = AOMemoryClient()
    await aoms.write_episode(
        episode_type="consciousness_cycle",
        title=f"Consciousness: {phase}",
        outcome=outcome,
        tags=["consciousness", phase.lower(), model],
        metadata={"duration_ms": duration_ms, "model": model},
    )
    await aoms.close()

async def log_goal_execution(
    goal_name: str,
    outcome: str,
    success: bool,
    duration_ms: int,
):
    """Log goal execution to AOMS."""
    aoms = AOMemoryClient()
    await aoms.write_episode(
        episode_type="achievement" if success else "failure",
        title=f"Goal: {goal_name}",
        outcome=outcome,
        tags=["goal", "execution", "success" if success else "failure"],
        metadata={"duration_ms": duration_ms},
    )
    await aoms.close()

if __name__ == "__main__":
    # Test Daemon integration
    async def test():
        aoms = AOMemoryClient()
        
        # Test health
        health = await aoms.health()
        print(f"AOMS health: {health['status']}")
        
        # Test write episode
        episode_id = await aoms.write_episode(
            episode_type="test",
            title="Daemon integration test",
            outcome="Success",
            tags=["test", "daemon"],
        )
        print(f"Written episode: {episode_id}")
        
        # Test smart query
        results = await aoms.smart_query(
            "memory architecture",
            token_budget=1000,
        )
        print(f"Smart query returned {len(results.get('results', []))} results, {results.get('total_tokens', 0)} tokens")
        
        await aoms.close()
    
    asyncio.run(test())
