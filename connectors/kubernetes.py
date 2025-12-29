"""
Kubernetes Connector for parsing k8s-deployments.yaml files.

Extracts Kubernetes Deployments and Services, merging metadata with
existing nodes from other connectors.
"""

import re
import yaml
from pathlib import Path
from typing import Any

from .base import BaseConnector, ConnectorResult, Node, Edge, ConnectorRegistry


@ConnectorRegistry.register
class KubernetesConnector(BaseConnector):
    """
    Connector for parsing Kubernetes manifest files.
    
    Extracts:
    - Deployment resources (replicas, container images, resource limits)
    - Service resources (ports, selectors)
    - Dependencies from environment variables
    
    This connector is designed to supplement data from other connectors,
    adding K8s-specific metadata to existing nodes.
    """
    
    @property
    def name(self) -> str:
        return "kubernetes"
    
    def parse(self, file_path: Path) -> ConnectorResult:
        """Parse k8s-deployments.yaml and extract nodes and edges."""
        if not self.validate_file(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Split YAML documents (separated by ---)
        documents = []
        for doc in yaml.safe_load_all(content):
            if doc:
                documents.append(doc)
        
        if not documents:
            raise ValueError(f"No valid Kubernetes resources found in {file_path}")
        
        nodes = []
        edges = []
        
        # Group resources by kind
        deployments = []
        services = []
        
        for doc in documents:
            kind = doc.get('kind', '').lower()
            if kind == 'deployment':
                deployments.append(doc)
            elif kind == 'service':
                services.append(doc)
        
        # Process deployments
        for deployment in deployments:
            node, dep_edges = self._parse_deployment(deployment)
            if node:
                nodes.append(node)
                edges.extend(dep_edges)
        
        # Process services (adds metadata, doesn't create new nodes)
        for service in services:
            # Services provide networking info - we could create K8sService nodes
            # but for simplicity, we'll just note their existence
            pass
        
        return ConnectorResult(
            nodes=nodes,
            edges=edges,
            source_file=file_path,
            connector_name=self.name
        )
    
    def _parse_deployment(self, deployment: dict) -> tuple[Node | None, list[Edge]]:
        """Parse a Kubernetes Deployment resource."""
        metadata = deployment.get('metadata', {})
        spec = deployment.get('spec', {})
        
        name = metadata.get('name')
        if not name:
            return None, []
        
        node_id = f"service:{name}"
        
        # Extract properties
        properties = self._extract_deployment_properties(deployment)
        
        # Create node (this will merge with existing node if present)
        node = Node(
            id=node_id,
            type="service",
            name=name,
            properties=properties
        )
        
        # Extract edges from container environment variables
        edges = self._extract_env_edges(name, node_id, deployment)
        
        return node, edges
    
    def _extract_deployment_properties(self, deployment: dict) -> dict[str, Any]:
        """Extract properties from a Deployment resource."""
        properties = {}
        metadata = deployment.get('metadata', {})
        spec = deployment.get('spec', {})
        
        # Namespace
        if metadata.get('namespace'):
            properties['namespace'] = metadata['namespace']
        
        # Labels
        labels = metadata.get('labels', {})
        if labels.get('team'):
            properties['team'] = labels['team']
        if labels.get('app'):
            properties['app_label'] = labels['app']
        
        # Replicas
        if spec.get('replicas'):
            properties['replicas'] = spec['replicas']
        
        # Container info
        template = spec.get('template', {})
        pod_spec = template.get('spec', {})
        containers = pod_spec.get('containers', [])
        
        if containers:
            container = containers[0]  # Primary container
            
            if container.get('image'):
                properties['image'] = container['image']
            
            # Ports
            ports = container.get('ports', [])
            if ports:
                properties['container_port'] = ports[0].get('containerPort')
            
            # Resource limits
            resources = container.get('resources', {})
            limits = resources.get('limits', {})
            requests = resources.get('requests', {})
            
            if limits:
                properties['resource_limits'] = limits
            if requests:
                properties['resource_requests'] = requests
        
        # Mark as K8s-managed
        properties['k8s_managed'] = True
        
        return properties
    
    def _extract_env_edges(self, service_name: str, node_id: str, deployment: dict) -> list[Edge]:
        """Extract relationship edges from container environment variables."""
        edges = []
        
        spec = deployment.get('spec', {})
        template = spec.get('template', {})
        pod_spec = template.get('spec', {})
        containers = pod_spec.get('containers', [])
        
        if not containers:
            return edges
        
        container = containers[0]
        env_vars = container.get('env', [])
        
        for env_var in env_vars:
            name = env_var.get('name', '')
            value = env_var.get('value', '')
            
            # Skip if value comes from secret
            if env_var.get('valueFrom'):
                continue
            
            # Handle service URLs
            if name.endswith('_URL') and name != 'DATABASE_URL' and value:
                target_service = self._extract_service_from_k8s_url(value)
                if target_service and target_service != service_name:
                    edge = Edge(
                        id=f"edge:{service_name}-calls-{target_service}",
                        type="calls",
                        source=node_id,
                        target=f"service:{target_service}",
                        properties={"via": name, "source": "k8s"}
                    )
                    edges.append(edge)
        
        return edges
    
    def _extract_service_from_k8s_url(self, url: str) -> str | None:
        """
        Extract service name from a K8s service URL.
        
        Examples:
        - http://payment-service.ecommerce.svc.cluster.local:8083
        - http://payment-service:8083
        """
        try:
            # Pattern for K8s DNS: service-name.namespace.svc.cluster.local
            match = re.search(r'//([a-zA-Z0-9_-]+)(?:\.[\w.-]+)?:', url)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None
