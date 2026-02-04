# Meeting AI Notes

A macOS menu bar app that records meetings (Teams/Zoom), transcribes locally with Whisper, and summarizes with Ollama.

## Features

- **Dual Audio Capture**: Records both your microphone and system audio (meeting participants)
- **Local Transcription**: Uses lightning-whisper-mlx (Apple Silicon optimized)
- **AI Summaries**: Generates meeting summaries with action items using Ollama
- **Privacy First**: Everything runs locally - no data sent to the cloud

## Prerequisites

### 1. BlackHole (Virtual Audio Device)

```bash
brew install blackhole-2ch
```

Then configure Audio MIDI Setup - see [scripts/setup_blackhole.md](scripts/setup_blackhole.md) for detailed instructions.

### 2. Ollama (Local LLM)

```bash
brew install ollama
ollama pull llama3.1:8b
ollama serve  # Keep running in background
```

### 3. Python Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Start the App

```bash
python run.py
```

A microphone icon (🎙) will appear in your menu bar.

### Recording a Meeting

1. Click the menu bar icon
2. Select **"Start Recording"**
3. The icon changes to 🔴 with a timer
4. Join your meeting (Teams, Zoom, etc.)
5. Click **"Stop Recording"** when done

### Transcription

1. Click **"Transcribe Latest"**
2. Wait for the notification (icon shows ⏳)
3. Transcript is saved next to the audio file

### Summarization

1. Click **"Summarize Latest"**
2. Wait for Ollama to process
3. Summary with action items is saved as `.summary.md`

## File Locations

All files are saved to `~/Documents/MeetingRecordings/`:

```
MeetingRecordings/
├── meeting_20240115_143022.wav      # Audio recording
├── meeting_20240115_143022.txt      # Transcript
└── meeting_20240115_143022.summary.md  # Summary
```

## Menu Options

- **Start/Stop Recording** - Toggle recording
- **Transcribe Latest** - Transcribe most recent recording
- **Summarize Latest** - Summarize most recent transcript
- **Devices** - Select microphone, view system audio status
- **Open Recordings Folder** - Open in Finder
- **Status** - Check BlackHole and Ollama status

## Troubleshooting

### "BlackHole not detected"

1. Install BlackHole: `brew install blackhole-2ch`
2. Restart the app

### "Ollama not available"

1. Start Ollama: `ollama serve`
2. Pull a model: `ollama pull llama3.1:8b`

### No system audio in recording

1. Set up Multi-Output Device in Audio MIDI Setup
2. Select Multi-Output Device as your system output
3. See [scripts/setup_blackhole.md](scripts/setup_blackhole.md)

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Menu Bar (rumps)│────▶│  Audio Recorder  │────▶│  Processing     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                              │      │                    │
                        ┌─────┘      └─────┐              │
                        ▼                  ▼              ▼
                  ┌──────────┐      ┌───────────┐  ┌─────────────┐
                  │ Mic Input│      │ BlackHole │  │ Whisper MLX │
                  │(sounddevice)    │(system audio) └──────┬──────┘
                  └──────────┘      └───────────┘         │
                                                          ▼
                                                   ┌─────────────┐
                                                   │   Ollama    │
                                                   └─────────────┘
```

## License

MIT
