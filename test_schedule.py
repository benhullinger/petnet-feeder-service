import asyncio
import os
from feeder.database.models import get_combined_device_schedule

async def test():
    device_hid = "40a7153d12ddb536afc3a465ef33c40fbbbdfe44"
    res = await get_combined_device_schedule(device_hid)
    print(f"Charlie events: {len(res)}")
    for e in res:
        print(f" - {e.name}: {e.time} seconds since midnight (portion: {e.portion})")

if __name__ == "__main__":
    asyncio.run(test())
