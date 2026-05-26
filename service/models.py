"""Pydantic models for the AOMS API."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemoryWrite(BaseModel):
    """Request body for writing a memory entry."""
    type: str = Field(..., description="Entry type within the tier (experience, decision, fact, skill, etc.)")
    payload: Dict[str, Any] = Field(..., description="Entry data matching the tier's JSONL schema")
    tags: Optional[List[str]] = Field(default_factory=list)
    weight: Optional[float] = Field(default=None, ge=0.1, le=5.0, description="Initial weight override")


class MemorySearch(BaseModel):
    """Request body for searching memory."""
    query: str
    tier: Optional[List[str]] = Field(default=None, description="Tiers to search (None = all)")
    limit: int = Field(default=10, ge=1, le=100)
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_weight: Optional[float] = Field(default=None, ge=0.0)


class WeightUpdate(BaseModel):
    """Request body for adjusting a memory's weight via reinforcement."""
    entry_id: str
    tier: str
    task_score: float = Field(..., ge=0.0, le=1.0, description="Task outcome score (0=failure, 1=perfect)")


class SearchResult(BaseModel):
    """A single search result."""
    tier: str
    type: str
    entry: Dict[str, Any]
    score: float
    line_number: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    uptime_seconds: float
    memory_root: str
    tiers: Dict[str, int]


# --- Cortex L0/L1/L2 models ---

class CortexIngest(BaseModel):
    """Request body for ingesting a document into the cortex tiered system."""
    content: str = Field(..., description="Full document content (L2)")
    title: str
    hierarchy_path: str = Field(..., description="e.g. /research/memory_architecture")
    doc_type: str = Field(default="reference", description="strategy|backtest|research|episode|skill|pattern|session_learning|reference")
    tags: Optional[List[str]] = Field(default_factory=list)


class CortexQuery(BaseModel):
    """Request body for a smart tiered query."""
    query: str
    token_budget: int = Field(default=4000, ge=100, le=50000)
    top_k: int = Field(default=10, ge=1, le=50)
    directory: Optional[str] = Field(default=None, description="Limit to hierarchy prefix")
    agent_id: Optional[str] = None


# --- Upgrade v1.2 models ---

class SemanticSearch(BaseModel):
    """Request body for semantic (vector) search."""
    query: str
    tier: Optional[List[str]] = Field(default=None, description="Tiers to search (None = all)")
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)
    hybrid: bool = Field(default=True, description="Combine with keyword search")


class RecallRequest(BaseModel):
    """Request body for agent recall endpoint."""
    task: str = Field(..., description="Task description or query for context")
    token_budget: int = Field(default=2000, ge=100, le=10000)
    tiers: Optional[List[str]] = Field(default=None, description="Tiers to include")
    format: str = Field(default="markdown", description="Output format: markdown|json|plain")


class RecallResponse(BaseModel):
    """Response from agent recall endpoint."""
    context: str
    tokens: int
    sources: List[Dict[str, Any]]
    tiers_searched: List[str]


class DecayRequest(BaseModel):
    """Request body for weight decay operation."""
    tier: Optional[str] = Field(default=None, description="Specific tier (None = all)")
    min_age_days: int = Field(default=1, ge=0, description="Only decay entries older than this")
    decay_rate: float = Field(default=0.995, ge=0.9, le=1.0)
    dry_run: bool = Field(default=False, description="Preview without applying")


class ConsolidateRequest(BaseModel):
    """Request body for memory consolidation."""
    tier: str = Field(default="episodic")
    min_age_days: int = Field(default=7, ge=1)
    similarity_threshold: float = Field(default=0.85, ge=0.5, le=1.0)
    max_entries: int = Field(default=100, ge=1, le=1000)
    dry_run: bool = Field(default=False)


class EntityExtractRequest(BaseModel):
    """Request body for entity extraction."""
    text: str
    source_id: Optional[str] = None
    store: bool = Field(default=True, description="Store extracted entities")


class StatsResponse(BaseModel):
    """Response for /stats endpoint."""
    total_entries: int
    by_tier: Dict[str, int]
    by_type: Dict[str, int]
    vector_indexed: Dict[str, int]
    weight_distribution: Dict[str, int]
    recent_24h: int
    oldest_entry: Optional[str]
    newest_entry: Optional[str]
