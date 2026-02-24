# Weighted Memory Proof-of-Concept - Cursor Build Instructions

**Model:** Use Opus 4.6 or Codex Premium  
**Location:** `~/projects/weighted-memory-poc/`

---

## Context (Read These Files First)

You have access to 3 comprehensive research documents in `~/.openclaw/workspace/docs/`:

1. **`ai-agents-frameworks-analysis.md`** (38KB)
   - AutoGen, CrewAI patterns
   - 6 implementable patterns with code
   - D2DT trading integration strategy

2. **`memelord-analysis.md`** (14KB)
   - Memelord's weighted memory system (production, by Turso)
   - Reinforcement learning algorithm
   - Comparison with Daemon Cortex

3. **`memory-architecture-research-synthesis.md`** (24KB)
   - 5 generations of AI memory systems
   - Gen 5 architecture (hierarchical + weighted)
   - D2DT trading opportunity
   - 12-week implementation roadmap

**Read these first** to understand the full context.

---

## Goal

Build a **standalone proof-of-concept** that validates weighted memory retrieval with reinforcement learning.

**Formula:**
```
score = similarity × weight × recency
```

Where:
- **Similarity:** Cosine distance from vector embeddings
- **Weight:** Learned from task outcomes (1.1x on success, 0.9x on failure)
- **Recency:** Time decay (0.995^days since created)

---

## Critical Constraints

### ❌ DO NOT Touch These Existing Systems:
- `~/.openclaw/workspace/memory/` (OpenClaw daily logs)
- `~/.openclaw/workspace/MEMORY.md` (OpenClaw long-term memory)
- `/home/dhawal/daemon/memory_data/` (Daemon Cortex)

### ✅ Build Standalone:
- Location: `~/projects/weighted-memory-poc/`
- Self-contained Python library
- Local SQLite + embeddings (no external services)
- Can be pip-installed later

---

## Deliverables

### 1. Core Library
```
weighted_memory/
├── __init__.py
├── memory.py          # Main WeightedMemory class
├── storage.py         # SQLite + vector storage
├── embeddings.py      # Local embeddings (sentence-transformers)
├── retrieval.py       # Weighted scoring + ranking
├── reinforcement.py   # Weight adjustment from outcomes
└── utils.py           # Helpers
```

### 2. Test Suite
```
tests/
├── test_storage.py
├── test_retrieval.py
├── test_reinforcement.py
└── test_integration.py
```

### 3. Examples
```
examples/
├── basic_usage.py              # Store + retrieve
├── reinforcement_demo.py       # Weight adjustment
├── comparison_flat_vs_weighted.py  # Prove weighted is better
└── trading_simulation.py       # Simulated D2DT use case
```

### 4. Documentation
```
README.md              # Quick start
ARCHITECTURE.md        # Design decisions
API.md                 # Full API reference
BENCHMARKS.md          # Performance comparisons
```

---

## Architecture Requirements

### Memory Storage (SQLite Schema)

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,  -- Vector stored as bytes
    category TEXT NOT NULL CHECK(category IN ('user_teaching', 'user_correction', 'self_correction', 'achievement', 'failure', 'observation')),
    weight REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,
    times_retrieved INTEGER DEFAULT 0,
    times_helpful INTEGER DEFAULT 0
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    tokens_used INTEGER,
    errors INTEGER,
    user_corrections INTEGER,
    completed BOOLEAN,
    score REAL,  -- Calculated 0-1
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE task_memories (
    task_id TEXT REFERENCES tasks(id),
    memory_id TEXT REFERENCES memories(id),
    retrieved_score REAL,  -- Score at retrieval time
    PRIMARY KEY (task_id, memory_id)
);
```

### Embeddings

Use **sentence-transformers** for local embeddings (no API calls):
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')  # 22MB model, fast
embedding = model.encode(text)  # Returns numpy array
```

### Retrieval Algorithm

