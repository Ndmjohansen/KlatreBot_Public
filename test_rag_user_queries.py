#!/usr/bin/env python3
"""
Test script for RAG user-specific queries

This script demonstrates how the enhanced RAG system handles user-specific queries
like "What did Troels talk about 5 days ago, something with fish?"
"""

import asyncio
import logging
from MessageDatabase import MessageDatabase
from RAGEmbeddingService import RAGEmbeddingService
from RAGQueryService import RAGQueryService
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os

# Load .env file if it exists
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_user_query_parsing():
    """Test the user query parsing functionality"""
    
    # Initialize services
    message_db = MessageDatabase()
    await message_db.initialize()
    
    # Create a mock embedding service for testing
    class MockEmbeddingService:
        async def generate_embedding(self, text):
            # Return a mock embedding (just for testing parsing)
            return [0.1] * 1536  # text-embedding-3-small has 1536 dimensions
    
    embedding_service = MockEmbeddingService()
    rag_query_service = RAGQueryService(message_db, embedding_service)
    
    # Test queries
    test_queries = [
        "What did Troels talk about 5 days ago, something with fish?",
        "What did Magnus say yesterday about climbing?",
        "What was Sarah discussing last week?",
        "What did Alex mention about work?",
        "What did someone say about the weather?",
        "How are you doing today?"
    ]
    
    print("=== RAG User Query Parsing Test ===\n")
    
    for query in test_queries:
        print(f"Query: {query}")
        
        try:
            target_user, target_user_id, time_reference = await rag_query_service.parse_user_query(query)
            
            print(f"  Target User: {target_user}")
            print(f"  Target User ID: {target_user_id}")
            print(f"  Time Reference: {time_reference} days ago")
            print(f"  Is Factual Query: {target_user_id is not None}")
            print()
            
        except Exception as e:
            print(f"  Error: {e}")
            print()

async def test_user_lookup():
    """Test user lookup functionality"""
    
    message_db = MessageDatabase()
    await message_db.initialize()
    
    print("=== User Lookup Test ===\n")
    
    # Test exact match
    test_names = ["Troels", "Magnus", "Sarah", "Alex", "NonExistentUser"]
    
    for name in test_names:
        print(f"Looking up: {name}")
        
        try:
            # Try exact match
            user = await message_db.get_user_by_display_name(name)
            if user:
                print(f"  Exact match found: {user['display_name']} (ID: {user['discord_user_id']})")
            else:
                # Try fuzzy search
                similar_users = await message_db.search_users_by_name(name)
                if similar_users:
                    print(f"  Similar users found:")
                    for user in similar_users[:3]:
                        print(f"    - {user['display_name']} (ID: {user['discord_user_id']}, Messages: {user['message_count']})")
                else:
                    print(f"  No users found")
            print()
            
        except Exception as e:
            print(f"  Error: {e}")
            print()

async def main():
    """Run all tests"""
    print("RAG User Query System Test\n")
    print("=" * 50)
    
    await test_user_query_parsing()
    await test_user_lookup()
    
    print("Test completed!")

if __name__ == "__main__":
    asyncio.run(main())
