import asyncio
import json
import logging
import random
import re
import string
import time
from typing import List

import semver
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_1, QOS_2

from feeder.database.models import (
    KronosDevices,
    DeviceTelemetryData,
    FeedingResult,
    FeedingSchedule,
)
from feeder.util.mqtt.authentication import local_username, local_password

logger = logging.getLogger(__name__)

# Client configuration with longer keepalive to prevent disconnects
CLIENT_CONFIG = {
    'keep_alive': 60,  # Send ping every 60s instead of default 10s
    'ping_delay': 5,   # Allow 5s delay before keepalive timeout
    'auto_reconnect': True,
    'reconnect_max_interval': 30,
    'reconnect_retries': -1,  # Infinite retries
}


def generate_task_id():
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(32))


def build_command(device_id, command, args):
    payload = json.dumps(args)
    msg = {
        "hid": generate_task_id(),
        "name": "SendCommand",
        "encrypted": False,
        "parameters": {
            "deviceHid": device_id,
            "command": command,
            "payload": payload,
        },
    }
    return json.dumps(msg).encode("utf-8")


async def commit_telemetry_data(gateway_id: str, payload: dict):
    device_id = payload["_|deviceHid"]
    message_type = payload["s|msg_type"]
    if message_type == "hb":
        logger.debug("Sending ping for %s", device_id)
        await KronosDevices.ping(gateway_hid=gateway_id, device_hid=device_id)
    if message_type == "sensor":
        logger.debug("Updating sensor information for %s", device_id)
        await DeviceTelemetryData.report(
            gateway_hid=gateway_id,
            device_hid=device_id,
            voltage=payload["f|voltage"] / 1000,
            usb_power=bool(payload["i|usb"]),
            charging=bool(payload["i|chg"]),
            ir=bool(payload["i|ir"]),
            rssi=payload["i|rssi"],
        )
    if message_type == "feed_result":
        logger.info("Committing feed result data for %s", device_id)
        await FeedingResult.report(
            device_hid=device_id,
            start_time=payload.get("i|stime"),
            end_time=payload.get("i|etime"),
            pour=payload.get("i|pour"),
            full=payload.get("i|full"),
            grams_expected=payload.get("f|e_g"),
            grams_actual=payload.get("f|a_g"),
            hopper_start=payload.get("f|h_s"),
            hopper_end=payload.get("f|h_e"),
            source=payload.get("i|src"),
            fail=payload.get("b|fail"),
            trip=payload.get("b|trip"),
            lrg=payload.get("b|lrg"),
            vol=payload.get("b|vol"),
            bowl=payload.get("b|bowl"),
            recipe_id=payload.get("s|rid"),
            error=payload.get("s|err"),
        )


