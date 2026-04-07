"""
Test to verify ChromaVectorService handles both string and numeric timestamp types.
This test addresses the bug where ChromaDB sometimes returns timestamps as strings
instead of floats, causing "'str' object cannot be interpreted as an integer" errors.
"""

import pytest
import os
import tempfile
import shutil
import datetime
from ChromaVectorService import ChromaVectorService


@pytest.mark.asyncio
async def test_chroma_handles_string_and_numeric_timestamps():
    """
    Test that ChromaVectorService.search_similar() correctly handles:
    1. Numeric timestamps (float) - the expected format
    2. Numeric string timestamps - sometimes returned by ChromaDB
    3. ISO format datetime strings - legacy data format
    """
    tmpdir = tempfile.mkdtemp(prefix="test_chroma_timestamp_")
    chroma_dir = os.path.join(tmpdir, "chroma_db")
    
    try:
        # Initialize ChromaVectorService
        chroma_service = ChromaVectorService(persist_directory=chroma_dir)
        await chroma_service.initialize()
        
        # Store a test embedding with a known timestamp
        test_message_id = 123456
        test_embedding = [0.1] * 1536  # Standard embedding size for text-embedding-3-small
        test_content = "Test message content"
        test_display_name = "TestUser"
        test_timestamp = datetime.datetime(2025, 10, 24, 12, 0, 0)
        test_message_type = "text"
        test_user_id = 999
        
        # Store the embedding
        success = await chroma_service.store_embedding(
            test_message_id,
            test_embedding,
            test_content,
            test_display_name,
            test_timestamp,
            test_message_type,
            test_user_id
        )
        assert success, "Failed to store embedding"
        
        # Search for similar messages
        query_embedding = [0.1] * 1536  # Same embedding for exact match
        results = await chroma_service.search_similar(query_embedding, limit=1)
        
        # Verify the results
        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        result = results[0]
        
        # Verify the timestamp was correctly converted from metadata
        assert isinstance(result['timestamp'], datetime.datetime), \
            f"Expected datetime.datetime, got {type(result['timestamp'])}"
        
        # Verify timestamp values match (allowing for floating point precision)
        expected_timestamp = test_timestamp.timestamp()
        actual_timestamp = result['timestamp'].timestamp()
        assert abs(expected_timestamp - actual_timestamp) < 1.0, \
            f"Timestamp mismatch: expected {expected_timestamp}, got {actual_timestamp}"
        
        # Verify other fields
        assert result['discord_message_id'] == test_message_id
        assert result['content'] == test_content
        assert result['display_name'] == test_display_name
        assert result['message_type'] == test_message_type
        
        print(f"✓ Test passed: ChromaVectorService correctly handles timestamp conversion")
        print(f"  Stored timestamp: {test_timestamp}")
        print(f"  Retrieved timestamp: {result['timestamp']}")
        
    finally:
        # Cleanup
        try:
            shutil.rmtree(tmpdir)
            print(f"Cleaned up temporary directory: {tmpdir}")
        except Exception as e:
            print(f"Warning: Failed to cleanup {tmpdir}: {e}")


