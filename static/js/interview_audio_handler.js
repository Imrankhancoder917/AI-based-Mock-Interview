class InterviewAudioHandler {
  constructor(options) {
    this.endpoints = options.endpoints || {};
    this.micButton = options.micButton;
    this.waveform = options.waveform;
    this.statusElement = options.statusElement;
    this.subStatusElement = options.subStatusElement;
    this.onTranscript = options.onTranscript || (() => {});
    this.onStateChange = options.onStateChange || (() => {});
    this.onError = options.onError || (() => {});
    this.currentStream = null;
    this.mediaRecorder = null;
    this.chunks = [];
    this.recording = false;
    this.speaking = false;
    this.audioPlayer = new Audio();
    this.audioPlayer.preload = "auto";

    this._bindAudioEvents();
    this._refreshState();
  }

  _bindAudioEvents() {
    this.audioPlayer.addEventListener("play", () => this.setSpeaking(true));
    this.audioPlayer.addEventListener("ended", () => this.setSpeaking(false));
    this.audioPlayer.addEventListener("pause", () => {
      if (this.audioPlayer.ended) {
        this.setSpeaking(false);
      }
    });
  }

  _refreshState() {
    if (this.micButton) {
      this.micButton.classList.toggle("recording", this.recording);
      this.micButton.classList.toggle("speaking", this.speaking);
    }
    if (this.waveform) {
      this.waveform.classList.toggle("is-recording", this.recording);
      this.waveform.classList.toggle("is-speaking", this.speaking);
    }
    if (this.statusElement) {
      this.statusElement.textContent = this.recording ? "Recording" : this.speaking ? "Speaking" : "Idle";
    }
    this.onStateChange({ recording: this.recording, speaking: this.speaking });
  }

  setStatus(status, subStatus) {
    if (this.statusElement) {
      this.statusElement.textContent = status;
    }
    if (this.subStatusElement && typeof subStatus === "string") {
      this.subStatusElement.textContent = subStatus;
    }
  }

  setRecording(value) {
    this.recording = value;
    this._refreshState();
  }

  setSpeaking(value) {
    this.speaking = value;
    this._refreshState();
    if (value) {
      this.setStatus("Speaking", "The interviewer is reading the current prompt or feedback aloud.");
    }
  }

  async startRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      if (window.location.protocol === "http:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
        throw new Error("Microphone access is blocked in insecure contexts. Please access this app via http://localhost:5001 or configure HTTPS to enable audio recording.");
      }
      throw new Error("Audio recording is not supported in this browser. Please check browser permissions.");
    }

    if (this.recording) {
      return;
    }

    this.currentStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.chunks = [];

    const mimeType = this._chooseMimeType();
    this.mediaRecorder = new MediaRecorder(this.currentStream, mimeType ? { mimeType } : undefined);

    this.mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) {
        this.chunks.push(event.data);
      }
    });

    this.mediaRecorder.addEventListener("stop", async () => {
      const blob = new Blob(this.chunks, { type: this.mediaRecorder?.mimeType || "audio/webm" });
      this._stopStreamTracks();
      this.setRecording(false);
      this.setStatus("Transcribing", "Sending your recording to the backend whisper service.");

      try {
        const transcript = await this.transcribe(blob);
        this.onTranscript(transcript);
      } catch (error) {
        this.onError(error);
      }
    });

    // Start with a timeslice of 250ms to ensure continuous dataavailable events (highly recommended for Safari/iOS compatibility)
    this.mediaRecorder.start(250);
    this.setRecording(true);
    this.setStatus("Recording", "Speak your answer naturally. The browser mic is sending audio to the backend.");
  }

  stopRecording() {
    if (!this.recording || !this.mediaRecorder) {
      return;
    }

    this.mediaRecorder.stop();
  }

  toggleRecording() {
    if (this.recording) {
      this.stopRecording();
      return;
    }

    return this.startRecording();
  }

  async transcribe(blob) {
    const formData = new FormData();
    // Resolve dynamic extension based on actual browser MIME container type to avoid Groq decoding failures
    let extension = "webm";
    if (blob.type) {
      if (blob.type.includes("mp4") || blob.type.includes("m4a")) {
        extension = "mp4";
      } else if (blob.type.includes("ogg")) {
        extension = "ogg";
      } else if (blob.type.includes("wav")) {
        extension = "wav";
      } else if (blob.type.includes("webm")) {
        extension = "webm";
      }
    }
    formData.append("audio", blob, `interview.${extension}`);

    const response = await fetch(this.endpoints.transcribe, {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Unable to transcribe the recording.");
    }

    this.setStatus("Idle", "Transcription complete. You can edit the transcript before submitting.");
    return payload.transcript || "";
  }

  async speak(text) {
    const content = (text || "").trim();
    if (!content) {
      return;
    }

    try {
      const response = await fetch(this.endpoints.respond, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content, language: "en", slow: false }),
      });

      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Unable to synthesize audio.");
      }

      this.audioPlayer.pause();
      this.audioPlayer.src = payload.data_url;
      await this.audioPlayer.play();
    } catch (error) {
      this.onError(error);
      throw error;
    }
  }

  stopSpeaking() {
    this.audioPlayer.pause();
    this.audioPlayer.currentTime = 0;
    this.setSpeaking(false);
  }

  _chooseMimeType() {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    return candidates.find((type) => window.MediaRecorder && MediaRecorder.isTypeSupported(type)) || "";
  }

  _stopStreamTracks() {
    if (this.currentStream) {
      this.currentStream.getTracks().forEach((track) => track.stop());
      this.currentStream = null;
    }
  }
}

window.InterviewAudioHandler = InterviewAudioHandler;