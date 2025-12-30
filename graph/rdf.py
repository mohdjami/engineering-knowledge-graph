"""
RDF Conversion Module for Engineering Knowledge Graph.

This module handles the transformation of Property Graph data (Nodes/Edges)
into Semantic Web standards (RDF/Turtle) using a custom Ontology.
"""

from rdflib import Graph, Literal, RDF, RDFS, Namespace, URIRef
from rdflib.namespace import FOAF, XSD
from typing import Any

from graph.storage import GraphStorage


class RDFExporter:
    """
    Exports the Engineering Knowledge Graph to RDF format.
    """
    
    def __init__(self, storage: GraphStorage):
        self.storage = storage
        self.g = Graph()
        
        # Define Namespaces
        self.EKG = Namespace("http://mycompany.com/ekg#")
        self.g.bind("ekg", self.EKG)
        self.g.bind("foaf", FOAF)
        
    def _clean_id(self, node_id: str) -> str:
        """Clean node ID for URI usage (remove prefix)."""
        if ":" in node_id:
            return node_id.split(":", 1)[1]
        return node_id

    def _get_uri(self, node_id: str, node_type: str) -> URIRef:
        """Generate URI for a node."""
        clean_name = self._clean_id(node_id)
        # Use PascalCase for Type (class) reference if needed, but here simple ID reference
        return self.EKG[clean_name]

    def _map_type_to_class(self, node_type: str) -> URIRef:
        """Map internal node types to Ontology classes."""
        mapping = {
            "service": self.EKG.Service,
            "database": self.EKG.Database,
            "cache": self.EKG.Cache,
            "team": self.EKG.Team,
            "person": FOAF.Person
        }
        return mapping.get(node_type, self.EKG.Resource)

    def _map_edge_to_predicate(self, edge_type: str) -> URIRef:
        """Map internal edge types to Ontology properties."""
        mapping = {
            "owns": self.EKG.owns,
            "depends_on": self.EKG.dependsOn,
            "calls": self.EKG.calls,
            "reads_from": self.EKG.readsFrom,
            "writes_to": self.EKG.writesTo,
            "uses": self.EKG.uses
        }
        return mapping.get(edge_type, self.EKG.relatedTo)

    def generate_graph(self) -> Graph:
        """
        Fetch data from storage and build the RDF graph.
        
        Returns:
            rdflib.Graph populated with triples.
        """
        # 1. Fetch all data
        nodes = self.storage.get_all_nodes()
        edges = self.storage.get_all_edges()
        
        # 2. Add Nodes as Subjects
        for node in nodes:
            node_uri = self._get_uri(node["id"], node["type"])
            node_class = self._map_type_to_class(node["type"])
            
            # Type definition
            self.g.add((node_uri, RDF.type, node_class))
            
            # Label
            self.g.add((node_uri, RDFS.label, Literal(node["name"], datatype=XSD.string)))
            
            # Properties (Metadata)
            if "properties" in node:
                for k, v in node["properties"].items():
                    if k == "channel": continue # Skip internal-ish keys if desired
                    
                    # Store properties as ekg:hasPropertyName
                    # Capitalize first letter for property name convention if desired
                    prop_name = f"has{k.capitalize()}"
                    predicate = self.EKG[prop_name]
                    
                    self.g.add((node_uri, predicate, Literal(str(v), datatype=XSD.string)))

        # 3. Add Edges as Predicates
        for edge in edges:
            source_uri = self._get_uri(edge["source"], "") # Type unknown here without lookup, but ID is enough
            target_uri = self._get_uri(edge["target"], "")
            predicate = self._map_edge_to_predicate(edge["type"])
            
            self.g.add((source_uri, predicate, target_uri))
            
        return self.g

    def export_turtle(self) -> str:
        """Generate Turtle string."""
        self.generate_graph()
        return self.g.serialize(format="turtle")
