#!/bin/bash
# Deployment script for Petnet Feeder Service fixes
set -e

PI_IP="192.168.86.31"
PI_DIR="/home/pi/petnet-feeder-service"

echo "Compressing local feeder directory..."
tar -czf feeder_service.tar.gz feeder static README.md pyproject.toml poetry.lock Dockerfile docker-compose.yaml

echo "Syncing to Pi..."
SSHPASS=quackattack sshpass -e scp -o StrictHostKeyChecking=no feeder_service.tar.gz pi@$PI_IP:$PI_DIR/

echo "Extracting and rebuilding on Pi..."
SSHPASS=quackattack sshpass -e ssh -o StrictHostKeyChecking=no pi@$PI_IP "cd $PI_DIR && tar -xzf feeder_service.tar.gz && docker compose build petnet-feeder-service && docker compose up -d"

echo "Deployment complete. Cleaning up..."
rm feeder_service.tar.gz

echo "Verifying service status..."
SSHPASS=quackattack sshpass -e ssh -o StrictHostKeyChecking=no pi@$PI_IP "docker ps | grep petnet-feeder-service"
