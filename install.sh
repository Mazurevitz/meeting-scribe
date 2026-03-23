#!/bin/bash
# Meeting Scribe Installer
# Installs all dependencies and sets up the application

set -e

echo "=================================="
echo "  Meeting Scribe Installer"
echo "=================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}Error: This app only runs on macOS${NC}"
    exit 1
fi

echo "Checking dependencies..."
echo ""

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Homebrew not found. Installing...${NC}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo -e "${GREEN}✓ Homebrew${NC}"
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python 3 not found. Installing...${NC}"
    brew install python3
else
    echo -e "${GREEN}✓ Python 3 ($(python3 --version))${NC}"
fi

# Check for BlackHole
if brew list blackhole-2ch &> /dev/null; then
    echo -e "${GREEN}✓ BlackHole 2ch${NC}"
else
    echo -e "${YELLOW}Installing BlackHole 2ch (virtual audio driver)...${NC}"
    echo -e "${YELLOW}Note: This requires admin password and a reboot after install${NC}"
    brew install blackhole-2ch
    NEEDS_REBOOT=1
fi

# Check for Ollama
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}✓ Ollama${NC}"
else
    echo -e "${YELLOW}Installing Ollama...${NC}"
    brew install ollama
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt --quiet

echo -e "${GREEN}✓ Python dependencies installed${NC}"

# Check if Ollama has a model
echo ""
echo "Checking Ollama models..."
if pgrep -x "ollama" > /dev/null || curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    MODELS=$(curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('models',[])))" 2>/dev/null || echo "0")
    if [[ "$MODELS" -gt 0 ]]; then
        echo -e "${GREEN}✓ Ollama has $MODELS model(s) installed${NC}"
    else
        echo -e "${YELLOW}No Ollama models found. Installing qwen3:8b...${NC}"
        ollama pull qwen3:8b
    fi
else
    echo -e "${YELLOW}Ollama not running. Starting and pulling model...${NC}"
    ollama serve &> /dev/null &
    sleep 3
    ollama pull qwen3:8b
fi

# Save project directory so the .app launcher can find it
PROJ_DIR_CONFIG="$HOME/.config/meeting-scribe"
mkdir -p "$PROJ_DIR_CONFIG"
echo "$(pwd)" > "$PROJ_DIR_CONFIG/project_dir"
echo -e "${GREEN}✓ Project path saved${NC}"

# Setup launch agent
echo ""
read -p "Start Meeting Scribe automatically at login? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    ./scripts/install_launch_agent.sh
fi

# Copy app bundle to Applications
echo ""
if [ -d "MeetingRecorder.app" ]; then
    read -p "Install Meeting Recorder app to Applications folder? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        cp -r "MeetingRecorder.app" "/Applications/"
        echo -e "${GREEN}✓ Installed to /Applications/MeetingRecorder.app${NC}"
        echo "  You can drag it to your Dock for easy access."
    fi
fi

echo ""
echo "=================================="
echo -e "${GREEN}  Installation Complete!${NC}"
echo "=================================="
echo ""

if [[ -n "$NEEDS_REBOOT" ]]; then
    echo -e "${YELLOW}⚠️  BlackHole was installed. Please REBOOT your Mac for audio capture to work.${NC}"
    echo ""
    echo "After reboot:"
    echo "1. Open Audio MIDI Setup"
    echo "2. Create a Multi-Output Device with your speakers + BlackHole 2ch"
    echo "3. Set it as your system output"
    echo ""
    echo "See scripts/setup_blackhole.md for detailed instructions."
    echo ""
fi

echo "To start Meeting Recorder:"
echo "  • Double-click MeetingRecorder.app in Applications"
echo "  • Or run: python3 run.py"
echo ""
echo "The app will appear as 🎙 in your menu bar."
