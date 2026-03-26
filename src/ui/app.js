/* Meeting Recorder — Alpine.js app */

const POLL_FAST_MS = 1000;   // state poll (recording, progress)
const POLL_SLOW_MS = 5000;   // meetings list, devices, models

// Safe API wrapper — returns null instead of throwing if pywebview isn't ready
const api = new Proxy({}, {
  get(_, method) {
    return async (...args) => {
      try {
        if (!window.pywebview || !window.pywebview.api) {
          console.warn("pywebview.api not ready");
          return null;
        }
        const fn = window.pywebview.api[method];
        if (!fn) {
          console.warn("Unknown API method:", method);
          return null;
        }
        return await fn(...args);
      } catch (e) {
        console.error(`API.${method} failed:`, e);
        return null;
      }
    };
  },
});

function app() {
  return {
    // Backend state (polled)
    state: {
      recording: false,
      duration: "",
      processing: false,
      progress: null,
      progress_stage: null,
      auto_record: false,
      auto_transcribe: true,
      auto_summarize: true,
      diarization: true,
      diarization_available: false,
      ollama_available: false,
      ollama_model: "",
      incomplete_count: 0,
    },

    meetings: [],
    devices: { mics: [], system_audio: {} },
    models: { models: [], current: "" },

    // UI state
    search: "",
    showSettings: false,
    ready: false,
    renaming: null,
    editingTags: null,
    toast: null,
    sortBy: "date",   // "date" or "name"
    sortAsc: false,    // false = newest/Z first

    async init() {
      // Wait for pywebview bridge to be ready
      if (!window.pywebview || !window.pywebview.api) {
        await new Promise((resolve) => {
          window.addEventListener("pywebviewready", resolve);
        });
      }

      this.ready = true;
      console.log("pywebview ready, loading data...");

      // Initial data load
      await this.pollState();
      await this.refreshSlow();

      setInterval(() => this.pollState(), POLL_FAST_MS);
      setInterval(() => this.refreshSlow(), POLL_SLOW_MS);
    },

    async pollState() {
      if (!this.ready) return;
      const s = await api.get_state();
      if (s) this.state = s;
    },

    async refreshSlow() {
      if (!this.ready) return;
      const [meetings, devices, models] = await Promise.all([
        api.get_meetings(),
        api.get_devices(),
        api.get_models(),
      ]);
      if (meetings) this.meetings = meetings;
      if (devices) this.devices = devices;
      if (models) this.models = models;
    },

    filteredMeetings() {
      let list = this.meetings;

      if (this.search) {
        const q = this.search.toLowerCase();
        list = list.filter((m) => {
          const haystack = [
            m.name, m.created, m.title || "",
            ...(m.tags || []),
            ...(m.people || []),
          ].join(" ").toLowerCase();
          return haystack.includes(q);
        });
      }

      const dir = this.sortAsc ? 1 : -1;
      if (this.sortBy === "name") {
        list = [...list].sort((a, b) => {
          const an = (a.title || a.name).toLowerCase();
          const bn = (b.title || b.name).toLowerCase();
          return an < bn ? -dir : an > bn ? dir : 0;
        });
      } else {
        list = [...list].sort((a, b) => {
          return a.created < b.created ? -dir : a.created > b.created ? dir : 0;
        });
      }

      return list;
    },

    toggleSort() {
      // Cycle: date↓ → date↑ → name↓ → name↑ → date↓
      if (this.sortBy === "date" && !this.sortAsc) {
        this.sortAsc = true;
      } else if (this.sortBy === "date" && this.sortAsc) {
        this.sortBy = "name";
        this.sortAsc = false;
      } else if (this.sortBy === "name" && !this.sortAsc) {
        this.sortAsc = true;
      } else {
        this.sortBy = "date";
        this.sortAsc = false;
      }
    },

    // Format meeting name for display
    formatName(name) {
      const match = name.match(
        /meeting_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/
      );
      if (match) {
        const [, y, mo, d, h, mi] = match;
        const date = new Date(y, mo - 1, d, h, mi);
        return date.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit",
        });
      }
      return name;
    },

    // Badge class helper
    badgeClass(meeting, type) {
      if (type === "transcript") {
        if (meeting.has_transcript) return "badge-ok";
        if (meeting.pipeline_stage === "transcribing") return "badge-progress";
        if (meeting.pipeline_stage === "failed" && !meeting.has_transcript)
          return "badge-fail";
        return "badge-no";
      }
      if (type === "summary") {
        if (meeting.has_summary) return "badge-ok";
        if (meeting.pipeline_stage === "summarizing") return "badge-progress";
        if (
          meeting.pipeline_stage === "failed" &&
          meeting.has_transcript &&
          !meeting.has_summary
        )
          return "badge-fail";
        return "badge-no";
      }
      return "badge-no";
    },

    // Actions
    async toggleRecording() {
      const r = await api.toggle_recording();
      console.log("toggle_recording:", r);
      await this.pollState();
    },

    async setConfig(key, value) {
      await api.set_config(key, value);
      await this.pollState();
    },

    async selectMic(index) {
      await api.select_mic(index);
    },

    async selectModel(name) {
      await api.select_model(name);
      this.models.current = name;
    },

    async badgeClick(meeting, type) {
      if (type === "transcript") {
        if (meeting.has_transcript && meeting.transcript_path) {
          await api.open_file(meeting.transcript_path);
        } else if (meeting.has_audio) {
          // Transcribe or retry failed transcription
          await this.doTranscribe(meeting);
        }
      } else if (type === "summary") {
        if (meeting.has_summary && meeting.summary_path) {
          await api.open_file(meeting.summary_path);
        } else if (meeting.has_transcript) {
          // Summarize or retry failed summarization
          await this.doSummarize(meeting);
        }
      }
    },

    async doTranscribe(meeting) {
      if (meeting.audio_path) {
        await api.transcribe(meeting.audio_path);
        await this.pollState();
      }
    },

    async doSummarize(meeting) {
      if (meeting.transcript_path) {
        await api.summarize(meeting.transcript_path);
        await this.pollState();
      }
    },

    async doRetry(meeting) {
      await api.retry(meeting.name);
      await this.pollState();
    },

    async copySummary(meeting) {
      if (meeting.summary_path) {
        await api.copy_summary(meeting.summary_path);
      }
    },

    async openMeeting(meeting) {
      const path =
        meeting.summary_path || meeting.transcript_path || meeting.audio_path;
      if (path) {
        await api.open_file(path);
      }
    },

    startRename(meeting) {
      this.renaming = meeting.name;
    },

    async finishRename(meeting, newTitle) {
      this.renaming = null;
      if (newTitle && newTitle.trim() !== meeting.title && newTitle.trim() !== this.formatName(meeting.name)) {
        await api.rename_meeting(meeting.name, newTitle.trim());
        await this.refreshSlow();
      }
    },

    startEditTags(meeting) {
      this.editingTags = meeting.name;
    },

    async finishEditTags(meeting, value) {
      this.editingTags = null;
      const tags = value.split(",").map((t) => t.trim()).filter((t) => t.length > 0);
      await api.set_tags(meeting.name, tags);
      await this.refreshSlow();
    },

    async aiRename(meeting) {
      this.showToast("Generating title...", 5000);
      const r = await api.ai_rename(meeting.name);
      if (r && r.ok) {
        this.showToast("Renamed: " + r.title);
        await this.refreshSlow();
      } else {
        this.showToast(r?.error || "AI rename failed");
      }
    },

    async deleteMeeting(meeting) {
      if (!confirm(`Delete "${this.formatName(meeting.name)}" and all its files?`)) return;
      await api.delete_meeting(meeting.name);
      await this.refreshSlow();
    },

    async cancelProcessing() {
      await api.cancel_processing();
      await this.pollState();
    },

    showToast(msg, duration = 2000) {
      this.toast = msg;
      setTimeout(() => { this.toast = null; }, duration);
    },

    async copyError(errorText) {
      if (!errorText) return;
      try {
        await navigator.clipboard.writeText(errorText);
      } catch {
        // Fallback: use Python pbcopy
        await api.copy_summary(errorText);
      }
      this.showToast("Error copied to clipboard");
    },

    async openFolder() {
      await api.open_folder();
    },
  };
}
