#!/bin/bash
# Script to force a clean restart of the feeder service and clear out potential zombie MQTT connections
set -e

echo "Stopping petnet-feeder-service container..."
SSHPASS=quackattack sshpass -e ssh -o StrictHostKeyChecking=no pi@192.168.86.31 "docker stop petnet-feeder-service || true"

echo "Restarting petnet-feeder-service container..."
SSHPASS=quackattack sshpass -e ssh -o StrictHostKeyChecking=no pi@192.168.86.31 "cd /home/pi/petnet-feeder-service && docker compose up -d"

echo "Waiting for service to initialize..."
sleep 10

echo "Checking logs for MQTT connection..."
SSHPASS=quackattack sshpass -e ssh -o StrictHostKeyChecking=no pi@192.168.86.31 "docker logs petnet-feeder-service 2>&1 | grep -i 'MQTT Client connected' | tail -n 2"
