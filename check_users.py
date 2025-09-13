#!/usr/bin/env python3
"""
Check users in database
"""

import asyncio
from MessageDatabase import MessageDatabase

async def check_users():
    """Check what users are in the database"""
    try:
        db = MessageDatabase()
        await db.initialize()
        
        users = await db.get_user_stats()
        print("Users in database:")
        for user in users:
            print(f"  ID: {user['discord_user_id']}, Name: {user['display_name']}, Messages: {user['message_count']}")
        
        # Also check messages
        messages = await db.get_messages_for_rag(limit=5)
        print(f"\nSample messages:")
        for msg in messages:
            print(f"  User ID: {msg['discord_user_id']}, Content: {msg['content'][:50]}...")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_users())
