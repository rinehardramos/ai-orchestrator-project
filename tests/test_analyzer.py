import asyncio
from src.genesis.analyzer.task_analyzer import TaskAnalyzer

async def main():
    analyzer = TaskAnalyzer()
    req = await analyzer.parse_statement("Research the latest advancements in quantum computing")
    print(req.model_dump())

asyncio.run(main())
