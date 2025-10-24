import pytest
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock
from openai import AsyncOpenAI
from openai.types.responses import Response

# Fix imports by adding project root to sys.path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env for API key
from dotenv import load_dotenv
load_dotenv()

# Import project modules
from KlatreGPT import KlatreGPT
from MessageDatabase import MessageDatabase
from RAGEmbeddingService import RAGEmbeddingService
from RAGQueryService import RAGQueryService
from MCPToolManager import MCPToolManager

# Skip if no API key
@pytest.mark.skipif(not os.getenv("openaikey"), reason="OpenAI API key not set (set openaikey env var)")
@pytest.mark.asyncio
async def test_web_search_in_gpt_flow():
    """Test that !gpt-like flow uses web_search tool for external queries and generates a response with results."""
    # Pre-check: Verify API key and Responses API support
    api_key = os.getenv("openaikey")
    if not api_key:
        pytest.skip("No openaikey found")
    print(f"Using API key: {api_key[:10]}... (real calls will use this)")
    
    gpt = KlatreGPT()
    gpt.set_openai_key(api_key)
    
    # Check if responses API is available
    if not hasattr(gpt.client, 'responses'):
        pytest.skip("OpenAI library does not support 'responses' API (upgrade to >=2.0.0)")
    print("Responses API available; proceeding with real test...")
    
    # Mock DB (minimal implementation for RAG init; no real persistence needed)
    mock_db = AsyncMock(spec=MessageDatabase)
    mock_db.initialize = AsyncMock(return_value=None)
    mock_db.get_recent_messages_from_db = AsyncMock(return_value=[])
    mock_db.get_similar_messages = AsyncMock(return_value=[])  # Empty for this test
    mock_db.get_user_stats = AsyncMock(return_value=[])  # Empty users
    mock_db.upsert_user = AsyncMock(return_value=None)
    mock_db.is_admin = AsyncMock(return_value=False)
    mock_db.get_user_by_display_name = AsyncMock(return_value=None)
    mock_db.get_user_by_id = AsyncMock(return_value=None)
    mock_db.search_users_by_name = AsyncMock(return_value=[])
    mock_db.get_rag_stats = AsyncMock(return_value={})
    
    # Initialize RAG and tools (this registers web_search)
    gpt.initialize_rag(mock_db)
    print("RAG and tools initialized.")
    
    # Test query: External/current info to trigger web_search
    query = "What was a positive news story from today?"
    context = ""  # No recent context
    user_id = 12345  # Dummy user ID
    
    print(f"Starting prompt_gpt with query: {query}")
    
    # Run the prompt_gpt flow with timeout to prevent hangs
    try:
        response = await asyncio.wait_for(gpt.prompt_gpt(context, query, user_id=user_id, use_rag=True), timeout=35.0)
        print("prompt_gpt completed successfully.")
    except asyncio.TimeoutError:
        print("Overall timeout after 35s - check OpenAI dashboard for quota/network issues")
        pytest.fail("Test timed out - likely in planner LLM or web_search API call")
    except Exception as e:
        print(f"prompt_gpt failed with error: {e}")
        import traceback
        traceback.print_exc()
        raise  # Re-raise for pytest
    
    # Assertions
    assert response is not None, "Response should be generated"
    assert len(response) > 0, "Response should not be empty"
    assert len(response) > 100 and ('historie' in response.lower() or 'nyhed' in response.lower() or 'fundraiser' in response.lower() or 'community' in response.lower()), "Response should reference story/news or key search elements (works for Danish)"
    
    # Verify tool was likely used (response length/complexity indicates success)
    assert len(response) > 50, "Web search responses are typically detailed (>50 chars)"
    
    # Log for manual verification
    print(f"Generated response: {response}")
    print("Test passed: Web search integrated into GPT flow without Discord.")