@pytest.mark.asyncio
async def test_chroma_search_with_date_filters():
    """
    Test that ChromaVectorService handles date filtering correctly,
    including the conversion of date parameters that might come as strings from LLM tools.
    """
    tmpdir = tempfile.mkdtemp(prefix="test_chroma_date_filter_")
    chroma_dir = os.path.join(tmpdir, "chroma_db")
    
    try:
        # Initialize ChromaVectorService
        chroma_service = ChromaVectorService(persist_directory=chroma_dir)
        await chroma_service.initialize()
        
        # Store multiple embeddings with different timestamps
        base_embedding = [0.1] * 1536
        now = datetime.datetime.now()
        
        messages = [
            (1, now - datetime.timedelta(days=10), "Old message"),
            (2, now - datetime.timedelta(days=5), "Recent message"),
            (3, now, "Very recent message"),
        ]
        
        for msg_id, timestamp, content in messages:
            await chroma_service.store_embedding(
                msg_id, base_embedding, content, "TestUser", timestamp, "text", 999
            )
        
        # Test 1: Search with datetime start_date
        start_date = now - datetime.timedelta(days=7)
        results = await chroma_service.search_similar(
            base_embedding, 
            limit=10,
            start_date=start_date
        )
        
        # Should only get messages from last 7 days (messages 2 and 3)
        assert len(results) >= 2, f"Expected at least 2 results, got {len(results)}"
        for result in results:
            assert result['timestamp'] >= start_date, \
                f"Result timestamp {result['timestamp']} is before start_date {start_date}"
        
        # Test 2: Search with ISO string start_date (simulating LLM tool call)
        start_date_str = start_date.isoformat()
        results_str = await chroma_service.search_similar(
            base_embedding, 
            limit=10,
            start_date=start_date_str
        )
        
        # Should get same results as datetime version
        assert len(results_str) >= 2, f"Expected at least 2 results with string date, got {len(results_str)}"
        
        print(f"✓ Test passed: ChromaVectorService correctly handles date filters")
        print(f"  Messages stored: {len(messages)}")
        print(f"  Results with datetime filter: {len(results)}")
        print(f"  Results with string filter: {len(results_str)}")
        
    finally:
        # Cleanup
        try:
            shutil.rmtree(tmpdir)
            print(f"Cleaned up temporary directory: {tmpdir}")
        except Exception as e:
            print(f"Warning: Failed to cleanup {tmpdir}: {e}")


@pytest.mark.asyncio
async def test_chroma_handles_iso_format_timestamps():
    """
    Test that ChromaVectorService correctly handles ISO format datetime strings
    that might exist in legacy data stored in ChromaDB.
    """
    tmpdir = tempfile.mkdtemp(prefix="test_chroma_iso_timestamp_")
    chroma_dir = os.path.join(tmpdir, "chroma_db")
    
    try:
        # Initialize ChromaVectorService
        chroma_service = ChromaVectorService(persist_directory=chroma_dir)
        await chroma_service.initialize()
        
        # Manually insert a document with ISO format timestamp in metadata
        # This simulates legacy data that might exist in the database
        test_embedding = [0.2] * 1536
        test_content = "Legacy message with ISO timestamp"
        
        # Store with ISO format timestamp directly in ChromaDB
        # (bypassing the normal store_embedding method to simulate legacy data)
        doc_id = "999999"
        iso_timestamp = "2025-10-23T17:25:08.129000+00:00"
        
        chroma_service.collection.add(
            ids=[doc_id],
            embeddings=[test_embedding],
            metadatas=[{
                "discord_message_id": 999999,
                "discord_user_id": 888,
                "display_name": "LegacyUser",
                "timestamp": iso_timestamp,  # ISO format string
                "message_type": "text",
                "content": test_content[:1000]
            }],
            documents=[test_content]
        )
        
        print(f"Stored legacy data with ISO timestamp: {iso_timestamp}")
        
        # Now search for it - this should not crash even with ISO format timestamp
        query_embedding = [0.2] * 1536
        results = await chroma_service.search_similar(query_embedding, limit=5)
        
        # Verify we got results and they have proper datetime objects
        assert len(results) > 0, "Expected at least one result"
        
        legacy_result = [r for r in results if r['discord_message_id'] == 999999]
        assert len(legacy_result) == 1, "Expected to find the legacy message"
        
        result = legacy_result[0]
        assert isinstance(result['timestamp'], datetime.datetime), \
            f"Expected datetime.datetime, got {type(result['timestamp'])}"
        
        # Verify the timestamp was correctly parsed
        expected_dt = datetime.datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        assert abs((result['timestamp'] - expected_dt).total_seconds()) < 1.0, \
            f"Timestamp mismatch: expected {expected_dt}, got {result['timestamp']}"
        
        print(f"✓ Test passed: ChromaVectorService correctly handles ISO format timestamps")
        print(f"  Stored ISO timestamp: {iso_timestamp}")
        print(f"  Retrieved timestamp: {result['timestamp']}")
        print(f"  Content: {result['content']}")
        
    finally:
        # Cleanup
        try:
            shutil.rmtree(tmpdir)
            print(f"Cleaned up temporary directory: {tmpdir}")
        except Exception as e:
            print(f"Warning: Failed to cleanup {tmpdir}: {e}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_chroma_handles_string_and_numeric_timestamps())
    asyncio.run(test_chroma_search_with_date_filters())
    asyncio.run(test_chroma_handles_iso_format_timestamps())

