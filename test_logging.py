#!/usr/bin/env python3
"""
Test script to verify logging configuration works with journalctl
"""

import logging
import sys
import time

# Configure logging for journalctl
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)  # Send to stderr for journalctl
    ]
)

logger = logging.getLogger(__name__)

def test_logging():
    logger.info("Testing logging configuration...")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.debug("This debug message should not appear (level is INFO)")
    
    # Test LLM-style logging
    start_time = time.time()
    time.sleep(0.1)  # Simulate processing
    end_time = time.time()
    
    logger.info(f"Simulated LLM request took {end_time - start_time:.2f}s")
    logger.info("Logging test completed successfully")

if __name__ == "__main__":
    test_logging()
