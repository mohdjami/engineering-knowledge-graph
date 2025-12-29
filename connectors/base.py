"""
Base connector interface and data models for the Engineering Knowledge Graph.

This module defines the abstract interface that all connectors must implement,
along with the Node and Edge data structures used throughout the system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from pathlib import Path


@dataclass
class Node:
    """
    Represents a node in the knowledge graph.
    
    Attributes:
        id: Unique identifier with type prefix (e.g., "service:order-service")
        type: Node type (service, database, cache, team, etc.)
        name: Human-readable name
        properties: Additional metadata as key-value pairs
    """
    id: str
    type: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "properties": self.properties
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        """Create Node from dictionary."""
        return cls(
            id=data["id"],
            type=data["type"],
            name=data["name"],
            properties=data.get("properties", {})
        )


@dataclass
class Edge:
    """
    Represents an edge (relationship) in the knowledge graph.
    
    Attributes:
        id: Unique identifier for the edge
        type: Relationship type (calls, reads_from, writes_to, owns, uses, depends_on)
        source: Source node ID
        target: Target node ID
        properties: Additional metadata as key-value pairs
    """
    id: str
    type: str
    source: str
    target: str
    properties: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "target": self.target,
            "properties": self.properties
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Edge":
        """Create Edge from dictionary."""
        return cls(
            id=data["id"],
            type=data["type"],
            source=data["source"],
            target=data["target"],
            properties=data.get("properties", {})
        )


@dataclass
class ConnectorResult:
    """
    Result from a connector's parse operation.
    
    Attributes:
        nodes: List of nodes extracted from the source
        edges: List of edges (relationships) extracted from the source
        source_file: Path to the source file that was parsed
        connector_name: Name of the connector that produced this result
    """
    nodes: list[Node]
    edges: list[Edge]
    source_file: Optional[Path] = None
    connector_name: str = ""


class BaseConnector(ABC):
    """
    Abstract base class for all connectors.
    
    Connectors are responsible for parsing infrastructure configuration files
    and extracting nodes and edges for the knowledge graph.
    
    To add a new connector:
    1. Create a new file in connectors/ (e.g., terraform.py)
    2. Implement a class that inherits from BaseConnector
    3. Implement the parse() method
    4. Register with ConnectorRegistry
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the connector name."""
        pass
    
    @abstractmethod
    def parse(self, file_path: Path) -> ConnectorResult:
        """
        Parse a configuration file and extract nodes and edges.
        
        Args:
            file_path: Path to the configuration file
            
        Returns:
            ConnectorResult containing extracted nodes and edges
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is invalid
        """
        pass
    
    def validate_file(self, file_path: Path) -> bool:
        """
        Validate that a file exists and is readable.
        
        Args:
            file_path: Path to validate
            
        Returns:
            True if file is valid, False otherwise
        """
        return file_path.exists() and file_path.is_file()


class ConnectorRegistry:
    """
    Registry for managing available connectors.
    
    This provides a pluggable architecture where new connectors can be
    registered without modifying core code.
    """
    
    _connectors: dict[str, type[BaseConnector]] = {}
    
    @classmethod
    def register(cls, connector_class: type[BaseConnector]) -> type[BaseConnector]:
        """
        Register a connector class.
        
        Can be used as a decorator:
            @ConnectorRegistry.register
            class MyConnector(BaseConnector):
                ...
        """
        # Create a temporary instance to get the name
        instance = connector_class.__new__(connector_class)
        # Handle case where name is a property
        if hasattr(connector_class, 'name'):
            # Try to get name without initialization
            try:
                name = connector_class.name.fget(instance) if isinstance(connector_class.name, property) else instance.name
            except:
                # Fallback to class name
                name = connector_class.__name__.lower().replace('connector', '')
        else:
            name = connector_class.__name__.lower()
        
        cls._connectors[name] = connector_class
        return connector_class
    
    @classmethod
    def get(cls, name: str) -> Optional[type[BaseConnector]]:
        """Get a connector class by name."""
        return cls._connectors.get(name)
    
    @classmethod
    def list_connectors(cls) -> list[str]:
        """List all registered connector names."""
        return list(cls._connectors.keys())
    
    @classmethod
    def create_instance(cls, name: str) -> Optional[BaseConnector]:
        """Create an instance of a connector by name."""
        connector_class = cls.get(name)
        if connector_class:
            return connector_class()
        return None
