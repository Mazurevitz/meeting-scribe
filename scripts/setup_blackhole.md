# BlackHole Setup Guide

BlackHole is a virtual audio driver that allows the app to capture system audio (from Teams, Zoom, etc.).

## Installation

```bash
brew install blackhole-2ch
```

## Configuration (One-Time Setup)

### Step 1: Open Audio MIDI Setup
- Press `Cmd + Space` and search for "Audio MIDI Setup"
- Or find it in `/Applications/Utilities/Audio MIDI Setup.app`

### Step 2: Create Multi-Output Device
1. Click the **+** button at the bottom left
2. Select **"Create Multi-Output Device"**
3. In the right panel, check both:
   - **Built-in Output** (or your speakers/headphones)
   - **BlackHole 2ch**
4. Make sure **Built-in Output** is listed first (drag to reorder if needed)

### Step 3: Set as Default Output
1. Right-click on your new "Multi-Output Device"
2. Select **"Use This Device For Sound Output"**

Alternatively, go to **System Preferences > Sound > Output** and select "Multi-Output Device".

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    Multi-Output Device                       │
├─────────────────────────────────────────────────────────────┤
│  Meeting App (Teams/Zoom)                                    │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │ Built-in Output │    │  BlackHole 2ch  │                 │
│  │   (You hear)    │    │ (App records)   │                 │
│  └─────────────────┘    └─────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

Audio is sent to both your speakers AND to BlackHole simultaneously. The Meeting Recorder app then captures audio from the BlackHole input device.

## Troubleshooting

### No Sound After Setup
- Make sure "Multi-Output Device" is set as the output
- Check that Built-in Output is checked in the Multi-Output Device

### App Doesn't Detect BlackHole
- Restart the Meeting Recorder app
- Check if BlackHole is installed: `brew list | grep blackhole`
- Reinstall if needed: `brew reinstall blackhole-2ch`

### Only Recording Microphone, Not System Audio
- Verify BlackHole 2ch appears in Audio MIDI Setup
- Make sure the Multi-Output Device includes BlackHole 2ch
- Ensure the meeting app is outputting to the Multi-Output Device

## Reverting Changes

To stop using BlackHole:
1. Go to **System Preferences > Sound > Output**
2. Select your regular output device (e.g., "Built-in Output")
3. Optionally, delete the Multi-Output Device in Audio MIDI Setup
