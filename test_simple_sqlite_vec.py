#!/usr/bin/env python3
"""
Simple test of sqlite-vec functionality
"""
import sqlite3
import sqlite_vec
from sqlite_vec import load

def test_sqlite_vec():
    """Test basic sqlite-vec functionality"""
    print("Testing sqlite-vec...")
    
    try:
        # Create in-memory database
        db = sqlite3.connect(":memory:")
        
        # Enable extension loading
        print("Enabling extension loading...")
        db.enable_load_extension(True)
        
        # Load extension
        print("Loading extension...")
        load(db)
        
        # Test what functions are available
        print("Testing available functions...")
        try:
            cursor = db.execute("SELECT sqlite_vec_version()")
            version = cursor.fetchone()
            print(f"Version: {version[0]}")
        except Exception as e:
            print(f"sqlite_vec_version failed: {e}")
        
        # Try to list available functions
        try:
            cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            print(f"Tables: {tables}")
        except Exception as e:
            print(f"Table listing failed: {e}")
        
        # Create vector table
        print("Creating vector table...")
        db.execute("""
            CREATE VIRTUAL TABLE test_vectors USING vec0(
                embedding float[1536],
                id INTEGER
            )
        """)
        
        # Insert test vector
        print("Inserting test vector...")
        test_vector = [0.1] * 1536
        db.execute("""
            INSERT INTO test_vectors (id, embedding) VALUES (?, ?)
        """, (1, test_vector))
        
        # Query test
        print("Testing query...")
        cursor = db.execute("""
            SELECT id, distance FROM test_vectors 
            WHERE embedding MATCH ? ORDER BY distance LIMIT 5
        """, (test_vector,))
        results = cursor.fetchall()
        print(f"Query results: {results}")
        
        db.close()
        print("✅ All tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_sqlite_vec()
