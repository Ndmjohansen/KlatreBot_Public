#!/usr/bin/env python3
"""
Embedding Generation Script

This script generates embeddings for existing messages in the database.
It can be run to populate the RAG system with historical data.
"""

import asyncio
import argparse
import logging
from MessageDatabase import MessageDatabase
from RAGEmbeddingService import RAGEmbeddingService
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os

# Load .env file if it exists
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="Generate embeddings for existing messages")
    parser.add_argument("--openai-key", help="OpenAI API key (or use openaikey from .env)")
    parser.add_argument("--db-path", default="klatrebot.db", help="SQLite database path")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum messages to process")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing")
    
    args = parser.parse_args()
    
    # Get OpenAI key from args or environment
    openai_key = args.openai_key or os.getenv('openaikey')
    if not openai_key:
        logger.error("OpenAI key not provided. Use --openai-key or set openaikey in .env file")
        return
    
    try:
        # Initialize services
        logger.info("Initializing services...")
        message_db = MessageDatabase(args.db_path)
        await message_db.initialize()
        
        openai_client = AsyncOpenAI(api_key=openai_key)
        embedding_service = RAGEmbeddingService(openai_client, message_db)
        
        # Generate message embeddings
        logger.info(f"Generating embeddings for up to {args.limit} messages...")
        success_count = await embedding_service.generate_message_embeddings(args.limit)
        logger.info(f"Generated {success_count} message embeddings")
        
        
        # Show final stats
        stats = await embedding_service.get_embedding_stats()
        logger.info(f"Final stats: {stats}")
        
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    asyncio.run(main())
