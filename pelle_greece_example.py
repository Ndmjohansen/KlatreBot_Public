#!/usr/bin/env python3
"""
Pelle Greece Example - RAG User-Specific Query

This demonstrates how the RAG system handles user-specific queries
like "What does Pelle think about Greece?" with proper user resolution.
"""

import asyncio

async def demonstrate_pelle_greece_query():
    """Show how the Pelle Greece query works through the RAG system"""
    
    print("=== Pelle Greece Query Example ===\n")
    
    print("Query: 'What does Pelle think about Greece?'")
    print()
    
    print("=== Database Relationships ===")
    print("1. messages table:")
    print("   - discord_message_id: 12345")
    print("   - discord_user_id: 987654321 (Pelle's user ID)")
    print("   - content: 'I love Greece! The food is amazing and the islands are beautiful'")
    print("   - timestamp: 2024-01-15 14:30:00")
    print()
    
    print("2. users table:")
    print("   - discord_user_id: 987654321")
    print("   - display_name: 'Pelle' (set via !set_display_name)")
    print("   - message_count: 250")
    print("   - is_admin: false")
    print()
    
    print("3. message_embeddings table:")
    print("   - discord_message_id: 12345")
    print("   - embedding: [0.1, 0.2, 0.3, ...] (1536 dimensions)")
    print("   - embedding_model: 'text-embedding-3-small'")
    print()
    
    print("=== Query Processing Flow ===")
    print()
    print("1. Query Input: 'What does Pelle think about Greece?'")
    print()
    print("2. AI Parsing:")
    print("   - AI receives: 'What does Pelle think about Greece?'")
    print("   - AI receives user context: 'Pelle (ID: 987654321), Magnus (ID: 123456789), ...'")
    print("   - AI extracts: target_user='Pelle', time_days_ago=null, is_user_query=true")
    print()
    print("3. User Resolution:")
    print("   - System looks up 'Pelle' in database")
    print("   - Finds: discord_user_id = 987654321")
    print()
    print("4. Semantic Search:")
    print("   - Generates embedding for query: 'What does Pelle think about Greece?'")
    print("   - Searches message_embeddings WHERE discord_user_id = 987654321")
    print("   - Calculates cosine similarity between query and Pelle's message embeddings")
    print("   - Finds most similar messages about Greece")
    print()
    print("5. SQL Query (simplified):")
    print("   SELECT me.discord_message_id, me.embedding, m.content, u.display_name")
    print("   FROM message_embeddings me")
    print("   JOIN messages m ON me.discord_message_id = m.discord_message_id")
    print("   JOIN users u ON m.discord_user_id = u.discord_user_id")
    print("   WHERE u.discord_user_id = 987654321")
    print("   ORDER BY cosine_similarity DESC")
    print()
    print("6. Results Found:")
    print("   - Message 1: 'I love Greece! The food is amazing and the islands are beautiful' (similarity: 0.89)")
    print("   - Message 2: 'Greece has the best beaches in Europe' (similarity: 0.82)")
    print("   - Message 3: 'The Greek islands are perfect for climbing' (similarity: 0.75)")
    print()
    print("7. Context Assembly:")
    print("   MESSAGES FROM PELLE:")
    print("   2024-01-15 14:30: I love Greece! The food is amazing and the islands are beautiful")
    print("   2024-01-10 09:15: Greece has the best beaches in Europe")
    print("   2024-01-05 16:45: The Greek islands are perfect for climbing")
    print()
    print("8. GPT Response:")
    print("   'Pelle is very enthusiastic about Greece! He loves the food, finds the islands")
    print("   beautiful, thinks they have the best beaches in Europe, and even mentions")
    print("   that the Greek islands are perfect for climbing.'")
    print()
    
    print("=== Key Database Relationships ===")
    print("✅ Each message has a discord_user_id (foreign key to users table)")
    print("✅ Each embedding is linked to a message via discord_message_id")
    print("✅ User resolution: display_name → discord_user_id")
    print("✅ Semantic search: query_embedding vs user's message_embeddings")
    print("✅ Results filtered by user_id for user-specific queries")
    print()
    
    print("=== Why This Works ===")
    print("✅ User-Specific Search: Only searches Pelle's messages")
    print("✅ Semantic Understanding: Finds Greece-related content even if not exact match")
    print("✅ Display Name Resolution: Maps 'Pelle' to user ID 987654321")
    print("✅ Embedding Association: Each embedding knows its origin user")
    print("✅ Factual Response: Provides actual quotes from Pelle about Greece")
    print()
    
    print("=== Testing Commands ===")
    print("!test_user_query 'What does Pelle think about Greece?'")
    print("!gpt 'What does Pelle think about Greece?'")
    print("!find_user Pelle")
    print("!rag_search 'Greece'")

if __name__ == "__main__":
    asyncio.run(demonstrate_pelle_greece_query())
