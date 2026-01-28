import asyncio
import logging
import sys
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_2

# Use the same credentials as the app
local_username = "local_username"
local_password = "local_password"

async def monitor():
    client = MQTTClient()
    url = f"mqtt://{local_username}:{local_password}@localhost:1883/"
    print(f"Connecting to {url}...")
    await client.connect(url)
    await client.subscribe([("#", QOS_2)])
    print("Subscribed to #. Monitoring for 60 seconds...")
    
    try:
        while True:
            message = await asyncio.wait_for(client.deliver_message(), timeout=60)
            topic = message.publish_packet.variable_header.topic_name
            payload = message.publish_packet.payload.data.decode("utf-8", errors="replace")
            print(f"[{topic}]: {payload}")
    except asyncio.TimeoutError:
        print("Timeout reached.")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(monitor())
