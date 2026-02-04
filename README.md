# Meeting Scribe

A macOS menu bar app that automatically records Zoom and Teams calls, transcribes them locally using Whisper, and generates AI-powered meeting summaries with Ollama. Everything runs locally on your Mac—no data leaves your machine.

![macOS](https://img.shields.io/badge/macOS-000000?style=flat&logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python&logoColor=white)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-Optimized-000000?style=flat&logo=apple&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## Features

- **Auto-Record Calls** — Automatically starts recording when Zoom or Teams calls begin (Mon-Fri)
- **Dual Audio Capture** — Records both your microphone and system audio (meeting participants)
- **Local Transcription** — Uses [lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx), optimized for Apple Silicon
- **AI Summaries** — Generates meeting summaries with action items using Ollama
- **Privacy First** — 100% local processing, no cloud services, no data collection

## Requirements

- macOS (Apple Silicon recommended)
- Python 3.9+
- [BlackHole](https://existential.audio/blackhole/) (virtual audio driver for system audio capture)
- [Ollama](https://ollama.ai/) (for meeting summaries)

## Installation

### 1. Install Dependencies

```bash
# Clone the repository
git clone https://github.com/Mazurevitz/meeting-scribe.git
cd meeting-scribe

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Install BlackHole (System Audio Capture)

```bash
brew install blackhole-2ch
```

After installation, configure Audio MIDI Setup to capture system audio. See [setup guide](scripts/setup_blackhole.md) for detailed instructions.

### 3. Install Ollama (Optional, for Summaries)

```bash
brew install ollama
ollama pull llama3.1:8b
ollama serve  # Keep running in background
```

## Usage

### Start the App

```bash
python run.py
```

A microphone icon (🎙) appears in your menu bar.

### Menu Options

| Option | Description |
|--------|-------------|
| **Start/Stop Recording** | Manually control recording |
| **Auto-Record Calls (Mon-Fri)** | Toggle automatic recording for Zoom/Teams |
| **Transcribe Latest** | Transcribe the most recent recording |
| **Summarize Latest** | Generate AI summary of the latest transcript |
| **Devices** | Select microphone and view system audio status |
| **Open Recordings Folder** | Open saved recordings in Finder |

### Auto-Recording

When enabled, Meeting Scribe monitors for Zoom and Teams calls:

1. Click the menu bar icon
2. Select **"Auto-Record Calls (Mon-Fri)"**
3. A checkmark indicates auto-record is active
4. Recording starts/stops automatically with your calls

### Output Files

All files are saved to `~/Documents/MeetingRecordings/`:

```
MeetingRecordings/
├── meeting_20240115_143022.wav        # Audio recording
├── meeting_20240115_143022.txt        # Transcript
└── meeting_20240115_143022.summary.md # AI-generated summary
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Menu Bar (rumps)│────▶│  Audio Recorder  │────▶│  Processing     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                     │      │                    │
        │               ┌─────┘      └─────┐              │
        ▼               ▼                  ▼              ▼
┌──────────────┐  ┌──────────┐      ┌───────────┐  ┌─────────────┐
│ Call Monitor │  │ Mic Input│      │ BlackHole │  │ Whisper MLX │
│ (Zoom/Teams) │  └──────────┘      │(sys audio)│  └──────┬──────┘
└──────────────┘                    └───────────┘         │
                                                          ▼
                                                   ┌─────────────┐
                                                   │   Ollama    │
                                                   └─────────────┘
```

## Configuration

### Supported Audio Devices

The app automatically detects:
- Default microphone
- BlackHole 2ch (system audio)
- ZoomAudioDevice (call detection)
- Microsoft Teams Audio (call detection)

### Whisper Models

Default: `distil-medium.en` — good balance of speed and accuracy.

Available models (configurable in code):
- `tiny.en`, `base.en`, `small.en` — faster, less accurate
- `medium.en`, `distil-medium.en` — balanced
- `large-v3`, `distil-large-v3` — most accurate, slower

### Ollama Models

Default: `llama3.1:8b`

Any Ollama model works. Recommended alternatives:
- `mistral:7b` — fast and capable
- `llama3.1:70b` — higher quality summaries (requires more RAM)

## Troubleshooting

### BlackHole not detected

```bash
# Verify installation
brew list | grep blackhole

# Reinstall if needed
brew reinstall blackhole-2ch
```

Restart your Mac after installing BlackHole.

### No system audio in recordings

1. Open **Audio MIDI Setup**
2. Create a **Multi-Output Device** with both your speakers and BlackHole
3. Set it as your system output in **System Preferences > Sound**

### Ollama not available

```bash
# Start Ollama server
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [rumps](https://github.com/jaredks/rumps) — macOS menu bar apps in Python
- [lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx) — Fast Whisper for Apple Silicon
- [BlackHole](https://existential.audio/blackhole/) — Virtual audio driver
- [Ollama](https://ollama.ai/) — Local LLM runner
