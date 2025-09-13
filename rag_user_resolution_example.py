#!/usr/bin/env python3
"""
RAG User Resolution Example

This demonstrates how the AI-powered user name resolution works
for various query patterns.
"""

import asyncio
import json

# Mock example of how the AI parsing works
async def demonstrate_ai_parsing():
    """Show how AI parses different query types"""
    
    examples = [
        {
            "query": "What did Troels talk about 5 days ago, something with fish?",
            "available_users": ["Troels", "Magnus", "Sarah", "Alex", "Nicklas"],
            "expected_ai_response": {
                "target_user": "Troels",
                "time_days_ago": 5,
                "is_user_query": True
            }
        },
        {
            "query": "What was Magnus discussing yesterday about climbing?",
            "available_users": ["Troels", "Magnus", "Sarah", "Alex", "Nicklas"],
            "expected_ai_response": {
                "target_user": "Magnus", 
                "time_days_ago": 1,
                "is_user_query": True
            }
        },
        {
            "query": "Sarah mentioned something about work last week",
            "available_users": ["Troels", "Magnus", "Sarah", "Alex", "Nicklas"],
            "expected_ai_response": {
                "target_user": "Sarah",
                "time_days_ago": 7,
                "is_user_query": True
            }
        },
        {
            "query": "How are you doing today?",
            "available_users": ["Troels", "Magnus", "Sarah", "Alex", "Nicklas"],
            "expected_ai_response": {
                "target_user": None,
                "time_days_ago": None,
                "is_user_query": False
            }
        },
        {
            "query": "What did Alex say about the weather 3 days ago?",
            "available_users": ["Troels", "Magnus", "Sarah", "Alex", "Nicklas"],
            "expected_ai_response": {
                "target_user": "Alex",
                "time_days_ago": 3,
                "is_user_query": True
            }
        }
    ]
    
    print("=== AI-Powered User Query Parsing Examples ===\n")
    
    for i, example in enumerate(examples, 1):
        print(f"Example {i}:")
        print(f"Query: '{example['query']}'")
        print(f"Available users: {example['available_users']}")
        print(f"Expected AI response: {json.dumps(example['expected_ai_response'], indent=2)}")
        print()
    
    print("=== How This Works ===")
    print("1. Query comes in: 'What did Troels talk about 5 days ago, something with fish?'")
    print("2. AI receives query + list of available users")
    print("3. AI extracts: target_user='Troels', time_days_ago=5, is_user_query=true")
    print("4. System looks up Troels' user ID in database")
    print("5. System searches Troels' messages from 5 days ago")
    print("6. System finds messages about fish using semantic search")
    print("7. System provides factual response about Troels' fish discussion")
    print()
    print("=== Benefits of AI Approach ===")
    print("✅ Handles natural language variations")
    print("✅ Works with nicknames and partial names")
    print("✅ Understands context and intent")
    print("✅ Robust to typos and different phrasings")
    print("✅ Can be extended to handle more complex queries")

if __name__ == "__main__":
    asyncio.run(demonstrate_ai_parsing())
