# Engineering Knowledge Graph (EKG)

A prototype system that unifies engineering knowledge from infrastructure configuration files into a queryable graph with a natural language interface.

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- OpenAI API key
- Neo4j Aura account (free tier works)

### Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd ekg
   ```

2. **Configure environment variables**
   
   Create a `.env` file:
   ```env
   OPENAI_API_KEY=your_openai_api_key
   NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your_neo4j_password
   ```

3. **Start the system**
   ```bash
   docker-compose up --build
   ```

4. **Access the chat interface**
   
   Open [http://localhost:8000](http://localhost:8000) in your browser.

### Usage

Ask questions about your infrastructure:

- "Who owns the payment service?"
- "What does order-service depend on?"
- "What breaks if redis-main goes down?"
- "How does api-gateway connect to payments-db?"
- "List all services"

---

## 📐 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Engineering Knowledge Graph                      │
│                                                                          │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐              │
│  │   Config      │   │    Graph      │   │    Chat       │              │
│  │   Files       │   │    Layer      │   │    Interface  │              │
│  └───────┬───────┘   └───────┬───────┘   └───────┬───────┘              │
│          │                   │                   │                       │
│          ▼                   ▼                   ▼                       │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐              │
│  │  Connectors   │──▶│   Neo4j       │◀──│   OpenAI      │              │
│  │  • Docker     │   │   Storage     │   │   NLP         │              │
│  │  • Teams      │   │   + Query     │   │   Processing  │              │
│  │  • K8s        │   │   Engine      │   │               │              │
│  └───────────────┘   └───────────────┘   └───────────────┘              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Connectors** parse infrastructure configuration files (docker-compose.yml, teams.yaml, k8s-deployments.yaml)
2. **Graph Storage** persists nodes and edges to Neo4j
3. **Query Engine** provides graph traversal operations
4. **NLP Processor** translates natural language to graph queries using OpenAI
5. **Web UI** provides the chat interface

---

## 📁 Project Structure

```
ekg/
├── connectors/           # Config file parsers
│   ├── base.py          # Base connector interface
│   ├── docker_compose.py # Docker Compose parser
│   ├── teams.py         # Teams YAML parser
│   └── kubernetes.py    # K8s manifests parser
├── graph/                # Graph layer
│   ├── storage.py       # Neo4j persistence
│   └── query.py         # Query engine
├── chat/                 # Chat interface
│   ├── api.py           # FastAPI backend
│   ├── nlp.py           # OpenAI integration
│   └── static/          # Web UI files
├── data/                 # Configuration files
├── tests/                # Test suite
├── docker-compose.yml    # Container orchestration
├── Dockerfile           # Container image
├── main.py              # Application entry point
└── requirements.txt     # Python dependencies
```

---

## 🎯 Design Questions

### 1. Connector Pluggability

**How would someone add a new connector (e.g., Terraform)?**

Create a new file `connectors/terraform.py`:

```python
from connectors.base import BaseConnector, ConnectorResult, ConnectorRegistry

@ConnectorRegistry.register
class TerraformConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "terraform"
    
    def parse(self, file_path: Path) -> ConnectorResult:
        # Parse .tf files and extract resources
        # Return nodes and edges
        ...
```

The `@ConnectorRegistry.register` decorator automatically registers the connector. No changes to core code required.

### 2. Graph Updates

**If docker-compose.yml changes, how does the graph stay in sync?**

The system uses **upsert semantics** with `MERGE` in Neo4j:
- On startup, connectors re-parse all files
- Existing nodes are updated with new properties
- New nodes are created
- The `/ingest` API endpoint can trigger manual refresh

For production, I would add file watching with `watchdog` and incremental updates.

### 3. Cycle Handling

**How do you prevent infinite loops in upstream() and downstream() queries?**

Two mechanisms:
1. **Max depth limit** (default 10) in Cypher path patterns: `[*1..10]`
2. **DISTINCT** keyword ensures each node appears only once in results
3. Cypher's built-in path semantics don't revisit nodes

### 4. Query Mapping

**How do you translate natural language to graph queries?**

Using OpenAI's **function calling**:
1. Define available functions as JSON schema (get_node, list_nodes, blast_radius, etc.)
2. Send user query + function definitions to GPT-4
3. Model returns structured function calls with arguments
4. Execute corresponding graph queries
5. Feed results back to model for natural language response

### 5. Failure Handling

**When the chat can't answer a question, what happens?**

- If no function calls are returned, respond with "I couldn't understand that query"
- If function returns no results, model explains that the entity wasn't found
- The system prompt instructs the model to never make up information
- Out-of-scope questions are politely declined

### 6. Scale Considerations

**What would break first if this had 10K nodes?**

**First to break:**
- Query engine traversals without depth limits (memory explosion)
- Full graph visualization (browser performance)
- Connector parsing (if config files grow huge)

**Solutions:**
- Add pagination to list queries
- Use streaming for large result sets
- Add Cypher indexes on frequently queried properties
- Implement query result caching
- Use graph sampling for visualization

### 7. Why Neo4j?

Neo4j was chosen because:
- **Native graph storage** optimized for traversals
- **Cypher query language** is intuitive for relationship queries
- **Aura free tier** provides hosted solution
- **Excellent Python driver** support
- Industry standard for knowledge graphs

---

## ⚖️ Tradeoffs & Limitations

### Intentional Simplifications

- **No auth** - Real system would need API authentication
- **Single-file ingestion** - Would benefit from background workers
- **No caching** - Repeated queries hit the database each time
- **Limited error recovery** - Minimal retry logic

### Weakest Parts

1. **Entity resolution** - The NLP sometimes misidentifies service names
2. **K8s connector** - Only supports Deployment/Service resources
3. **No incremental updates** - Full graph reload on changes

### With 20 More Hours

1. Add graph visualization using vis.js
2. Implement file watching for live updates
3. Add comprehensive test coverage
4. Build Terraform and AWS connectors
5. Add authentication and multi-user support
6. Implement query result caching
7. Deploy to Railway/Fly.io

---

## 🤖 AI Usage

### Where AI Helped Most

- **Boilerplate generation** - FastAPI endpoints, Neo4j queries
- **CSS styling** - The dark theme and animations
- **OpenAI function schemas** - Defining the tool interfaces
- **Error handling patterns** - Edge cases I might have missed

### Where I Corrected AI

- **Neo4j Cypher syntax** - Had to fix relationship patterns
- **Async/await usage** - Corrected session management
- **Import paths** - Fixed relative import issues
- **Edge case handling** - Added null checks AI missed

### Learnings

AI is excellent at scaffolding and pattern implementation but needs human oversight for:
- Domain-specific correctness
- Integration between components
- Security considerations
- Performance optimization

---

## 🧪 Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/ -v
```

---

## 📹 Demo Video

[Link to demo video - 3-5 minutes showing:]
- System startup via docker-compose
- Connectors parsing config files
- 5+ natural language queries
- Blast radius query demonstration
- Architecture walkthrough

---

## 📝 License

MIT License - See LICENSE file for details.