class FeederClient(MQTTClient):
    api_regex = re.compile(r"^krs\.api\.gts\.(?P<gateway_id>.*)$")
    telemetry_regex = re.compile(r"^krs\.tel\.gts\.(?P<gateway_id>.*)$")

    def __init__(self):
        super().__init__(config=CLIENT_CONFIG)
        self._pending_tasks: set = set()

    async def _process_message_async(self, packet):
        """Process message in background without blocking MQTT client."""
        try:
            await self.handle_message(packet)
        except Exception:
            logger.exception("Error processing MQTT message")

    def _schedule_message_processing(self, packet):
        """Schedule message processing without blocking the MQTT loop."""
        task = asyncio.create_task(self._process_message_async(packet))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def handle_message(self, packet):
        api_result = self.api_regex.match(packet.variable_header.topic_name)
        telemetry_result = self.telemetry_regex.match(packet.variable_header.topic_name)
        if api_result:
            gateway_id = api_result.groupdict()["gateway_id"]
            try:
                payload = json.loads(packet.payload.data)
            except UnicodeDecodeError:
                logger.exception("Failed to decode message: %s", packet.payload.data)
                return
            request_id = payload["requestId"]
            await self.create_request_ack(gateway_id, request_id)
        elif telemetry_result:
            gateway_id = telemetry_result.groupdict()["gateway_id"]
            try:
                payload = json.loads(packet.payload.data)
            except UnicodeDecodeError:
                logger.exception("Failed to decode message: %s", packet.payload.data)
                return
            await commit_telemetry_data(gateway_id, payload)
        else:
            logger.info(
                "Unknown message: %s => %s",
                packet.variable_header.topic_name,
                packet.payload.data,
            )

    async def create_request_ack(self, gateway_id, request_id):
        reply = {
            "requestId": request_id,
            "eventName": "GatewayToServer_ApiRequest",
            "encrypted": False,
            "parameters": {"status": "OK"},
        }
        logger.debug("Publishing MQTT ACK: %s", reply)
        await self.publish(
            f"krs/api/stg/{gateway_id}", json.dumps(reply).encode("utf-8"), qos=QOS_2
        )

    async def send_cmd(self, gateway_id, device_id, command, args):
        packet = build_command(device_id, command, args)
        await self.publish(f"krs/cmd/stg/{gateway_id}", packet, qos=QOS_2)

    async def send_cmd_feed(self, gateway_id, device_id, portion=0.0625):
        await self.send_cmd(gateway_id, device_id, "feed", {"portion": portion})

    async def send_cmd_button(self, gateway_id, device_id, enable=True):
        await self.send_cmd(
            gateway_id, device_id, "button_enable_remote", {"enable": enable}
        )

    async def send_cmd_reboot(self, gateway_id, device_id):
        await self.send_cmd(gateway_id, device_id, "reboot", {})

    async def send_cmd_utc_offset(self, gateway_id, device_id, utc_offset=0):
        await self.send_cmd(
            gateway_id, device_id, "utc_offset", {"utc_offset": utc_offset}
        )

    async def send_cmd_budget(
        self,
        gateway_id,
        device_id,
        recipe_id,
        tbsp_per_feeding,
        g_per_tbsp,
        budget_tbsp,
    ):
        # The feeder seems to get unhappy if the recipe ID isn't 7-8 chars long and
        # in r"[a-z]{1,2}[0-9]{6,7}" format. Whatever.
        await self.send_cmd(
            gateway_id,
            device_id,
            "budget",
            {
                "recipe": f"E{str(recipe_id).zfill(7)}",
                "tbsp_per_feeding": tbsp_per_feeding,
                "g_per_tbsp": g_per_tbsp,
                "budget_tbsp": budget_tbsp,
            },
        )

    async def send_cmd_schedule(
        self, gateway_id, device_id, events: List[FeedingSchedule]
    ):
        # We are going to default to the old API version because the
        # older firmwares aren't great at consistently reporting their
        # version info. We can assume is a feeder doesn't have a version,
        # it is using the legacy scheduling API.
        software_version = "2.3.2"
        results = await KronosDevices.get(device_hid=device_id)
        device = results[0]
        if device.softwareVersion is not None:
            logger.debug("Setting softwareVersion to %s", device.softwareVersion)
            software_version = device.softwareVersion

        schedule_array = [
            {
                "active": event.enabled,
                "automatic": True,
                "feeding_id": (
                    f"{device_id[:16]}_feed{event.event_id}_"
                    f"{int(event.time / 3600)}:{str(int(event.time / 60 % 60)).zfill(2)}"
                    f"{'AM' if event.time / 3600 < 12 else 'PM'}"
                ),
                "name": f"FEED{index}",
                "portion": event.portion,
                "reminder": True,
                "time": event.time,
            }
            for index, event in enumerate(events)
        ]

        # TODO: Actually figure out when they implemented the newer scheduling API...
        # We know >=2.7 uses the new API and that 2.3.2 uses the legacy API.
        # Assuming 2.5.X because that is smack dab in between 3 and 7.
        if semver.VersionInfo.parse("2.5.0").compare(software_version) == 1:
            # If we are running on 2.4.0 or lower, use the legacy scheduling API
            await self.send_cmd(gateway_id, device_id, "schedule", schedule_array)
        else:
            # If we are running 2.5.0 or higher, use the new API.
            # TODO: We could probably be smarter about how we are handling events and
            # TODO: actually take advantage of the new API. For now, this should work.
            await self.send_cmd(gateway_id, device_id, "schedule_clear", {})
            await self.send_cmd(
                gateway_id,
                device_id,
                "schedule_mod_start",
                {"size": len(schedule_array)},
            )
            await self.send_cmd(
                gateway_id,
                device_id,
                "schedule_add",
                [
                    {"index": index, "data": event}
                    for index, event in enumerate(schedule_array)
                ],
            )
            await self.send_cmd(gateway_id, device_id, "schedule_mod_end", {})

    async def start(self):
        while True:
            try:
                await self.connect(f"mqtt://{local_username}:{local_password}@localhost:1883/")
                # Use QOS_1 for subscriptions - QOS_2's 4-way handshake can stall with high msg volume
                await self.subscribe([("#", QOS_1)])
                logger.info("MQTT client connected and subscribed")
                
                last_message_time = time.time()
                consecutive_timeouts = 0
                
                while True:
                    try:
                        # Use timeout to detect stalls - allows keepalive pings to work
                        message = await asyncio.wait_for(
                            self.deliver_message(), 
                            timeout=60  # Check every 60s
                        )
                        packet = message.publish_packet
                        # Process message asynchronously to avoid blocking MQTT protocol
                        self._schedule_message_processing(packet)
                        last_message_time = time.time()
                        consecutive_timeouts = 0
                    except asyncio.TimeoutError:
                        consecutive_timeouts += 1
                        time_since_message = time.time() - last_message_time
                        
                        # If no message in 5 minutes, connection is likely dead
                        if time_since_message > 300:
                            logger.warning(
                                "No MQTT messages received in %.0f seconds, forcing reconnect",
                                time_since_message
                            )
                            # Force disconnect and break to outer loop for reconnect
                            try:
                                await self.disconnect()
                            except Exception:
                                pass
                            break
                        
                        if consecutive_timeouts % 3 == 0:
                            logger.debug(
                                "MQTT client: %d consecutive timeouts, %.0fs since last message",
                                consecutive_timeouts, time_since_message
                            )
                        continue

            except Exception as err:  # pylint: disable=broad-except
                logger.exception("MQTT client error, reconnecting in 5s: %s", err)
                await asyncio.sleep(5)
