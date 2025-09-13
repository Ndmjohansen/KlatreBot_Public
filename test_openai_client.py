#!/usr/bin/env python3
"""
Test OpenAI client initialization
"""

import asyncio
import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load .env file if it exists
load_dotenv()

async def test_openai_client():
    """Test OpenAI client initialization"""
    try:
        openai_key = os.getenv('openaikey')
        if not openai_key:
            print("❌ No OpenAI key found in environment")
            return False
        
        print(f"✅ OpenAI key found: {openai_key[:10]}...")
        
        # Test basic client creation
        client = AsyncOpenAI(api_key=openai_key)
        print("✅ AsyncOpenAI client created successfully")
        
        # Test embedding generation
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input="test message"
        )
        print(f"✅ Embedding generated: {len(response.data[0].embedding)} dimensions")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    asyncio.run(test_openai_client())
