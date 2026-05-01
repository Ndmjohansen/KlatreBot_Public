import pytest
import os
import tempfile
import shutil
import datetime
import sys
from MCPToolManager import MCPToolManager
from MessageDatabase import MessageDatabase
from ChromaVectorService import ChromaVectorService
from RAGEmbeddingService import RAGEmbeddingService
from RAGQueryService import RAGQueryService

def echo(msg: str):
    try:
        # Write directly to the original stdout to bypass pytest capture when possible
        sys.__stdout__.write(msg + "\n")
    except Exception:
        # Fallback to regular print if direct write fails
        print(msg)

@pytest.mark.asyncio
async def _prepare_db_and_mgr():
    """
    Helper to prepare a MessageDatabase, deterministic embeddings and an MCPToolManager.
    Returns (md, mgr, tmpdir) where tmpdir should be removed by the caller.
    """
    tmpdir = tempfile.mkdtemp(prefix="test_tools_")
    tmpdb = os.path.join(tmpdir, "test_klatrebot.db")
    chroma_dir = os.path.join(tmpdir, "chroma_db")

    md = MessageDatabase(db_path=tmpdb)
    md.chroma_service = ChromaVectorService(persist_directory=chroma_dir)
    await md.initialize()

    # Insert a user and messages covering climbing-related and unrelated content
    await md.upsert_user(1001, "TestUser")
    now = datetime.datetime.now(datetime.timezone.utc)
    msgs = [
        ("Just went bouldering at the gym today, so pumped!", now),
        ("Random unrelated message", now - datetime.timedelta(minutes=5)),
        ("Anyone wants beta for that V3? I tried some crimps.", now - datetime.timedelta(minutes=10)),
    ]
    for i, (text, ts) in enumerate(msgs, start=1):
        await md.log_message(i, 1, 1001, text, timestamp=ts)

    # Deterministic embeddings
    emb1 = [0.1] * 8
    emb2 = [0.5] * 8
    emb3 = [0.11] * 8
    await md.store_message_embedding(1, emb1)
    await md.store_message_embedding(2, emb2)
    await md.store_message_embedding(3, emb3)

    # Embedding service stub
    emb_service = RAGEmbeddingService(None, md)
    async def fake_generate_embedding(text: str):
        txt = text.lower()
        if any(k in txt for k in ("boulder", "bouldering", "v3", "beta", "climb")):
            return [0.1] * 8
        return [0.5] * 8
    emb_service.generate_embedding = fake_generate_embedding

    rag = RAGQueryService(md, emb_service)
    mgr = MCPToolManager(rag)
    return md, mgr, tmpdir

@pytest.mark.asyncio
async def test_rag_search_returns_results_verbose():
    md, mgr, tmpdir = await _prepare_db_and_mgr()
    echo(f"[TEST] tempdir: {tmpdir}")
    try:
        echo("[TEST] Calling rag_search(topic='climbing', limit=5)")
        res = await mgr.call_tool("rag_search", {"topic": "climbing", "limit": 5})
        echo(f"[TEST] rag_search -> {res}")
        assert res["success"] is True
        assert res["tool"] == "rag_search"
        assert isinstance(res["output"], dict)
        assert res["output"].get("topic") == "climbing"
        results = res["output"].get("results")
        assert isinstance(results, list)
        assert len(results) > 0
        # Print a brief summary of the top results
        for i, r in enumerate(results[:5], start=1):
            echo(f"  result[{i}] id={r.get('id')} display_name={r.get('display_name')!r} content_preview={ (r.get('content') or '')[:120]!r }")
    finally:
        try:
            shutil.rmtree(tmpdir)
            echo(f"[TEST] Cleaned up tempdir: {tmpdir}")
        except Exception:
            pass

@pytest.mark.asyncio
async def test_find_relevant_context_returns_list_verbose():
    md, mgr, tmpdir = await _prepare_db_and_mgr()
    echo(f"[TEST] tempdir: {tmpdir}")
    try:
        payload = {"query": "who mentioned climbing", "user_id": None, "limit": 3}
        echo(f"[TEST] Calling find_relevant_context with {payload}")
        res = await mgr.call_tool("find_relevant_context", payload)
        echo(f"[TEST] find_relevant_context -> {res}")
        assert res["success"] is True
        results = res["output"].get("results")
        assert isinstance(results, list)
        assert len(results) > 0
        for i, r in enumerate(results, start=1):
            echo(f"  ctx[{i}] source={r.get('source')} snippet={ (r.get('content') or '')[:140]!r }")
    finally:
        try:
            shutil.rmtree(tmpdir)
            echo(f"[TEST] Cleaned up tempdir: {tmpdir}")
        except Exception:
            pass

@pytest.mark.asyncio
async def test_user_messages_filters_and_returns_user_items_verbose():
    md, mgr, tmpdir = await _prepare_db_and_mgr()
    echo(f"[TEST] tempdir: {tmpdir}")
    try:
        payload = {"query": "climb", "target_user_id": 1001}
        echo(f"[TEST] Calling user_messages with {payload}")
        res = await mgr.call_tool("user_messages", payload)
        echo(f"[TEST] user_messages -> {res}")
        assert res["success"] is True
        assert res["output"].get("target_user_id") == 1001
        results = res["output"].get("results")
        assert isinstance(results, list)
        assert len(results) > 0
        for i, r in enumerate(results, start=1):
            echo(f"  msg[{i}] id={r.get('id')} display_name={r.get('display_name')!r} content_preview={ (r.get('content') or '')[:140]!r }")
    finally:
        try:
            shutil.rmtree(tmpdir)
            echo(f"[TEST] Cleaned up tempdir: {tmpdir}")
        except Exception:
            pass

@pytest.mark.asyncio
async def test_conversation_summary_produces_summary_string_verbose():
    md, mgr, tmpdir = await _prepare_db_and_mgr()
    echo(f"[TEST] tempdir: {tmpdir}")
    try:
        payload = {"user_id": 1001, "days": 7}
        echo(f"[TEST] Calling conversation_summary with {payload}")
        res = await mgr.call_tool("conversation_summary", payload)
        echo(f"[TEST] conversation_summary -> {res}")
        assert res["success"] is True
        assert "summary" in res["output"]
        assert isinstance(res["output"]["summary"], str)
        assert len(res["output"]["summary"].strip()) > 0
        echo(f"[TEST] Summary (truncated): {res['output']['summary'][:300]!r}")
    finally:
        try:
            shutil.rmtree(tmpdir)
            echo(f"[TEST] Cleaned up tempdir: {tmpdir}")
        except Exception:
            pass
