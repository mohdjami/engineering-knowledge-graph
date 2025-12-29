"""
Query Engine for the Engineering Knowledge Graph.

This module provides graph traversal and query functions for answering
questions about infrastructure dependencies, ownership, and blast radius.
"""

from typing import Any, Optional
from graph.storage import GraphStorage


class QueryEngine:
    """
    Query engine for traversing and querying the knowledge graph.
    
    Provides:
    - Single node retrieval
    - Filtered node listing
    - Transitive dependency traversal (upstream/downstream)
    - Blast radius analysis
    - Shortest path finding
    - Ownership queries
    """
    
    def __init__(self, storage: GraphStorage):
        """
        Initialize the query engine.
        
        Args:
            storage: GraphStorage instance for database access
        """
        self.storage = storage
    
    def get_node(self, node_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve a single node by ID.
        
        Args:
            node_id: Unique node identifier (e.g., "service:order-service")
            
        Returns:
            Node data as dictionary, or None if not found
        """
        return self.storage.get_node(node_id)
    
    def get_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """
        List nodes by type with optional filters.
        
        Args:
            node_type: Filter by node type (service, database, cache, team)
            filters: Additional property filters
            
        Returns:
            List of matching nodes
        """
        return self.storage.get_nodes(node_type, filters)
    
    def downstream(
        self,
        node_id: str,
        edge_types: Optional[list[str]] = None,
        max_depth: int = 10
    ) -> list[dict[str, Any]]:
        """
        Find all transitive dependencies of a node.
        
        "What does order-service depend on?"
        
        Args:
            node_id: Starting node ID
            edge_types: Filter by relationship types (e.g., ["calls", "uses"])
            max_depth: Maximum traversal depth to prevent infinite loops
            
        Returns:
            List of downstream nodes (dependencies)
        """
        # Build relationship filter
        if edge_types:
            rel_filter = "|".join([t.upper().replace("-", "_") for t in edge_types])
            rel_pattern = f"[r:{rel_filter}*1..{max_depth}]"
        else:
            rel_pattern = f"[r*1..{max_depth}]"
        
        query = f"""
        MATCH (start {{id: $node_id}})
        MATCH (start)-{rel_pattern}->(downstream)
        RETURN DISTINCT downstream
        """
        
        with self.storage.session() as session:
            result = session.run(query, node_id=node_id)
            return [dict(record["downstream"]) for record in result]
    
    def upstream(
        self,
        node_id: str,
        edge_types: Optional[list[str]] = None,
        max_depth: int = 10
    ) -> list[dict[str, Any]]:
        """
        Find all transitive dependents of a node.
        
        "What breaks if orders-db goes down?"
        
        Args:
            node_id: Starting node ID
            edge_types: Filter by relationship types
            max_depth: Maximum traversal depth to prevent infinite loops
            
        Returns:
            List of upstream nodes (dependents)
        """
        # Build relationship filter
        if edge_types:
            rel_filter = "|".join([t.upper().replace("-", "_") for t in edge_types])
            rel_pattern = f"[r:{rel_filter}*1..{max_depth}]"
        else:
            rel_pattern = f"[r*1..{max_depth}]"
        
        query = f"""
        MATCH (target {{id: $node_id}})
        MATCH (upstream)-{rel_pattern}->(target)
        RETURN DISTINCT upstream
        """
        
        with self.storage.session() as session:
            result = session.run(query, node_id=node_id)
            return [dict(record["upstream"]) for record in result]
    
    def blast_radius(self, node_id: str) -> dict[str, Any]:
        """
        Calculate the full impact analysis for a node.
        
        Combines upstream (what depends on this), downstream (what this depends on),
        and affected teams.
        
        "What's the blast radius if redis-main goes down?"
        
        Args:
            node_id: The node to analyze
            
        Returns:
            Dictionary with upstream, downstream, and affected_teams
        """
        # Get the node itself
        node = self.get_node(node_id)
        
        # Get upstream (what would break)
        upstream = self.upstream(node_id)
        
        # Get downstream (dependencies)
        downstream = self.downstream(node_id)
        
        # Get affected teams - teams that own any upstream service
        affected_teams = set()
        affected_node_ids = [node_id] + [n.get("id", "") for n in upstream]
        
        for affected_id in affected_node_ids:
            owner = self.get_owner(affected_id)
            if owner:
                affected_teams.add(owner.get("name", ""))
        
        # Also check team property on nodes
        for n in upstream + [node] if node else upstream:
            if n and n.get("team"):
                affected_teams.add(n["team"])
        
        return {
            "node": node,
            "upstream": upstream,
            "downstream": downstream,
            "affected_teams": list(affected_teams),
            "total_impact": len(upstream) + len(downstream)
        }
    
    def path(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 10
    ) -> list[dict[str, Any]]:
        """
        Find the shortest path between two nodes.
        
        "How does api-gateway connect to payments-db?"
        
        Args:
            from_id: Source node ID
            to_id: Target node ID
            max_depth: Maximum path length
            
        Returns:
            List of nodes in the path (including endpoints)
        """
        query = f"""
        MATCH (start {{id: $from_id}}), (end {{id: $to_id}})
        MATCH path = shortestPath((start)-[*1..{max_depth}]->(end))
        RETURN nodes(path) as path_nodes, relationships(path) as path_rels
        """
        
        with self.storage.session() as session:
            result = session.run(query, from_id=from_id, to_id=to_id)
            record = result.single()
            
            if record:
                path_nodes = [dict(n) for n in record["path_nodes"]]
                path_rels = []
                for r in record["path_rels"]:
                    rel_data = dict(r)
                    rel_data["type"] = r.type
                    path_rels.append(rel_data)
                
                return {
                    "nodes": path_nodes,
                    "relationships": path_rels,
                    "length": len(path_nodes) - 1
                }
            return {"nodes": [], "relationships": [], "length": 0}
    
    def get_owner(self, node_id: str) -> Optional[dict[str, Any]]:
        """
        Find the team that owns a node.
        
        "Who owns payment-service?"
        
        Args:
            node_id: The node to find the owner of
            
        Returns:
            Team node data, or None if no owner found
        """
        query = """
        MATCH (team:Team)-[:OWNS]->(target {id: $node_id})
        RETURN team
        """
        
        with self.storage.session() as session:
            result = session.run(query, node_id=node_id)
            record = result.single()
            
            if record:
                return dict(record["team"])
            
            # Fallback: check the 'team' property on the node itself
            node = self.get_node(node_id)
            if node and node.get("team"):
                team_name = node["team"]
                team = self.get_node(f"team:{team_name}")
                return team
            
            return None
    
    def get_team_assets(self, team_id: str) -> list[dict[str, Any]]:
        """
        Get all assets owned by a team.
        
        "What does the orders team own?"
        
        Args:
            team_id: The team node ID
            
        Returns:
            List of owned nodes
        """
        query = """
        MATCH (team {id: $team_id})-[:OWNS]->(asset)
        RETURN asset
        """
        
        with self.storage.session() as session:
            result = session.run(query, team_id=team_id)
            return [dict(record["asset"]) for record in result]
    
    def get_services_using(self, node_id: str) -> list[dict[str, Any]]:
        """
        Get all services that use a specific resource (database, cache).
        
        "What services use redis?"
        
        Args:
            node_id: The resource node ID
            
        Returns:
            List of services using the resource
        """
        query = """
        MATCH (service)-[:USES|DEPENDS_ON|CALLS]->(target {id: $node_id})
        RETURN DISTINCT service
        """
        
        with self.storage.session() as session:
            result = session.run(query, node_id=node_id)
            return [dict(record["service"]) for record in result]
    
    def get_oncall(self, node_id: str) -> Optional[str]:
        """
        Get the oncall person for a node.
        
        "Who should I page if orders-db is down?"
        
        Args:
            node_id: The node to find oncall for
            
        Returns:
            Oncall identifier (e.g., "@dave"), or None
        """
        # First check the node's oncall property
        node = self.get_node(node_id)
        if node and node.get("oncall"):
            return node["oncall"]
        
        # Then check the owning team's lead
        owner = self.get_owner(node_id)
        if owner:
            return owner.get("lead")
        
        return None
    
    def search_nodes(self, query_text: str) -> list[dict[str, Any]]:
        """
        Search for nodes by name or property values.
        
        Args:
            query_text: Text to search for
            
        Returns:
            List of matching nodes
        """
        query = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($query)
           OR toLower(n.id) CONTAINS toLower($query)
        RETURN n
        LIMIT 20
        """
        
        with self.storage.session() as session:
            result = session.run(query, query=query_text)
            return [dict(record["n"]) for record in result]
    
    def get_graph_stats(self) -> dict[str, int]:
        """Get statistics about the graph."""
        return {
            "node_count": self.storage.get_node_count(),
            "edge_count": self.storage.get_edge_count()
        }
