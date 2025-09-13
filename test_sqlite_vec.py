#!/usr/bin/env python3
"""
Test script to debug sqlite-vec extension loading
"""
import asyncio
import aiosqlite
import sqlite_vec

async def test_extension_loading():
    """Test different ways to load sqlite-vec extension"""
    print("Testing sqlite-vec extension loading...")
    
    try:
        # Test 1: Direct connection with sqlite-vec
        print("\n1. Testing direct connection...")
        async with aiosqlite.connect(":memory:") as db:
            # Try to load extension
            try:
                await db.execute("SELECT load_extension('sqlite-vec')")
                print("✅ Extension loaded with load_extension")
            except Exception as e:
                print(f"❌ load_extension failed: {e}")
            
            # Try to call sqlite_vec_version
            try:
                cursor = await db.execute("SELECT sqlite_vec_version()")
                result = await cursor.fetchone()
                print(f"✅ sqlite_vec_version(): {result[0]}")
            except Exception as e:
                print(f"❌ sqlite_vec_version failed: {e}")
    
    except Exception as e:
        print(f"❌ Connection failed: {e}")
    
    try:
        # Test 2: Using sqlite-vec Python API
        print("\n2. Testing Python API...")
        import sqlite_vec
        print(f"✅ sqlite-vec version: {sqlite_vec.__version__}")
        
        # Try to create a vector table
        async with aiosqlite.connect(":memory:") as db:
            await db.execute("""
                CREATE VIRTUAL TABLE test_vectors USING vec0(
                    embedding float[1536],
                    id INTEGER
                )
            """)
            print("✅ Vector table created successfully")
            
            # Try to insert a test vector
            test_vector = [0.1] * 1536
            await db.execute("""
                INSERT INTO test_vectors (id, embedding) VALUES (?, ?)
            """, (1, test_vector))
            print("✅ Vector inserted successfully")
            
            # Try to query
            cursor = await db.execute("""
                SELECT id, distance FROM test_vectors 
                WHERE embedding MATCH ? ORDER BY distance LIMIT 5
            """, (test_vector,))
            results = await cursor.fetchall()
            print(f"✅ Vector query successful: {len(results)} results")
            
    except Exception as e:
        print(f"❌ Python API test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_extension_loading())
