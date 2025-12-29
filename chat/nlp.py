"""
Natural Language Processing for the Engineering Knowledge Graph.

This module translates natural language queries into graph operations
using OpenAI's function calling capability.
"""

import os
import json
from typing import Any, Optional
from dataclasses import dataclass

from openai import OpenAI


@dataclass
class ParsedIntent:
    """
    Represents a parsed user intent.
    
    Attributes:
        intent_type: Category of the query (ownership, dependency, blast_radius, etc.)
        operation: Specific query operation to perform
        parameters: Parameters for the operation
        original_query: The original natural language query
    """
    intent_type: str
    operation: str
    parameters: dict[str, Any]
    original_query: str


class NLPProcessor:
    """
    Natural language processor using OpenAI for intent classification.
    
    Supports:
    - Ownership queries ("Who owns...")
    - Dependency queries ("What does X depend on...")
    - Blast radius queries ("What breaks if...")
    - Exploration queries ("List all services...")
    - Path queries ("How does X connect to Y...")
    - Follow-up queries with context
    """
    
    # Available functions for the LLM to call
    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "get_node",
                "description": "Get details about a specific node by its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "The node ID, e.g., 'service:order-service' or 'database:users-db'"
                        }
                    },
                    "required": ["node_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_nodes",
                "description": "List all nodes of a specific type",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_type": {
                            "type": "string",
                            "enum": ["service", "database", "cache", "team"],
                            "description": "Type of nodes to list"
                        }
                    },
                    "required": ["node_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_downstream",
                "description": "Get all dependencies of a node (what it depends on)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "The node ID to find dependencies for"
                        }
                    },
                    "required": ["node_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_upstream",
                "description": "Get all dependents of a node (what depends on it, what would break if it goes down)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "The node ID to find dependents for"
                        }
                    },
                    "required": ["node_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "blast_radius",
                "description": "Get full impact analysis: what depends on this node, what it depends on, and affected teams",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "The node ID to analyze blast radius for"
                        }
                    },
                    "required": ["node_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_path",
                "description": "Find the shortest path between two nodes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_node": {
                            "type": "string",
                            "description": "Source node ID"
                        },
                        "to_node": {
                            "type": "string",
                            "description": "Target node ID"
                        }
                    },
                    "required": ["from_node", "to_node"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_owner",
                "description": "Find the team that owns a service or database",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "The node ID to find the owner of"
                        }
                    },
                    "required": ["node_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_team_assets",
                "description": "Get all services and databases owned by a team",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "team_name": {
                            "type": "string",
                            "description": "The team name, e.g., 'orders-team' or 'platform-team'"
                        }
                    },
                    "required": ["team_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_oncall",
                "description": "Get the on-call person for a service or database",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "The node ID to find on-call for"
                        }
                    },
                    "required": ["node_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_nodes",
                "description": "Search for nodes by partial name match",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    SYSTEM_PROMPT = """You are an assistant for an Engineering Knowledge Graph that contains information about services, databases, caches, and teams in an e-commerce platform.

Available nodes in the system:
- Services: api-gateway, auth-service, order-service, payment-service, inventory-service, notification-service, recommendation-service
- Databases: users-db, orders-db, payments-db, inventory-db
- Caches: redis-main
- Teams: platform-team, identity-team, orders-team, payments-team, ml-team

When referencing nodes, use the format: type:name
- For services: service:order-service
- For databases: database:orders-db
- For caches: cache:redis-main
- For teams: team:orders-team

Use the available functions to answer questions about:
- Service ownership (who owns what)
- Dependencies (what depends on what)
- Blast radius (impact of failures)
- Paths between services
- On-call information

If you cannot answer a question or it's outside the scope of infrastructure knowledge, say so clearly.
Do not make up information - only use what the functions return.

When the user asks a follow-up question, use the conversation context to understand what they're referring to.
"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the NLP processor.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")
        
        self.client = OpenAI(api_key=self.api_key)
        self.conversation_history: list[dict] = []
        self.last_mentioned_nodes: list[str] = []
    
    def process_query(self, query: str) -> tuple[str, list[dict]]:
        """
        Process a natural language query and return function calls to execute.
        
        Args:
            query: The user's natural language query
            
        Returns:
            Tuple of (response_text, function_calls)
            where function_calls is a list of {function_name, arguments}
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": query
        })
        
        # Keep conversation history manageable
        if len(self.conversation_history) > 10:
            self.conversation_history = self.conversation_history[-10:]
        
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT}
        ] + self.conversation_history
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=self.TOOLS,
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            
            # Extract function calls
            function_calls = []
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_calls.append({
                        "id": tool_call.id,
                        "function_name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments)
                    })
            
            # Add assistant message to history
            self.conversation_history.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": message.tool_calls
            })
            
            return message.content or "", function_calls
            
        except Exception as e:
            return f"Error processing query: {str(e)}", []
    
    def generate_response(
        self,
        query: str,
        function_results: list[dict]
    ) -> str:
        """
        Generate a natural language response based on function results.
        
        Args:
            query: The original user query
            function_results: Results from executed function calls
            
        Returns:
            Natural language response
        """
        # Add function results to conversation
        for result in function_results:
            self.conversation_history.append({
                "role": "tool",
                "tool_call_id": result["id"],
                "content": json.dumps(result["result"])
            })
            
            # Track mentioned nodes for follow-up context
            if isinstance(result["result"], dict) and result["result"].get("id"):
                self.last_mentioned_nodes.append(result["result"]["id"])
            elif isinstance(result["result"], list):
                for item in result["result"]:
                    if isinstance(item, dict) and item.get("id"):
                        self.last_mentioned_nodes.append(item["id"])
        
        # Keep only recent mentioned nodes
        self.last_mentioned_nodes = self.last_mentioned_nodes[-5:]
        
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT + "\n\nNow provide a helpful, concise response based on the function results."}
        ] + self.conversation_history
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )
            
            response_text = response.choices[0].message.content or ""
            
            # Add to history
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })
            
            return response_text
            
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    def clear_context(self) -> None:
        """Clear conversation history and context."""
        self.conversation_history = []
        self.last_mentioned_nodes = []
