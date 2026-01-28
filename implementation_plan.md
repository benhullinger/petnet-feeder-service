# Implementation Plan - Reliability and Sync Fixes

This plan addresses missed meal dispensations and system-level connection hangs by improving schedule synchronization logic and refactoring the MQTT message handling model.

## Proposed Changes

### Core MQTT Stability

#### [MODIFY] [client.py](file:///Users/ben.hullinger/Documents/petnet-feeder-service/feeder/util/mqtt/client.py)

- **Asynchronous Message Processing**: Refactor the `deliver_message` loop to use `asyncio.create_task` for `handle_message`. This prevents long-running tasks (like database queries or schedule syncs) from blocking the delivery of subsequent heartbeats or telemetry.
- **QOS Optimization**: Downgrade communication from `QOS_2` (Exactly Once) to `QOS_1` (At Least Once) for commands and ACKs. This reduces handshake overhead and prevents deadlocks on unstable connections.
- **Improved Schedule Sync**:
  - Trigger a full schedule sync when receiving a `hash` message with an empty `local_md5`.
  - For firmware 2.5.0+, send `schedule_add` commands as a list of individual events to ensure compatibility.
- **Error Handling**: Wrap message handling in `try/except` blocks to ensure individual message failures do not disrupt the entire connection loop.

---

### API and Device Synchronization

#### [MODIFY] [main.py](file:///Users/ben.hullinger/Documents/petnet-feeder-service/feeder/main.py)

- Ensure the `kronos` router is properly initialized with the `FeederClient` instance.

#### [MODIFY] [kronos.py](file:///Users/ben.hullinger/Documents/petnet-feeder-service/feeder/api/routers/kronos.py)

- Update `gateway_checkin` to automatically trigger a schedule synchronization for all associated devices when a gateway checks in or re-connects.

#### [MODIFY] [pet.py](file:///Users/ben.hullinger/Documents/petnet-feeder-service/feeder/api/routers/pet.py)

- Update the schedule display logic to query recent `feed_event` records.
- Compare actual dispense times against scheduled times to accurately reflect "Dispensed" status in the UI.

---

### Database and Utilities

#### [MODIFY] [models.py](file:///Users/ben.hullinger/Documents/petnet-feeder-service/feeder/database/models.py)

- Extract `get_combined_device_schedule` into `models.py` or a dedicated synchronization utility to avoid circular dependencies between API routers.

## Verification Plan

### Automated Verification

- **Log Monitoring**: Verify that "MQTT Client connected" appears after restarts.
- **Telemetry Check**: Confirm `lastPingedAt` updates in real-time when heartbeats are received.

### Manual Verification

1. **Trigger Manual Check-in**: Use `curl` to hit the `/checkin` endpoint and verify in the logs that a schedule sync is triggered.
2. **Firmware Compatibility**: Verify that `schedule_add` commands for Salsa (firmware 2.5.0) are sent in the new list format.
3. **Connection Resilience**: Verify that the system remains responsive ("last seen" updates) even during a multi-command schedule synchronization.
