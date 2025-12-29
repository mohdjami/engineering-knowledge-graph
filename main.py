"""
Engineering Knowledge Graph - Main Entry Point

This module starts the FastAPI application server.
"""

import os
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def main():
    """Run the application."""
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"🚀 Starting Engineering Knowledge Graph on {host}:{port}")
    
    uvicorn.run(
        "chat.api:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG", "false").lower() == "true"
    )


if __name__ == "__main__":
    main()
