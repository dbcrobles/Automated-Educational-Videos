#!/bin/bash
echo "Initializing Video Generation Pipeline..."
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Kill any existing reflex servers or main.py processes to avoid port conflicts
pkill -f "reflex run" || true
pkill -f "python3 main.py" || true

# Start the Backend Workers
echo "Starting Backend Orchestrator..."
cd Backend
python3 main.py &
cd ..

# Start the Reflex Dashboard
echo "Starting Dashboard on localhost:3000..."
cd Frontend
python -m reflex run

echo "Pipeline shut down."