```python
def retrieve_with_weight(query: str, limit: int = 10) -> List[Memory]:
    """
    Retrieve memories using weighted scoring.
    
    score = cosine_similarity(query, memory) × weight × recency_factor
    
    Where:
    - cosine_similarity: 1.0 - cosine_distance (ChromaDB style)
    - weight: Current memory weight (adjusted by RL)
    - recency_factor: 0.995 ^ days_since_created
    """
    query_embedding = embed(query)
    
    candidates = []
    for memory in all_memories:
        # Semantic similarity
        similarity = 1.0 - cosine_distance(query_embedding, memory.embedding)
        
        # Weight from reinforcement learning
        weight = memory.weight
        
        # Recency decay
        days_old = (now() - memory.created_at).days
        recency = 0.995 ** days_old
        
        # Final score
        score = similarity * weight * recency
        candidates.append((memory, score))
    
    # Sort by score descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [m for m, s in candidates[:limit]]
```

### Reinforcement Learning

```python
def adjust_weights_from_task_outcome(task: Task):
    """
    Adjust memory weights based on task success.
    
    Task Score (0-1):
    - 0.5: Completion (success=1.0, fail=0.2)
    - 0.2: Token efficiency (fewer tokens = higher)
    - 0.15: Error rate (fewer errors = higher)
    - 0.15: User corrections (fewer corrections = higher)
    """
    # Calculate task quality score
    task_score = calculate_task_score(task)
    
    # Get memories used during task
    used_memories = get_task_memories(task.id)
       │   ├── tiers/                                                                                                                                                                                                                                                                         
   │   │   ├── working.py      # Working memory tier                                                                                                                                                                                                                                      
   │   │   ├── episodic.py     # Episodic memory tier                                                                                                                                                                                                                                     
   │   │   ├── semantic.py     # Semantic memory tier                                                                                                                                                                                                                                     
   │   │   └── procedural.py   # Procedural memory tier                                                                                                                                                                                                                                   
   │   ├── loaders/                                                                                                                                                                                                                                                                       
   │   │   ├── l0.py           # Abstract loader                                                                                                                                                                                                                                          
   │   │   ├── l1.py           # Overview loader                                                                                                                                                                                                                                          
   │   │   └── l2.py           # Full content loader                                                                                                                                                                                                                                      
   │   ├── storage/                                                                                                                                                                                                                                                                       
   │   │   ├── base.py         # Storage interface                                                                                                                                                                                                                                        
   │   │   └── json_store.py   # JSON file storage                                                                                                                                                                                                                                        
   │   ├── embeddings/                                                                                                                                                                                                                                                                    
   │   │   └── ollama.py       # Ollama embedding client                                                                                                                                                                                                                                  
   │   └── api.py              # FastAPI routes                                                                                                                                                                                                                                           
   ├── data/                   # Storage directory                                                                                                                                                                                                                                        
   ├── tests/                                                                                                                                                                                                                                                                             
   ├── requirements.txt                                                                                                                                                                                                                                                                   
   ├── README.md                                                                                                                                                                                                                                                                          
   └── config.yaml                                                                                                                                                                                                                                                                        
                                                                                                                                                                                                                                                                                          
 ```                                                                                                                                                                                                                                                                                      
                                                                                                                                                                                                                                                                                          
 Core Functionality (Phase 1)                                                                                                                                                                                                                                                             
                                                                                                                                                                                                                                                                                          
 Memory Operations:                                                                                                                                                                                                                                                                       
 - store(tier, content, metadata) → Store with auto L0/L1/L2 generation                                                                                                                                                                                                                   
 - query(query_text, tier=None, limit=10) → Semantic search                                                                                                                                                                                                                               
 - retrieve(id, load_level='L1') → Get by ID with tiering                                                                                                                                                                                                                                 
 - update(id, content) → Update existing entry                                                                                                                                                                                                                                            
 - delete(id) → Remove entry                                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                          
 API Endpoints:                                                                                                                                                                                                                                                                           
 - POST /memory/store - Store new memory                                                                                                                                                                                                                                                  
 - GET /memory/query - Semantic search                                                                                                                                                                                                                                                    
 - GET /memory/{id} - Retrieve by ID                                                                                                                                                                                                                                                      
 - PUT /memory/{id} - Update                                                                                                                                                                                                                                                              
 - DELETE /memory/{id} - Delete                                                                                                                                                                                                                                                           
                                                                                                                                                                                                                                                                                          
 Key Decisions                                                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                                          
 1. Start with JSON - One file per tier, easy to debug                                                                                                                                                                                                                                    
 2. Local embeddings - Ollama nomic-embed-text (no API costs)                                                                                                                                                                                                                             
 3. Simple vector search - Cosine similarity, optimize later                                                                                                                                                                                                                              
 4. FastAPI - Clean, async-ready, good docs                                                                                                                                                                                                                                               
 5. No ChromaDB yet - Avoid segfault issues, add later if needed                                                                                                                                                                                                                          
                                                                                                                                                                                                                                                                                          
 First Tasks                                                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                          
 1. Set up project structure                                                                                                                                                                                                                                                              
 2. Implement JSON storage backend                                                                                                                                                                                                                                                        
 3. Build Ollama embedding client                                                                                                                                                                                                                                                         
 4. Create basic Working memory tier                                                                                                                                                                                                                                                      
 5. Add L0/L1/L2 loader logic                                                                                                                                                                                                                                                             
 6. Test with simple store/retrieve cycles                                                                                                                                                                                                                                                
                                                                                                                                                                                                                                                                                          
 Success Criteria                                                                                                                                                                                                                                                                         
                                                                                                                                                                                                                                                                                          
 - Store a memory and retrieve it by ID                                                                                                                                                                                                                                                   
 - Query memories semantically                                                                                                                                                                                                                                                            
 - L0 loads fast (<50ms), L2 on-demand only                                                                                                                                                                                                                                               
 - Clean API with FastAPI                                                                                                                                                                                                                                                                 
 - No external dependencies that cost money                                                                                                                                                                                                                                               
                                                                                                                                                                                                                                                                                          
 ────────────────────────────────────────────────────────────────────────────────                                                                                                                                                                                                         
                                                                                                                                                                                                                                                                                          
 Start with the structure, then Working memory + JSON storage. Keep it simple and functional.   

