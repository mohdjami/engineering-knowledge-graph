"""
FastAPI Backend for the Engineering Knowledge Graph Chat Interface.

This module provides REST endpoints for:
- Natural language chat queries
- Graph data access
- System health checks
"""

import os
from pathlib import Path
from typing import Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph.storage import GraphStorage
from graph.query import QueryEngine
from chat.nlp import NLPProcessor


# Global instances
storage: Optional[GraphStorage] = None
query_engine: Optional[QueryEngine] = None
nlp_processor: Optional[NLPProcessor] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global storage, query_engine, nlp_processor
    
    # Initialize on startup
    print("🚀 Starting Engineering Knowledge Graph...")
    
    try:
        # Initialize graph storage
        storage = GraphStorage()
        storage.connect()
        print("✅ Connected to Neo4j")
        
        # Initialize query engine
        query_engine = QueryEngine(storage)
        print("✅ Query engine ready")
        
        # Initialize NLP processor
        nlp_processor = NLPProcessor()
        print("✅ NLP processor ready")
        
        # Run connectors to populate graph
        await run_connectors()
        
    except Exception as e:
        print(f"❌ Startup error: {e}")
        raise
    
    yield
    
    # Cleanup on shutdown
    if storage:
        storage.close()
        print("👋 Disconnected from Neo4j")


async def run_connectors():
    """Run all connectors to populate the graph."""
    from connectors import DockerComposeConnector, TeamsConnector, KubernetesConnector
    
    data_dir = Path(__file__).parent.parent / "data"
    
    # Clear existing data for fresh load
    storage.clear_graph()
    print("🗑️  Cleared existing graph data")
    
    # Run Docker Compose connector
    docker_compose_file = data_dir / "docker-compose.yml"
    if docker_compose_file.exists():
        connector = DockerComposeConnector()
        result = connector.parse(docker_compose_file)
        
        for node in result.nodes:
            storage.upsert_node(node)
        for edge in result.edges:
            storage.upsert_edge(edge)
        
        print(f"✅ Docker Compose: {len(result.nodes)} nodes, {len(result.edges)} edges")
    
    # Run Teams connector
    teams_file = data_dir / "teams.yaml"
    if teams_file.exists():
        connector = TeamsConnector()
        result = connector.parse(teams_file)
        
        for node in result.nodes:
            storage.upsert_node(node)
        for edge in result.edges:
            storage.upsert_edge(edge)
        
        print(f"✅ Teams: {len(result.nodes)} nodes, {len(result.edges)} edges")
    
    # Run Kubernetes connector (bonus)
    k8s_file = data_dir / "k8s-deployments.yaml"
    if k8s_file.exists():
        connector = KubernetesConnector()
        result = connector.parse(k8s_file)
        
        for node in result.nodes:
            storage.upsert_node(node)
        for edge in result.edges:
            storage.upsert_edge(edge)
        
        print(f"✅ Kubernetes: {len(result.nodes)} nodes, {len(result.edges)} edges")
    
    # Create indexes
    storage.create_indexes()
    print(f"📊 Graph ready: {storage.get_node_count()} nodes, {storage.get_edge_count()} edges")


# Create FastAPI app
app = FastAPI(
    title="Engineering Knowledge Graph",
    description="Natural language interface for infrastructure knowledge",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatRequest(BaseModel):
    message: str
    clear_context: bool = False


class ChatResponse(BaseModel):
    response: str
    function_calls: list[dict] = []
    nodes_mentioned: list[str] = []


class NodeResponse(BaseModel):
    id: str
    type: str
    name: str
    properties: dict


# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the chat interface."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("""
    <html>
        <head><title>EKG Chat</title></head>
        <body>
            <h1>Engineering Knowledge Graph</h1>
            <p>Chat interface not found. Use the API endpoints directly.</p>
        </body>
    </html>
    """)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "graph_connected": storage is not None,
        "node_count": storage.get_node_count() if storage else 0,
        "edge_count": storage.get_edge_count() if storage else 0
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process a natural language chat message."""
    if not nlp_processor or not query_engine:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    if request.clear_context:
        nlp_processor.clear_context()
    
    # Get function calls from NLP
    _, function_calls = nlp_processor.process_query(request.message)
    
    # Execute function calls
    function_results = []
    nodes_mentioned = []
    
    for call in function_calls:
        result = execute_function(call["function_name"], call["arguments"])
        function_results.append({
            "id": call["id"],
            "function_name": call["function_name"],
            "result": result
        })
        
        # Track mentioned nodes
        if isinstance(result, dict) and result.get("id"):
            nodes_mentioned.append(result["id"])
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and item.get("id"):
                    nodes_mentioned.append(item["id"])
    
    # Generate response
    if function_results:
        response_text = nlp_processor.generate_response(request.message, function_results)
    else:
        response_text = "I couldn't understand that query. Try asking about services, databases, teams, or their relationships."
    
    return ChatResponse(
        response=response_text,
        function_calls=function_results,
        nodes_mentioned=nodes_mentioned
    )


def execute_function(function_name: str, arguments: dict) -> Any:
    """Execute a graph query function."""
    if function_name == "get_node":
        return query_engine.get_node(arguments["node_id"])
    
    elif function_name == "list_nodes":
        return query_engine.get_nodes(arguments["node_type"])
    
    elif function_name == "get_downstream":
        return query_engine.downstream(arguments["node_id"])
    
    elif function_name == "get_upstream":
        return query_engine.upstream(arguments["node_id"])
    
    elif function_name == "blast_radius":
        return query_engine.blast_radius(arguments["node_id"])
    
    elif function_name == "find_path":
        return query_engine.path(arguments["from_node"], arguments["to_node"])
    
    elif function_name == "get_owner":
        return query_engine.get_owner(arguments["node_id"])
    
    elif function_name == "get_team_assets":
        team_id = f"team:{arguments['team_name']}"
        return query_engine.get_team_assets(team_id)
    
    elif function_name == "get_oncall":
        return query_engine.get_oncall(arguments["node_id"])
    
    elif function_name == "search_nodes":
        return query_engine.search_nodes(arguments["query"])
    
    else:
        return {"error": f"Unknown function: {function_name}"}


@app.get("/graph/nodes")
async def get_all_nodes():
    """Get all nodes in the graph."""
    if not storage:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return storage.get_all_nodes()


@app.get("/graph/nodes/{node_type}")
async def get_nodes_by_type(node_type: str):
    """Get nodes by type."""
    if not query_engine:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return query_engine.get_nodes(node_type)


@app.get("/graph/node/{node_id:path}")
async def get_node(node_id: str):
    """Get a specific node by ID."""
    if not query_engine:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    node = query_engine.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    
    return node


@app.get("/graph/edges")
async def get_all_edges():
    """Get all edges in the graph."""
    if not storage:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return storage.get_all_edges()


@app.post("/ingest")
async def trigger_ingest():
    """Re-run connectors to refresh graph data."""
    if not storage:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    await run_connectors()
    
    return {
        "status": "success",
        "node_count": storage.get_node_count(),
        "edge_count": storage.get_edge_count()
    }


@app.get("/graph/stats")
async def get_stats():
    """Get graph statistics."""
    if not query_engine:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return query_engine.get_graph_stats()
