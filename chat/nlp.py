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
    """
    intent_type: str
    operation: str
    parameters: dict[str, Any]
    original_query: str


class NLPProcessor:
    """
    Natural language processor using LangChain and OpenAI.
    
    Supports persistent chat history via Redis.
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
        
        self.redis_url = os.getenv("REDIS_URL")
        if not self.redis_url:
            raise ValueError("REDIS_URL environment variable not set")
            
        self.client = OpenAI(api_key=self.api_key)
        
        # We will initialize history per session request
    
    def _get_history(self, session_id: str):
        """Get Redis-backed chat history."""
        from langchain_community.chat_message_histories import RedisChatMessageHistory
        
        return RedisChatMessageHistory(
            session_id=session_id,
            url=self.redis_url,
            # Data expiry (optional, e.g., 2 weeks)
            ttl=1209600
        )

    def process_query(self, query: str, session_id: str) -> tuple[str, list[dict]]:
        """
        Process a natural language query and return function calls to execute.
        """
        history = self._get_history(session_id)
        
        # Add user message
        history.add_user_message(query)
        
        # Construct message list for OpenAI
        # We need to convert LangChain messages to OpenAI format
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        
        # Get recent history (limit context window)
        lc_messages = history.messages[-10:] 
        
        for msg in lc_messages:
            role = "user" if msg.type == "human" else "assistant"
            # Note: LangChain stores function calls differently, but for simplicity
            # in this hybrid approach, we'll mainly rely on text content for context
            # or we could fully parse them.
            # Ideally we'd validly reconstruct tool calls.
            # For now, let's just pass text content to keep context.
            messages.append({"role": role, "content": msg.content})
            
        # Add current user query (it's already in history but we're building the prompt)
        # Actually history.messages includes the one we just added.
        
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
            
            # We DON'T add the intermediate assistant message (with tool calls) to history 
            # to avoid cluttering human-readable history, OR we can if we want full debug.
            # For this simple implementation, we'll only store the FINAL response in history.
            
            return message.content or "", function_calls
            
        except Exception as e:
            return f"Error processing query: {str(e)}", []
    
    def generate_response(
        self,
        query: str,
        function_results: list[dict],
        session_id: str
    ) -> str:
        """
        Generate a natural language response based on function results.
        """
        history = self._get_history(session_id)
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        
        # Reconstruct context
        lc_messages = history.messages[-10:]
        for msg in lc_messages:
            role = "user" if msg.type == "human" else "assistant"
            messages.append({"role": role, "content": msg.content})
            
        # Appending function results effectively as "system" or "tool" context for the final generation
        # Since we aren't using the full tool-call history flow in LangChain here,
        # we can inject the results as a system message context
        
        results_context = "\n\nFunction Results:\n"
        for result in function_results:
            results_context += f"Function: {result['function_name']}\nResult: {json.dumps(result['result'])}\n\n"
            
        messages.append({
            "role": "system", 
            "content": f"The user asked: '{query}'.\nHere is the data obtained from the system to answer the question:\n{results_context}\n\nProvide a helpful, concise response based ONLY on this data."
        })
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )
            
            response_text = response.choices[0].message.content or ""
            
            # Add final response to history
            history.add_ai_message(response_text)
            
            return response_text
            
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    def clear_context(self, session_id: str) -> None:
        """Clear conversation history."""
        history = self._get_history(session_id)
        history.clear()