### Category-Based Initial Weights

```python
INITIAL_WEIGHTS = {
    "user_teaching": 2.0,      # User explicitly taught us
    "user_correction": 1.8,    # User corrected our mistake
    "self_correction": 1.5,    # We caught our own mistake
    "achievement": 1.3,        # Successful task completion
    "failure": 1.0,            # Failed task (learn from it)
    "observation": 0.8         # Passive observation
}
```

---

## Implementation Steps

### Phase 1: Core Storage (1-2 hours)
1. SQLite schema setup
2. Memory CRUD operations
3. Embedding generation + storage
4. Basic retrieval (flat, no weighting yet)

### Phase 2: Weighted Retrieval (1-2 hours)
5. Implement weighted scoring formula
6. Test with synthetic memories
7. Compare flat vs weighted results

### Phase 3: Reinforcement Learning (2-3 hours)
8. Task outcome tracking
9. Weight adjustment algorithm
10. Test with simulated tasks (success/failure patterns)

### Phase 4: Testing & Validation (2-3 hours)
11. Unit tests for all components
12. Integration test: store → retrieve → adjust → re-retrieve
13. Benchmark: flat vs weighted (token usage, retrieval quality)

### Phase 5: Examples & Documentation (1-2 hours)
14. Basic usage example
15. Comparison demo (prove weighted is better)
16. Trading simulation (D2DT use case)
17. Documentation (README, API, benchmarks)

**Total:** 8-12 hours of focused work

---

## Validation Criteria

### Must Pass:
1. ✅ **Weighted retrieval works**
   - Test: Boost one memory's weight, verify it ranks higher
   - Test: Decay one memory, verify it ranks lower

2. ✅ **Reinforcement learning works**
   - Test: Successful task → memories get boosted (1.1x)
   - Test: Failed task → memories get decayed (0.9x)

3. ✅ **Recency decay works**
   - Test: Old memory (30 days) has lower score than recent (1 day)

4. ✅ **Better than flat retrieval**
   - Benchmark: Weighted vs flat on 100 synthetic tasks
   - Measure: Retrieval quality (top-k accuracy)
   - Expected: Weighted outperforms flat by 20-40%

