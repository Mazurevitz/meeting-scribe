#!/bin/bash
# Install Meeting Scribe as a launch agent (starts at login)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.meetingscribe.app.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"

# Get Python path
PYTHON_PATH=$(which python3)

# Create the plist file
# Load HF token from .env if exists
HF_TOKEN=""
if [ -f "$PROJECT_DIR/.env" ]; then
    HF_TOKEN=$(grep "^HF_TOKEN=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
fi

cat > "$LAUNCH_AGENTS_DIR/$PLIST_NAME" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.meetingscribe.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$PROJECT_DIR/run.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HF_TOKEN</key>
        <string>$HF_TOKEN</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/meeting-scribe.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/meeting-scribe.error.log</string>
</dict>
</plist>
EOF

echo "✓ Created launch agent: $LAUNCH_AGENTS_DIR/$PLIST_NAME"

# Load the launch agent
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "✓ Loaded launch agent"
echo ""
echo "Meeting Scribe will now start automatically at login."
echo "To disable: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"
