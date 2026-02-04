#!/bin/bash
# Remove Meeting Scribe launch agent

PLIST_NAME="com.meetingscribe.app.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

if [ -f "$LAUNCH_AGENTS_DIR/$PLIST_NAME" ]; then
    launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true
    rm "$LAUNCH_AGENTS_DIR/$PLIST_NAME"
    echo "✓ Removed launch agent"
    echo "Meeting Scribe will no longer start at login."
else
    echo "Launch agent not found. Nothing to remove."
fi
