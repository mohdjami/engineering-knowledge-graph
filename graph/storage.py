"""
Graph Storage Layer using Neo4j.

This module provides the persistence layer for the Engineering Knowledge Graph,
supporting CRUD operations on nodes and edges stored in Neo4j.
"""

import json
import os
from typing import Any, Optional
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable, AuthError

from connectors.base import Node, Edge


class GraphStorage:
    """
    Storage layer for the knowledge graph using Neo4j.
    
    Provides:
    - Upsert operations for nodes and edges
    - Retrieval by ID and by type
    - Deletion with cascade for connected edges
    - Connection management with retry logic
    """
    
    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None
    ):
        """
        Initialize the graph storage.
        
        Args:
            uri: Neo4j connection URI (defaults to NEO4J_URI env var)
            user: Neo4j username (defaults to NEO4J_USER env var)
            password: Neo4j password (defaults to NEO4J_PASSWORD env var)
        """
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        
        self._driver: Optional[Driver] = None
    
    def connect(self) -> None:
        """Establish connection to Neo4j."""
        try:
            # For Neo4j Aura (neo4j+s://), encryption is handled by the URI scheme
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
            # Verify connectivity
            self._driver.verify_connectivity()
        except AuthError as e:
            raise ConnectionError(f"Authentication failed: {e}")
        except ServiceUnavailable as e:
            raise ConnectionError(f"Neo4j service unavailable: {e}")
    
    def close(self) -> None:
        """Close the database connection."""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    @contextmanager
    def session(self):
        """Context manager for database sessions."""
        if not self._driver:
            self.connect()
        session = self._driver.session()
        try:
            yield session
        finally:
            session.close()
    
    def upsert_node(self, node: Node) -> None:
        """
        Insert or update a node in the graph.
        
        Uses MERGE to create if not exists, then SET to update properties.
        
        Args:
            node: The node to upsert
        """
        # Sanitize label for Cypher (remove special chars, use PascalCase)
        label = self._sanitize_label(node.type)
        
        # Flatten properties (Neo4j doesn't support nested objects)
        flat_props = self._flatten_properties(node.properties)
        
        query = f"""
        MERGE (n:{label} {{id: $id}})
        SET n.name = $name,
            n.type = $type,
            n += $properties
        """
        
        with self.session() as session:
            session.run(
                query,
                id=node.id,
                name=node.name,
                type=node.type,
                properties=flat_props
            )
    
    def upsert_edge(self, edge: Edge) -> None:
        """
        Insert or update an edge in the graph.
        
        Creates the relationship between source and target nodes.
        Nodes must exist before creating edges.
        
        Args:
            edge: The edge to upsert
        """
        # Sanitize relationship type for Cypher
        rel_type = self._sanitize_relationship(edge.type)
        
        # Flatten properties
        flat_props = self._flatten_properties(edge.properties)
        
        query = f"""
        MATCH (source {{id: $source}})
        MATCH (target {{id: $target}})
        MERGE (source)-[r:{rel_type} {{id: $id}}]->(target)
        SET r += $properties
        """
        
        with self.session() as session:
            session.run(
                query,
                id=edge.id,
                source=edge.source,
                target=edge.target,
                properties=flat_props
            )
    
    def get_node(self, node_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve a node by its ID.
        
        Args:
            node_id: The unique node ID
            
        Returns:
            Node data as dictionary, or None if not found
        """
        query = """
        MATCH (n {id: $id})
        RETURN n
        """
        
        with self.session() as session:
            result = session.run(query, id=node_id)
            record = result.single()
            
            if record:
                node_data = dict(record["n"])
                return node_data
            return None
    
    def get_nodes(
        self,
        node_type: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """
        Retrieve nodes by type and/or filters.
        
        Args:
            node_type: Filter by node type (service, database, etc.)
            filters: Additional property filters
            
        Returns:
            List of matching nodes as dictionaries
        """
        filters = filters or {}
        
        if node_type:
            label = self._sanitize_label(node_type)
            query = f"MATCH (n:{label})"
        else:
            query = "MATCH (n)"
        
        # Add property filters
        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append(f"n.{key} = ${key}")
            query += " WHERE " + " AND ".join(conditions)
        
        query += " RETURN n"
        
        with self.session() as session:
            result = session.run(query, **filters)
            return [dict(record["n"]) for record in result]
    
    def delete_node(self, node_id: str) -> bool:
        """
        Delete a node and all its connected edges.
        
        Args:
            node_id: The ID of the node to delete
            
        Returns:
            True if node was deleted, False if not found
        """
        query = """
        MATCH (n {id: $id})
        DETACH DELETE n
        RETURN count(n) as deleted
        """
        
        with self.session() as session:
            result = session.run(query, id=node_id)
            record = result.single()
            return record["deleted"] > 0 if record else False
    
    def clear_graph(self) -> None:
        """Delete all nodes and edges from the graph."""
        query = """
        MATCH (n)
        DETACH DELETE n
        """
        
        with self.session() as session:
            session.run(query)
    
    def get_all_nodes(self) -> list[dict[str, Any]]:
        """Retrieve all nodes in the graph."""
        query = """
        MATCH (n)
        RETURN n
        """
        
        with self.session() as session:
            result = session.run(query)
            return [dict(record["n"]) for record in result]
    
    def get_all_edges(self) -> list[dict[str, Any]]:
        """Retrieve all edges in the graph."""
        query = """
        MATCH (source)-[r]->(target)
        RETURN r, source.id as source_id, target.id as target_id, type(r) as rel_type
        """
        
        with self.session() as session:
            result = session.run(query)
            edges = []
            for record in result:
                edge_data = dict(record["r"])
                edge_data["source"] = record["source_id"]
                edge_data["target"] = record["target_id"]
                edge_data["type"] = record["rel_type"]
                edges.append(edge_data)
            return edges
    
    def get_node_count(self) -> int:
        """Get the total number of nodes."""
        query = "MATCH (n) RETURN count(n) as count"
        
        with self.session() as session:
            result = session.run(query)
            record = result.single()
            return record["count"] if record else 0
    
    def get_edge_count(self) -> int:
        """Get the total number of edges."""
        query = "MATCH ()-[r]->() RETURN count(r) as count"
        
        with self.session() as session:
            result = session.run(query)
            record = result.single()
            return record["count"] if record else 0
    
    def create_indexes(self) -> None:
        """Create indexes for better query performance."""
        indexes = [
            "CREATE INDEX node_id IF NOT EXISTS FOR (n:Service) ON (n.id)",
            "CREATE INDEX node_id IF NOT EXISTS FOR (n:Database) ON (n.id)",
            "CREATE INDEX node_id IF NOT EXISTS FOR (n:Cache) ON (n.id)",
            "CREATE INDEX node_id IF NOT EXISTS FOR (n:Team) ON (n.id)",
        ]
        
        with self.session() as session:
            for index_query in indexes:
                try:
                    session.run(index_query)
                except Exception:
                    # Index might already exist
                    pass
    
    def _sanitize_label(self, label: str) -> str:
        """
        Sanitize a string for use as a Neo4j label.
        
        Converts to PascalCase and removes invalid characters.
        """
        # Remove common prefixes and clean up
        label = label.replace("-", "_").replace(" ", "_")
        # Convert to PascalCase
        parts = label.split("_")
        return "".join(part.capitalize() for part in parts)
    
    def _sanitize_relationship(self, rel_type: str) -> str:
        """
        Sanitize a string for use as a Neo4j relationship type.
        
        Converts to UPPER_SNAKE_CASE.
        """
        return rel_type.upper().replace("-", "_").replace(" ", "_")
    
    def _flatten_properties(self, properties: dict[str, Any]) -> dict[str, Any]:
        """
        Flatten nested properties for Neo4j storage.
        
        Neo4j only supports primitive types and arrays of primitives.
        Nested objects are serialized to JSON strings.
        """
        flat = {}
        for key, value in properties.items():
            if isinstance(value, dict):
                # Serialize dicts to JSON strings
                flat[key] = json.dumps(value)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                # Serialize list of dicts to JSON strings
                flat[key] = json.dumps(value)
            else:
                flat[key] = value
        return flat
