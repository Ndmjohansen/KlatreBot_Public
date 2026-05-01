#!/usr/bin/env python3
"""
Test script to call the OpenAI Responses web_search tool using the project's AsyncOpenAI client.
It runs the same query against two models (gpt-5-mini and gpt-5-nano) and prints timing and response info.

Usage:
  Set openaikey in the environment, then:
  python tools/test_web_search_call.py

Note: this uses the openai AsyncOpenAI client; run in an environment with the project's deps.
"""
import argparse
import asyncio
import os
import time
import json
from openai import AsyncOpenAI
from openai.types.responses import Response
from dotenv import load_dotenv
import pathlib


QUERY = "!gpt Hvilke buffs i PoE 3.27 patch notes ser mest spændende ud ift. at give lidt liv til gamle builds?"


async def call_web_search(client, model, query):
    start = time.time()
    try:
        response: Response = await client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            input=query,
        )
        duration = time.time() - start
        # Extract output text
        output_text = response.output_text if hasattr(response, 'output_text') else (response.choices[0].message.content if response.choices else '')
        sources = []
        if hasattr(response, 'web_search_call') and response.web_search_call:
            try:
                sources = response.web_search_call.action.get('sources', [])
            except Exception:
                sources = []
        return {
            'model': model,
            'duration': duration,
            'output_text_preview': output_text[:400],
            'sources_count': len(sources),
            'raw_response': response
        }
    except Exception as e:
        return {'model': model, 'error': str(e), 'duration': time.time() - start}


async def call_chat_search(client, model, query):
    """Call the Chat Completions API with a specialized search model (e.g. gpt-5-search-api).
    This tests the chat-based search path which may be faster for simple lookups.
    """
    start = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": query}],
        )
        duration = time.time() - start
        output_text = resp.choices[0].message.content if resp.choices else ''
        return {
            'model': model,
            'duration': duration,
            'output_text_preview': output_text[:400],
        }
    except Exception as e:
        return {'model': model, 'error': str(e), 'duration': time.time() - start}


async def main(run_responses=True, run_chat=True, run_auto=False):
    # Attempt to load the project's .env (.env) from repo root so tests use same credentials
    script_dir = pathlib.Path(__file__).resolve().parent
    project_root = script_dir.parent
    dotenv_path = project_root / '.env'
    if dotenv_path.exists():
        load_dotenv(dotenv_path=str(dotenv_path))

    # Accept common env var names for compatibility
    api_key = os.getenv('OPENAI_API_KEY') or os.getenv('OPENAI_KEY') or os.getenv('openaikey')
    if not api_key:
        print('OPENAI_API_KEY not found in environment or .env; set it and re-run')
        return

    client = AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=0)

    if run_responses:
        # Responses API web_search (tool) path
        for model in ('gpt-4o-mini', 'gpt-4.1-mini', 'gpt-4.1-nano'):
            print(f'Calling Responses web_search with model={model}...')
            res = await call_web_search(client, model, QUERY)
            res_log = {k: v for k, v in res.items() if k != 'raw_response'}
            print(json.dumps(res_log, indent=2, default=str))

    if run_chat:
        # Chat Completions search model (specialized for search)
        for model in ('gpt-5-search-api',):
            print(f'Calling Chat Completions search with model={model}...')
            res = await call_chat_search(client, model, QUERY)
            print(json.dumps(res, indent=2, default=str))

    if run_auto:
        # Automatic tool selection: ordinary prompt, allow model to choose tools
        print('Calling Responses API with automatic tool selection (tool_choice=auto)')
        start = time.time()
        try:
            resp = await client.responses.create(
                model='gpt-5-mini',
                tool_choice='auto',
                input=QUERY,
                include=['web_search_call.action.sources']
            )
            duration = time.time() - start
            output_text = resp.output_text if hasattr(resp, 'output_text') else (resp.choices[0].message.content if resp.choices else '')
            print(json.dumps({'mode': 'auto', 'duration': duration, 'preview': output_text[:400]}, indent=2))
        except Exception as e:
            print(json.dumps({'mode': 'auto', 'error': str(e), 'duration': time.time() - start}, indent=2))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-responses', dest='responses', action='store_false', help='Skip Responses API web_search tests')
    ap.add_argument('--no-chat', dest='chat', action='store_false', help='Skip Chat Completions search tests')
    ap.add_argument('--auto', dest='auto', action='store_true', help='Run automatic tool selection test')
    ns = ap.parse_args()
    asyncio.run(main(run_responses=ns.responses, run_chat=ns.chat, run_auto=ns.auto))


