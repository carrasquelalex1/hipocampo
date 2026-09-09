#!/usr/bin/env python3
"""CLI para ejecutar review_trade_knowledge desde systemd timer."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(sys.path[0])

from hipocampo_mcp_server import review_trade_knowledge
import asyncio


async def main():
    result = await review_trade_knowledge(dry_run=True)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
