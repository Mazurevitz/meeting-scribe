# Meeting Scribe

A macOS menu bar app that automatically records Zoom and Teams calls, transcribes them locally using Whisper, and generates AI-powered meeting summaries with Ollama. Everything runs locally on your Mac—no data leaves your machine.

![macOS](https://img.shields.io/badge/macOS-000000?style=flat&logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python&logoColor=white)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-Optimized-000000?style=flat&logo=apple&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## Features

- **Auto-Record Calls** — Automatically starts recording when Zoom or Teams calls begin (Mon-Fri)
- **Dual Audio Capture** — Records both your microphone and system audio (meeting participants)
- **Speaker Diarization** — Identifies different speakers (Speaker 1, Speaker 2, etc.) using whisperx
- **Local Transcription** — Uses [lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx), optimized for Apple Silicon
- **AI Summaries** — Generates meeting summaries with action items using Ollama
- **Hands-Free Pipeline** — Record → Transcribe → Summarize runs automatically
- **Privacy First** — 100% local processing, no cloud services, no data collection

## Requirements

- macOS (Apple Silicon recommended)
- Python 3.9+
- [BlackHole](https://existential.audio/blackhole/) (virtual audio driver for system audio capture)
- [Ollama](https://ollama.ai/) (for meeting summaries)

## Installation

### Quick Install (Recommended)

```bash
# Clone the repository
git clone https://github.com/Mazurevitz/meeting-scribe.git
cd meeting-scribe

# Run the installer
./install.sh
```

The installer handles everything: Homebrew, Python deps, BlackHole, Ollama, and launch-at-login setup.

### Manual Installation

<details>
<summary>Click to expand manual steps</summary>

#### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 2. Install BlackHole (System Audio Capture)

```bash
brew install blackhole-2ch
```

After installation, configure Audio MIDI Setup to capture system audio. See [setup guide](scripts/setup_blackhole.md) for detailed instructions.

#### 3. Install Ollama (Optional, for Summaries)

```bash
brew install ollama
ollama pull llama3.1:latest
ollama serve  # Keep running in background
```

#### 4. Enable Speaker Diarization (Optional)

```bash
# Install whisperx
pip install whisperx

# Get a HuggingFace token (free) from https://huggingface.co/settings/tokens
# Accept model terms at https://huggingface.co/pyannote/speaker-diarization-3.1

# Set the token
export HF_TOKEN="hf_your_token_here"

# Add to ~/.zshrc for persistence
echo 'export HF_TOKEN="hf_your_token_here"' >> ~/.zshrc
```

</details>

## Usage

### Start the App

```bash
python run.py
```

A microphone icon (🎙) appears in your menu bar. The app also starts automatically at login if configured.

### Menu Options

| Option | Description |
|--------|-------------|
| **Start/Stop Recording** | Manually control recording |
| **Auto-Record Calls (Mon-Fri)** | Toggle automatic recording for Zoom/Teams |
| **Auto-Transcribe** | Automatically transcribe after recording stops |
| **Auto-Summarize** | Automatically summarize after transcription |
| **Speaker Diarization** | Identify different speakers in transcript |
| **Transcribe Latest** | Transcribe the most recent recording |
| **Summarize Latest** | Generate AI summary of the latest transcript |
| **Copy Summary to Clipboard** | Copy the latest summary for pasting |
| **Devices** | Select microphone |
| **Models** | Select Ollama model for summaries |
| **Open Recordings Folder** | Open saved recordings in Finder |
| **Status** | Check BlackHole, Ollama, and diarization status |

**Tip:** Click on notifications to open the generated file directly.

### Auto-Recording

When enabled, Meeting Scribe monitors for Zoom and Teams calls:

1. Click the menu bar icon
2. Select **"Auto-Record Calls (Mon-Fri)"**
3. A checkmark indicates auto-record is active
4. Recording starts/stops automatically with your calls

### Hands-Free Pipeline

With default settings, the complete flow is automatic:

1. **Call starts** → Recording begins automatically
2. **Call ends** → Recording stops
3. **Auto-transcribe** → Transcript generated (with speaker labels if enabled)
4. **Auto-summarize** → AI summary with action items created
5. **Notification** → Click to open the summary

No manual intervention required.

### Speaker Diarization

When enabled, transcripts include speaker identification:

```
[00:15] SPEAKER_00:
  Hi everyone, let's get started with the weekly sync.

[00:22] SPEAKER_01:
  Thanks for setting this up. First item on the agenda...

[01:45] SPEAKER_00:
  Good point. Let me share my screen.
```

**Setup:**
1. Install whisperx: `pip install whisperx`
2. Set HuggingFace token: `export HF_TOKEN="hf_..."`
3. Enable in menu: **Speaker Diarization** ✓

Falls back to basic transcription automatically if diarization is unavailable.

### Output Files

All files are saved to `~/Documents/MeetingRecordings/`:

```
MeetingRecordings/
├── meeting_20240115_143022.wav        # Audio recording
├── meeting_20240115_143022.txt        # Transcript (with speaker labels)
└── meeting_20240115_143022.summary.md # AI-generated summary
```

### Configuration

Settings are persisted to `~/.config/meeting-scribe/config.json`:

- Auto-record preference
- Auto-transcribe/summarize toggles
- Speaker diarization preference
- Selected Ollama model

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Menu Bar (rumps)│────▶│  Audio Recorder  │────▶│  Processing     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                     │      │                    │
        │               ┌─────┘      └─────┐              │
        ▼               ▼                  ▼              ▼
┌──────────────┐  ┌──────────┐      ┌───────────┐  ┌─────────────┐
│ Call Monitor │  │ Mic Input│      │ BlackHole │  │   Whisper   │
│ (Zoom/Teams) │  └──────────┘      │(sys audio)│  │ (+ whisperx)│
└──────────────┘                    └───────────┘  └──────┬──────┘
                                                          │
                                                          ▼
                                                   ┌─────────────┐
                                                   │   Ollama    │
                                                   │ (summaries) │
                                                   └─────────────┘
```

## Supported Audio Devices

The app automatically detects:
- Default microphone
- BlackHole 2ch (system audio)
- ZoomAudioDevice (call detection)
- Microsoft Teams Audio (call detection)

## Models

### Transcription

| Model | Speed | Accuracy | Use Case |
|-------|-------|----------|----------|
| `distil-medium.en` | Fast | Good | Default, recommended |
| `tiny.en`, `base.en` | Fastest | Lower | Quick drafts |
| `medium.en` | Medium | Better | Diarization default |
| `large-v3` | Slow | Best | Important meetings |

### Summarization (Ollama)

Any Ollama model works. Select from menu under **Models → Ollama Model**.

Recommended:
- `llama3.1:latest` — Default, good balance
- `mistral:7b` — Fast and capable
- `llama3.1:70b` — Best quality (requires 48GB+ RAM)

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

See [scripts/setup_blackhole.md](scripts/setup_blackhole.md) for detailed instructions.

### Ollama not available

```bash
# Start Ollama server
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

### Speaker diarization not working

Check the **Status** menu for diarization status. Common issues:

1. **whisperx not installed**: `pip install whisperx`
2. **HF_TOKEN not set**: `export HF_TOKEN="hf_..."`
3. **Model terms not accepted**: Visit https://huggingface.co/pyannote/speaker-diarization-3.1

The app automatically falls back to basic transcription if diarization fails.

### App not starting at login

```bash
# Reinstall launch agent
./scripts/install_launch_agent.sh

# Or remove it
./scripts/uninstall_launch_agent.sh
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [rumps](https://github.com/jaredks/rumps) — macOS menu bar apps in Python
- [lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx) — Fast Whisper for Apple Silicon
- [whisperx](https://github.com/m-bain/whisperX) — Whisper with speaker diarization
- [BlackHole](https://existential.audio/blackhole/) — Virtual audio driver
- [Ollama](https://ollama.ai/) — Local LLM runner
- [pyannote-audio](https://github.com/pyannote/pyannote-audio) — Speaker diarization
