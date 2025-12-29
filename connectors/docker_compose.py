"""
Docker Compose Connector for parsing docker-compose.yml files.

Extracts services, databases, caches and their relationships from
Docker Compose configuration files.
"""

import re
import yaml
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .base import BaseConnector, ConnectorResult, Node, Edge, ConnectorRegistry


@ConnectorRegistry.register
class DockerComposeConnector(BaseConnector):
    """
    Connector for parsing Docker Compose configuration files.
    
    Extracts:
    - Services (application containers)
    - Databases (postgres, mysql, etc.)
    - Caches (redis, memcached, etc.)
    - Dependencies from depends_on
    - Service calls from environment variables (URLs)
    - Database connections from DATABASE_URL
    - Team ownership from labels
    """
    
    @property
    def name(self) -> str:
        return "docker_compose"
    
    def parse(self, file_path: Path) -> ConnectorResult:
        """Parse docker-compose.yml and extract nodes and edges."""
        if not self.validate_file(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(file_path, 'r') as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML in {file_path}: {e}")
        
        if not data or 'services' not in data:
            raise ValueError(f"No services found in {file_path}")
        
        nodes = []
        edges = []
        
        services = data.get('services', {})
        
        for service_name, service_config in services.items():
            if service_config is None:
                continue
                
            # Determine node type based on image/labels
            node_type = self._determine_node_type(service_name, service_config)
            
            # Extract properties
            properties = self._extract_properties(service_config)
            
            # Create node
            node_id = f"{node_type}:{service_name}"
            node = Node(
                id=node_id,
                type=node_type,
                name=service_name,
                properties=properties
            )
            nodes.append(node)
            
            # Extract edges from depends_on
            depends_on = service_config.get('depends_on', [])
            if isinstance(depends_on, dict):
                depends_on = list(depends_on.keys())
            
            for dep in depends_on:
                dep_type = self._determine_node_type(dep, services.get(dep, {}))
                edge = Edge(
                    id=f"edge:{service_name}-depends_on-{dep}",
                    type="depends_on",
                    source=node_id,
                    target=f"{dep_type}:{dep}",
                    properties={}
                )
                edges.append(edge)
            
            # Extract edges from environment variables
            env_edges = self._extract_env_edges(service_name, node_id, service_config, services)
            edges.extend(env_edges)
        
        return ConnectorResult(
            nodes=nodes,
            edges=edges,
            source_file=file_path,
            connector_name=self.name
        )
    
    def _determine_node_type(self, name: str, config: dict) -> str:
        """Determine if a service is a database, cache, or regular service."""
        if not config:
            # Try to infer from name
            if name.endswith('-db') or 'database' in name:
                return 'database'
            if 'redis' in name or 'cache' in name or 'memcached' in name:
                return 'cache'
            return 'service'
        
        # Check labels
        labels = config.get('labels', {})
        if isinstance(labels, list):
            labels = {l.split('=')[0]: l.split('=')[1] for l in labels if '=' in l}
        
        if labels.get('type') == 'database':
            return 'database'
        if labels.get('type') == 'cache':
            return 'cache'
        
        # Check image
        image = config.get('image', '')
        if any(db in image.lower() for db in ['postgres', 'mysql', 'mariadb', 'mongo', 'sqlite']):
            return 'database'
        if any(cache in image.lower() for cache in ['redis', 'memcached', 'hazelcast']):
            return 'cache'
        
        return 'service'
    
    def _extract_properties(self, config: dict) -> dict[str, Any]:
        """Extract relevant properties from service configuration."""
        properties = {}
        
        # Extract ports
        ports = config.get('ports', [])
        if ports:
            # Parse port mapping (e.g., "8080:8080" -> 8080)
            first_port = ports[0] if ports else None
            if first_port:
                if isinstance(first_port, str) and ':' in first_port:
                    properties['port'] = int(first_port.split(':')[0])
                elif isinstance(first_port, int):
                    properties['port'] = first_port
        
        # Extract labels
        labels = config.get('labels', {})
        if isinstance(labels, list):
            labels = {l.split('=')[0]: l.split('=')[1] for l in labels if '=' in l}
        
        if labels.get('team'):
            properties['team'] = labels['team']
        if labels.get('oncall'):
            properties['oncall'] = labels['oncall']
        if labels.get('pci_compliant'):
            properties['pci_compliant'] = labels['pci_compliant'] == 'true'
        if labels.get('encrypted'):
            properties['encrypted'] = labels['encrypted'] == 'true'
        
        # Extract image
        if config.get('image'):
            properties['image'] = config['image']
        
        # Extract build path
        if config.get('build'):
            build = config['build']
            if isinstance(build, str):
                properties['build_path'] = build
            elif isinstance(build, dict):
                properties['build_path'] = build.get('context', '')
        
        return properties
    
    def _extract_env_edges(self, service_name: str, node_id: str, config: dict, all_services: dict) -> list[Edge]:
        """Extract relationship edges from environment variables."""
        edges = []
        
        environment = config.get('environment', [])
        if isinstance(environment, list):
            env_dict = {}
            for item in environment:
                if '=' in item:
                    key, value = item.split('=', 1)
                    env_dict[key] = value
            environment = env_dict
        elif not isinstance(environment, dict):
            environment = {}
        
        for key, value in environment.items():
            # Handle service URLs (e.g., PAYMENT_SERVICE_URL=http://payment-service:8083)
            if key.endswith('_URL') and key != 'DATABASE_URL' and 'REDIS' not in key:
                target_service = self._extract_service_from_url(value, all_services)
                if target_service:
                    target_type = self._determine_node_type(target_service, all_services.get(target_service, {}))
                    edge = Edge(
                        id=f"edge:{service_name}-calls-{target_service}",
                        type="calls",
                        source=node_id,
                        target=f"{target_type}:{target_service}",
                        properties={"via": key}
                    )
                    edges.append(edge)
            
            # Handle DATABASE_URL (e.g., postgresql://...@users-db:5432/users)
            elif key == 'DATABASE_URL':
                db_name = self._extract_db_from_url(value, all_services)
                if db_name:
                    edge = Edge(
                        id=f"edge:{service_name}-uses-{db_name}",
                        type="uses",
                        source=node_id,
                        target=f"database:{db_name}",
                        properties={"connection_type": "database"}
                    )
                    edges.append(edge)
            
            # Handle REDIS_URL
            elif 'REDIS_URL' in key or key == 'CACHE_URL':
                cache_name = self._extract_cache_from_url(value, all_services)
                if cache_name:
                    edge = Edge(
                        id=f"edge:{service_name}-uses-{cache_name}",
                        type="uses",
                        source=node_id,
                        target=f"cache:{cache_name}",
                        properties={"connection_type": "cache"}
                    )
                    edges.append(edge)
        
        return edges
    
    def _extract_service_from_url(self, url: str, all_services: dict) -> str | None:
        """Extract service name from a URL like http://payment-service:8083."""
        try:
            # Handle URLs with http:// prefix
            if url.startswith('http://') or url.startswith('https://'):
                parsed = urlparse(url)
                host = parsed.hostname
                if host and host in all_services:
                    return host
            
            # Try regex for hostname pattern
            match = re.search(r'//([a-zA-Z0-9_-]+):', url)
            if match:
                host = match.group(1)
                if host in all_services:
                    return host
        except Exception:
            pass
        return None
    
    def _extract_db_from_url(self, url: str, all_services: dict) -> str | None:
        """Extract database name from a DATABASE_URL."""
        try:
            # Pattern: postgresql://user:pass@hostname:port/dbname
            match = re.search(r'@([a-zA-Z0-9_-]+):', url)
            if match:
                host = match.group(1)
                if host in all_services:
                    return host
        except Exception:
            pass
        return None
    
    def _extract_cache_from_url(self, url: str, all_services: dict) -> str | None:
        """Extract cache name from a REDIS_URL or similar."""
        try:
            # Pattern: redis://hostname:port
            match = re.search(r'//([a-zA-Z0-9_-]+):', url)
            if match:
                host = match.group(1)
                if host in all_services:
                    return host
        except Exception:
            pass
        return None
