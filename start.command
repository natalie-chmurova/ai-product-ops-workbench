#!/bin/bash
# Double-click this file in Finder to launch the AI Product Ops Workbench web app.
# It starts the local server and opens the app in your browser.

cd "$(dirname "$0")" || exit 1

# Create the virtual environment on first run if it isn't there yet.
if [ ! -d ".venv" ]; then
  echo "First-time setup: creating environment and installing dependencies..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi

echo "Starting AI Product Ops Workbench..."
echo "A browser tab will open. To stop the app, close this window."
./.venv/bin/streamlit run app.py
