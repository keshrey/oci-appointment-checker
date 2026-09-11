#!/bin/bash
set -a
source "$(dirname "$0")/.env.local"
set +a
python3 "$(dirname "$0")/test_booking_flow.py"
