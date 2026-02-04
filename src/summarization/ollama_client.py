"""Ollama client for meeting summarization."""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Union

import requests


class OllamaClient:
    """Client for Ollama local LLM API."""

    DEFAULT_MODEL = "llama3.1:latest"
    DEFAULT_URL = "http://localhost:11434"

    MEETING_SUMMARY_PROMPT = """You are a helpful assistant that summarizes meeting transcripts.

Given the following meeting transcript, please provide:

1. **Meeting Summary** (2-3 paragraphs)
   - Key topics discussed
   - Important decisions made
   - Overall context and purpose

2. **Key Points** (bullet points)
   - Main discussion points
   - Important information shared

3. **Action Items** (if any)
   - Tasks assigned with responsible person (if mentioned)
   - Deadlines (if mentioned)
   - Follow-up items

4. **Decisions Made** (if any)
   - List any decisions that were agreed upon

Please be concise but comprehensive. Focus on actionable information.

---
TRANSCRIPT:
{transcript}
---

Please provide the summary:"""

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None):
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or self.DEFAULT_URL

    def is_available(self) -> bool:
        """Check if Ollama server is running and accessible."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> List[str]:
        """List available models in Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except requests.RequestException:
            return []

    def is_model_available(self, model_name: Optional[str] = None) -> bool:
        """Check if a specific model is available."""
        model = model_name or self.model
        models = self.list_models()
        return any(model in m or m.startswith(model.split(":")[0]) for m in models)

    def generate(self, prompt: str, stream: bool = False) -> str:
        """
        Generate a response from Ollama.

        Args:
            prompt: The prompt to send
            stream: Whether to stream the response

        Returns:
            The generated text response
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
        }

        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()

        if stream:
            full_response = []
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if "response" in data:
                        full_response.append(data["response"])
                    if data.get("done"):
                        break
            return "".join(full_response)
        else:
            data = response.json()
            return data.get("response", "")

    def summarize_meeting(
        self,
        transcript: str,
        output_path: Optional[Union[Path, str]] = None,
        transcript_path: Optional[Union[Path, str]] = None
    ) -> str:
        """
        Summarize a meeting transcript.

        Args:
            transcript: The meeting transcript text
            output_path: Optional path to save the summary
            transcript_path: Optional path to the source transcript file

        Returns:
            The meeting summary
        """
        prompt = self.MEETING_SUMMARY_PROMPT.format(transcript=transcript)
        summary = self.generate(prompt)

        if output_path or transcript_path:
            if output_path is None:
                output_path = Path(transcript_path).with_suffix(".summary.md")
            else:
                output_path = Path(output_path)

            output_path.parent.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            source = f"\nSource: {transcript_path}\n" if transcript_path else ""
            header = f"# Meeting Summary\n\nGenerated: {timestamp}\nModel: {self.model}{source}\n---\n\n"

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(header)
                f.write(summary)

        return summary

    def summarize_transcript_file(self, transcript_path: Union[Path, str]) -> str:
        """
        Load and summarize a transcript file.

        Args:
            transcript_path: Path to the transcript file

        Returns:
            The meeting summary
        """
        transcript_path = Path(transcript_path)
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript file not found: {transcript_path}")

        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        transcript_lines = []
        in_header = True
        for line in lines:
            if in_header and line.startswith("="):
                in_header = False
                continue
            if not in_header:
                transcript_lines.append(line)

        transcript = "\n".join(transcript_lines).strip() or content

        return self.summarize_meeting(
            transcript=transcript,
            transcript_path=transcript_path
        )
