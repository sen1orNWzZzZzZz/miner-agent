import asyncio
import json
from langchain_mcp_adapters.client import MultiServerMCPClient


async def main():
    client = MultiServerMCPClient({
        "news": {"transport": "sse", "url": "http://news-mcp:8000/sse"},
        "pdf": {"transport": "sse", "url": "http://pdf-mcp:8001/sse"},
        "price": {"transport": "sse", "url": "http://price-mcp:8002/sse"},
    })
    tools = await client.get_tools()
    print("Tools:", [t.name for t in tools])

    for tool in tools:
        print(f"\n=== {tool.name} ===")
        if tool.name == "search":
            result = await tool.ainvoke({"query": "Pilbara lithium", "days": 7})
        elif tool.name == "fetch_article":
            result = await tool.ainvoke({"url": "https://example.com"})
        elif tool.name == "extract_resources":
            result = await tool.ainvoke({"pdf_url": "https://example.com/report.pdf"})
        elif tool.name == "get_price":
            result = await tool.ainvoke({"commodity": "lithium"})
        elif tool.name == "get_trend":
            result = await tool.ainvoke({"commodity": "lithium", "days": 7})
        else:
            continue
        print(json.dumps(result, ensure_ascii=False, indent=2)[:800])

    await client.close()


asyncio.run(main())
