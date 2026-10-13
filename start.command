#!/bin/bash
# Double-click this file in Finder to launch the AI Product Ops Workbench web app.
# It starts the local server and opens the app in your browser.

cd "$(dirname "$0")" || exit 1

# Create the virtual environment on first run if it isn't there yet.
if [ ! -d ".venv" ]; then
  echo "First-time setup: creating environment and installing dependencies..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
  # Audio stays opt-in: the transcription stack is about 570 MB (torch among it), and
  # the simplest way to start the app should not download it for a feature that may
  # never be used. Uploading a recording without it says what to install.
  if [ "$(uname -m)" = "arm64" ]; then
    echo ""
    echo "Optional, to transcribe audio recordings on this Mac (about 570 MB):"
    echo "  ./.venv/bin/pip install -r requirements-audio.txt && brew install ffmpeg"
    echo ""
  fi
fi

echo "Starting AI Product Ops Workbench..."
echo "A browser tab will open. To stop the app, close this window."
./.venv/bin/streamlit run app.py
