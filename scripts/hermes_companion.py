"""
Hermes Companion — local browser-automation runner for arbitrary tasks.

Runs on YOUR machine, drives YOUR already-logged-in Chrome via the Chrome
DevTools Protocol. Nothing here ever sends your dashboard sessions or
credentials to the Social Optimize server — the task instructions come
from Hermes (in-app chat), but the browser, the login state, and the
Anthropic API call all stay local.

STEP 1 — Launch Chrome with remote debugging (close Chrome first):

  Windows:
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\\ChromeDebug

  Mac:
    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

  Linux:
    google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

STEP 2 — Log into whatever dashboard the task needs (Supabase, Render,
         Stripe, Google Cloud, etc.) in that Chrome window.

STEP 3 — Run with a task description:

    python hermes_companion.py --task "Go to the Supabase project settings,
    Database page, and copy the exact connection pooler hostname shown
    under 'Connection string' for Transaction mode."

    Or pass a task file:
    python hermes_companion.py --task-file task.txt

Set ANTHROPIC_API_KEY in your environment first.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CDP_URL = os.getenv("CDP_URL", "http://localhost:9222")


def check_cdp() -> bool:
    try:
        resp = requests.get(f"{CDP_URL}/json/version", timeout=3)
        info = resp.json()
        print(f"[OK] Connected to Chrome: {info.get('Browser', 'unknown')}")
        return True
    except Exception:
        return False


async def run_task(task: str) -> str:
    try:
        from browser_use import Agent, Browser, BrowserConfig
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        print("Missing dependencies. Run:")
        print("  pip install browser-use langchain-anthropic")
        sys.exit(1)

    if not ANTHROPIC_API_KEY:
        print("[!] Set ANTHROPIC_API_KEY env var first.")
        sys.exit(1)

    if not check_cdp():
        print("\n[!] Chrome is not open with remote debugging.")
        print("See the instructions at the top of this script for the launch command.")
        sys.exit(1)

    llm = ChatAnthropic(model="claude-opus-4-8", api_key=ANTHROPIC_API_KEY)
    browser = Browser(config=BrowserConfig(cdp_url=CDP_URL))

    print("=" * 60)
    print("  HERMES COMPANION")
    print(f"  Task: {task[:200]}{'...' if len(task) > 200 else ''}")
    print("=" * 60)

    try:
        agent = Agent(task=task.strip(), llm=llm, browser=browser)
        result = await agent.run()
        value = str(result).strip()
        print("\n[RESULT]")
        print(value)
        return value
    finally:
        await browser.close()


def main():
    parser = argparse.ArgumentParser(description="Hermes Companion — run a browser task locally")
    parser.add_argument("--task", help="Natural-language task description")
    parser.add_argument("--task-file", help="Path to a file containing the task description")
    args = parser.parse_args()

    if args.task_file:
        task = open(args.task_file).read()
    elif args.task:
        task = args.task
    else:
        parser.error("Provide --task or --task-file")
        return

    asyncio.run(run_task(task))


if __name__ == "__main__":
    main()