---

## Example Usage (Target API)

```python
from weighted_memory import WeightedMemory

# Initialize
memory = WeightedMemory(db_path="./memory.db")

# Store memories
memory.store(
    content="x_search API was deprecated on Feb 23, 2026",
    category="user_correction"
)

memory.store(
    content="Twitter rate limits: 10 tweets/hour",
    category="observation"
)

# Retrieve with weighting
results = memory.retrieve(
    query="How to use Twitter API?",
    limit=5
)

for mem, score in results:
    print(f"{score:.3f}: {mem.content[:50]}...")

# Start task
task_id = memory.start_task("Fix Twitter auth")

# ... do work ...

# End task with outcome
memory.end_task(
    task_id=task_id,
    tokens_used=12000,
    errors=2,
    user_corrections=0,
    completed=True
)

# Weights automatically adjusted for memories used in task
```

---

## Testing Strategy

### Unit Tests
- `test_storage.py`: CRUD operations
- `test_embeddings.py`: Vector generation + similarity
- `test_retrieval.py`: Scoring formula + ranking
- `test_reinforcement.py`: Weight adjustments

### Integration Tests
```python
def test_full_cycle():
    """Test complete workflow."""
    mem = WeightedMemory()
    
    # Store
    mem.store("Python uses indentation", category="observation")
    mem.store("Always use type hints", category="user_teaching")
    
    # Initial retrieval
    results1 = mem.retrieve("coding style")
    assert "type hints" in results1[0].content  # Higher initial weight
    
    # Task with "type hints" memory
    task_id = mem.start_task("Write Python code")
    mem.end_task(task_id, tokens=5000, errors=0, completed=True)
    
    # Retrieve again - "type hints" should rank even higher
    results2 = mem.retrieve("coding style")
    assert results2[0].score > results1[0].score  # Weight boosted
```

### Benchmark Tests
```python
def benchmark_weighted_vs_flat():
    """Prove weighted retrieval is better."""
    # Generate 100 synthetic memories
    memories = generate_synthetic_dataset()
    
    # Simulate 50 tasks with known outcomes
    tasks = generate_synthetic_tasks()
    
    # Test flat retrieval
    flat_results = run_flat_retrieval(memories, tasks)
    
    # Test weighted retrieval
    weighted_results = run_weighted_retrieval(memories, tasks)
    
    # Compare
    print(f"Flat accuracy: {flat_results.accuracy}")
    print(f"Weighted accuracy: {weighted_results.accuracy}")
    assert weighted_results.accuracy > flat_results.accuracy * 1.2
```

---

## Success Metrics

After implementation, you should be able to demonstrate:

1. **Memory stores with categories** ✓
2. **Retrieval respects weights** ✓
3. **Successful tasks boost memory weights** ✓
4. **Failed tasks decay memory weights** ✓
5. **Old memories fade naturally (recency)** ✓
6. **Weighted > Flat by 20-40%** ✓

---

## Dependencies

```python
# requirements.txt
sentence-transformers>=2.2.0  # Local embeddings
numpy>=1.24.0
sqlite3  # Built-in
pytest>=7.0.0
```

---

## Final Deliverable Structure

```
~/projects/weighted-memory-poc/
├── weighted_memory/          # Core library
│   ├── __init__.py
│   ├── memory.py
│   ├── storage.py
│   ├── embeddings.py
│   ├── retrieval.py
│   ├── reinforcement.py
│   └── utils.py
├── tests/
│   ├── test_storage.py
│   ├── test_retrieval.py
│   ├── test_reinforcement.py
│   └── test_integration.py
├── examples/
│   ├── basic_usage.py
│   ├── reinforcement_demo.py
│   ├── comparison_flat_vs_weighted.py
│   └── trading_simulation.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   └── BENCHMARKS.md
├── README.md
├── requirements.txt
├── setup.py                  # pip install support
└── .gitignore
```

---

## Start Building

Open Cursor in `~/projects/weighted-memory-poc/` and begin with Phase 1: Core Storage.

Good luck! 🧠
