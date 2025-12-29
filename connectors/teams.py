"""
Teams Connector for parsing teams.yaml files.

Extracts team entities and their ownership relationships to services,
databases, and other infrastructure components.
"""

import yaml
from pathlib import Path
from typing import Any

from .base import BaseConnector, ConnectorResult, Node, Edge, ConnectorRegistry


@ConnectorRegistry.register
class TeamsConnector(BaseConnector):
    """
    Connector for parsing team configuration files.
    
    Extracts:
    - Team entities with metadata (lead, slack channel, pagerduty schedule)
    - Ownership relationships between teams and services/databases
    """
    
    @property
    def name(self) -> str:
        return "teams"
    
    def parse(self, file_path: Path) -> ConnectorResult:
        """Parse teams.yaml and extract team nodes and ownership edges."""
        if not self.validate_file(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(file_path, 'r') as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML in {file_path}: {e}")
        
        if not data or 'teams' not in data:
            raise ValueError(f"No teams found in {file_path}")
        
        nodes = []
        edges = []
        
        teams = data.get('teams', [])
        
        for team in teams:
            if not team or not team.get('name'):
                continue
            
            team_name = team['name']
            node_id = f"team:{team_name}"
            
            # Extract properties
            properties = self._extract_properties(team)
            
            # Create team node
            node = Node(
                id=node_id,
                type="team",
                name=team_name,
                properties=properties
            )
            nodes.append(node)
            
            # Create ownership edges
            owns = team.get('owns', [])
            for owned_item in owns:
                # We need to guess the type of the owned item
                # This will be resolved when merging with docker-compose data
                target_type = self._guess_type(owned_item)
                target_id = f"{target_type}:{owned_item}"
                
                edge = Edge(
                    id=f"edge:{team_name}-owns-{owned_item}",
                    type="owns",
                    source=node_id,
                    target=target_id,
                    properties={}
                )
                edges.append(edge)
        
        return ConnectorResult(
            nodes=nodes,
            edges=edges,
            source_file=file_path,
            connector_name=self.name
        )
    
    def _extract_properties(self, team: dict) -> dict[str, Any]:
        """Extract team properties."""
        properties = {}
        
        if team.get('lead'):
            properties['lead'] = team['lead']
        if team.get('slack_channel'):
            properties['slack_channel'] = team['slack_channel']
        if team.get('pagerduty_schedule'):
            properties['pagerduty_schedule'] = team['pagerduty_schedule']
        
        # Count owned items
        owns = team.get('owns', [])
        properties['owned_count'] = len(owns)
        
        return properties
    
    def _guess_type(self, name: str) -> str:
        """
        Guess the type of an owned item based on its name.
        
        This is a heuristic - the actual type will be confirmed when
        merging with data from other connectors.
        """
        name_lower = name.lower()
        
        if name_lower.endswith('-db') or 'database' in name_lower:
            return 'database'
        if 'redis' in name_lower or 'cache' in name_lower or 'memcached' in name_lower:
            return 'cache'
        
        return 'service'
