"""Bounded newline JSON RPC over the service user's private Unix socket."""
import asyncio
import json

MAX_RESPONSE = 2 * 1024 * 1024


async def request(socket_path, payload, timeout=5):
    async with asyncio.timeout(timeout):
        reader, writer = await asyncio.open_unix_connection(socket_path, limit=MAX_RESPONSE)
        try:
            writer.write(json.dumps(payload).encode() + b"\n")
            await writer.drain()
            response = json.loads(await reader.readline())
            if "error" in response:
                raise RuntimeError(response["error"])
            return response
        finally:
            writer.close()
            await writer.wait_closed()
