import asyncio
from temporalio.client import Client

async def main():
    try:
        c = await Client.connect("localhost:7233")
        res = await c.count_workflows('ExecutionStatus="Failed"')
        print("Failed count:", res.count)
        res2 = await c.count_workflows('ExecutionStatus="Running"')
        print("Active count:", res2.count)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
