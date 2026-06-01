document.addEventListener("DOMContentLoaded", () => {
  const bootstrapState = window.__INTERVIEW_BOOTSTRAP__ || {};
  const state = {
    resumeProfile: bootstrapState.interviewState?.resume_profile || {},
    jobDescription: bootstrapState.interviewState?.job_description || {},
    history: bootstrapState.interviewState?.history || [],
    difficulty: bootstrapState.interviewState?.difficulty || 5,
    currentQuestion: bootstrapState.initialQuestion || bootstrapState.interviewState?.current_question || null,
    voiceMode: true,
    round: bootstrapState.interviewState?.history?.length || 0,
    sessionStartedAt: null,
    timerHandle: null,
  };

  const endpoints = bootstrapState.endpoints || {};

  const elements = {
    questionCard: document.getElementById("questionCard"),
    questionKind: document.getElementById("questionKind"),
    questionText: document.getElementById("questionText"),
    questionHint: document.getElementById("questionHint"),
    questionDifficulty: document.getElementById("questionDifficulty"),
    questionScore: document.getElementById("questionScore"),
    startQuestionBtn: document.getElementById("startQuestionBtn"),
    speakQuestionBtn: document.getElementById("speakQuestionBtn"),
    generateFollowUpBtn: document.getElementById("generateFollowUpBtn"),
    micButton: document.getElementById("micButton"),
    waveform: document.getElementById("waveform"),
    audioStatus: document.getElementById("audioStatus"),
    audioSubStatus: document.getElementById("audioSubStatus"),
    answerInput: document.getElementById("answerInput"),
    transcribeBtn: document.getElementById("transcribeBtn"),
    submitAnswerBtn: document.getElementById("submitAnswerBtn"),
    clearAnswerBtn: document.getElementById("clearAnswerBtn"),
    resetSessionBtn: document.getElementById("resetSessionBtn"),
    transcriptList: document.getElementById("transcriptList"),
    progressFill: document.getElementById("progressFill"),
    progressLabel: document.getElementById("progressLabel"),
    difficultyBadge: document.getElementById("difficultyBadge"),
    timerDisplay: document.getElementById("timerDisplay"),
    roundMetric: document.getElementById("roundMetric"),
    scoreMetric: document.getElementById("scoreMetric"),
    voiceMetric: document.getElementById("voiceMetric"),
    sessionMetric: document.getElementById("sessionMetric"),
    interviewerStatus: document.getElementById("interviewerStatus"),
    nextQuestionPreview: document.getElementById("nextQuestionPreview"),
    coachNotes: document.getElementById("coachNotes"),
    voiceModeToggle: document.getElementById("voiceModeToggle"),
  };

  const audioHandler = new window.InterviewAudioHandler({
    endpoints,
    micButton: elements.micButton,
    waveform: elements.waveform,
    statusElement: elements.audioStatus,
    subStatusElement: elements.audioSubStatus,
    onTranscript: async (transcript) => {
      // Populate the answer input with the transcript and allow the user to edit.
      elements.answerInput.value = transcript;
      elements.audioSubStatus.textContent = "Transcript ready. Edit the transcript if needed, then press Submit to confirm.";
      // Mark the submit button so we can tag the submission as "Voice" when the user confirms.
      elements.submitAnswerBtn.dataset.pendingVoice = "1";
      elements.submitAnswerBtn.disabled = false;
      // Focus the input to encourage review/editing.
      try {
        elements.answerInput.focus();
        elements.answerInput.setSelectionRange(elements.answerInput.value.length, elements.answerInput.value.length);
      } catch (e) {
        // ignore focus errors on some browsers
      }
    },
    onStateChange: ({ recording, speaking }) => {
      elements.voiceMetric.textContent = recording ? "Recording" : speaking ? "Speaking" : "Off";
    },
    onError: (error) => {
      renderSystemMessage(error.message || "Audio processing failed.", "error");
    },
  });

  function formatTime(totalSeconds) {
    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
  }

  function updateTimer() {
    if (!state.sessionStartedAt) {
      elements.timerDisplay.textContent = "00:00";
      return;
    }

    const elapsed = Math.floor((Date.now() - state.sessionStartedAt) / 1000);
    elements.timerDisplay.textContent = formatTime(elapsed);
  }

  function startTimer() {
    if (state.timerHandle) {
      return;
    }

    state.sessionStartedAt = state.sessionStartedAt || Date.now();
    updateTimer();
    state.timerHandle = window.setInterval(updateTimer, 1000);
  }

  function stopTimer() {
    if (state.timerHandle) {
      window.clearInterval(state.timerHandle);
      state.timerHandle = null;
    }
  }

  function renderQuestion(question, animate = true) {
    if (!question) {
      return;
    }

    const apply = () => {
      elements.questionKind.textContent = question.kind || "adaptive";
      elements.questionText.textContent = question.prompt || "No question available.";
      elements.questionDifficulty.textContent = `D${question.difficulty || state.difficulty}`;
      elements.questionScore.textContent = question.trap ? "Trap" : "Live";
      elements.questionHint.textContent = question.trap
        ? "This one is designed to test your assumptions and expose shallow reasoning."
        : "Answer like you are in a senior interview: precise, concise, and rooted in tradeoffs.";
      elements.difficultyBadge.textContent = `${question.difficulty || state.difficulty} / 10`;
      elements.sessionMetric.textContent = question.trap ? "Trap mode" : "Live";
      elements.nextQuestionPreview.querySelector("strong").textContent = question.follow_up_seed
        ? `The next follow-up will likely focus on ${question.follow_up_seed}.`
        : "The next question will adapt after your answer.";
      elements.questionCard.classList.remove("transition-out");
      elements.questionCard.classList.add("transition-in");
      window.setTimeout(() => elements.questionCard.classList.remove("transition-in"), 320);
      state.currentQuestion = question;
      state.difficulty = question.difficulty || state.difficulty;
      startTimer();
      speakQuestion(question.prompt);
      updateProgress();
    };

    if (!animate) {
      apply();
      return;
    }

    elements.questionCard.classList.add("transition-out");
    window.setTimeout(apply, 180);
  }

  function renderTranscriptItem(role, title, text, meta = {}) {
    const item = document.createElement("article");
    item.className = `transcript-item ${role}`;

    const strong = document.createElement("strong");
    strong.textContent = title;

    const paragraph = document.createElement("p");
    paragraph.textContent = text;

    const metaRow = document.createElement("div");
    metaRow.className = "transcript-meta";

    const left = document.createElement("span");
    left.textContent = meta.label || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    const right = document.createElement("span");
    right.textContent = meta.tag || "";

    metaRow.append(left, right);
    item.append(strong, paragraph, metaRow);
    elements.transcriptList.prepend(item);
  }

  function renderSystemMessage(text, kind = "info") {
    const item = document.createElement("article");
    item.className = `transcript-item ${kind}`;

    const strong = document.createElement("strong");
    strong.textContent = kind === "error" ? "System error" : "System note";

    const paragraph = document.createElement("p");
    paragraph.textContent = text;

    item.append(strong, paragraph);
    elements.transcriptList.prepend(item);
  }

  function updateProgress() {
    const questionCount = Math.max(1, state.history.length + (state.currentQuestion ? 1 : 0));
    const percent = Math.min(100, Math.round((state.history.length / 8) * 100));
    elements.progressFill.style.width = `${percent}%`;
    elements.progressLabel.textContent = `${state.history.length} / 8 rounds`;
    elements.roundMetric.textContent = String(state.history.length);
    elements.scoreMetric.textContent = state.history.length ? String(state.history[state.history.length - 1].score ?? "-") : "-";
    elements.difficultyBadge.textContent = `${state.difficulty} / 10`;
    if (state.history.length === 0 && state.currentQuestion) {
      elements.scoreMetric.textContent = "-";
    }
  }

  async function speakQuestion(text) {
    if (!state.voiceMode) {
      return;
    }

    try {
      audioHandler.setStatus("Speaking", "The AI interviewer is reading the prompt aloud.");
      await audioHandler.speak(text);
      audioHandler.setStatus("Idle", "Prompt delivered. Respond when ready.");
    } catch (error) {
      renderSystemMessage(error.message || "Unable to play the question audio.", "error");
    }
  }

  async function generateQuestion() {
    elements.sessionMetric.textContent = "Generating";
    elements.startQuestionBtn.disabled = true;
    elements.generateFollowUpBtn.disabled = true;

    try {
      const response = await fetch(endpoints.generateQuestion, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_profile: state.resumeProfile,
          job_description: state.jobDescription,
          session_history: state.history,
          difficulty: state.difficulty,
        }),
      });

      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Unable to generate the next question.");
      }

      state.currentQuestion = payload.question;
      state.difficulty = payload.difficulty || state.difficulty;
      elements.sessionMetric.textContent = "Live";
      renderQuestion(payload.question);
      renderSystemMessage("New interviewer prompt loaded.");
    } catch (error) {
      renderSystemMessage(error.message, "error");
      elements.sessionMetric.textContent = "Error";
    } finally {
      elements.startQuestionBtn.disabled = false;
      elements.generateFollowUpBtn.disabled = false;
      updateProgress();
    }
  }

  async function submitAnswer(answerText, options = {}) {
    const answer = answerText.trim();
    if (!answer) {
      renderSystemMessage("Write or speak an answer before submitting.", "error");
      return;
    }

    if (!state.currentQuestion) {
      await generateQuestion();
      return;
    }

    // If not explicitly provided, infer whether this submission originated from a voice transcript
    if (typeof options.fromVoice === "undefined") {
      options.fromVoice = elements.submitAnswerBtn.dataset.pendingVoice === "1";
    }

    elements.sessionMetric.textContent = "Scoring";
    renderTranscriptItem("user", "You", answer, { tag: options.fromVoice ? "Voice" : "Typed" });
    elements.submitAnswerBtn.disabled = true;
    elements.transcribeBtn.disabled = true;
    elements.startQuestionBtn.disabled = true;

    try {
      const response = await fetch(endpoints.processAnswer, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answer,
          current_question: state.currentQuestion,
          session_history: state.history,
          resume_profile: state.resumeProfile,
          job_description: state.jobDescription,
          difficulty: state.difficulty,
        }),
      });

      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Unable to process the answer.");
      }

      const evaluation = payload.evaluation;
      state.history.push({
        question: state.currentQuestion.prompt,
        answer,
        score: evaluation.score,
        kind: state.currentQuestion.kind,
      });
      state.difficulty = payload.difficulty || state.difficulty;

      renderTranscriptItem(
        "ai",
        `Score ${evaluation.score}/10`,
        payload.feedback || evaluation.reasoning || "Feedback generated.",
        { tag: evaluation.gaps?.[0] || "Adaptive feedback" }
      );

      elements.coachNotes.innerHTML = "";
      (evaluation.strengths || ["Keep tightening the answer structure."]).slice(0, 3).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        elements.coachNotes.appendChild(li);
      });

      state.currentQuestion = payload.next_question;
      renderQuestion(payload.next_question);
      elements.questionScore.textContent = `Scored ${evaluation.score}/10`;
      elements.scoreMetric.textContent = String(evaluation.score);
      elements.sessionMetric.textContent = "Live";
      updateProgress();
      await speakQuestion(payload.next_question.prompt);
    } catch (error) {
      renderSystemMessage(error.message || "Submission failed.", "error");
      elements.sessionMetric.textContent = "Error";
    } finally {
      elements.submitAnswerBtn.disabled = false;
      elements.transcribeBtn.disabled = false;
      elements.startQuestionBtn.disabled = false;
      elements.answerInput.value = "";
      // clear pending voice marker after submission
      delete elements.submitAnswerBtn.dataset.pendingVoice;
    }
  }

  function resetSession() {
    state.history = [];
    state.currentQuestion = null;
    state.sessionStartedAt = null;
    stopTimer();
    elements.transcriptList.innerHTML = "";
    elements.answerInput.value = "";
    elements.questionKind.textContent = "Waiting";
    elements.questionText.textContent = "Start the interview to receive a challenging first question.";
    elements.questionHint.textContent = "Your interviewer will focus on tradeoffs, outcomes, and the reasoning behind your choices.";
    elements.questionDifficulty.textContent = `D${state.difficulty}`;
    elements.questionScore.textContent = "Ready";
    elements.nextQuestionPreview.querySelector("strong").textContent = "Generate a question to reveal the next challenge.";
    elements.progressFill.style.width = "0%";
    elements.progressLabel.textContent = "0 / 8 rounds";
    elements.roundMetric.textContent = "0";
    elements.scoreMetric.textContent = "-";
    elements.sessionMetric.textContent = "Idle";
    elements.audioStatus.textContent = "Idle";
    elements.audioSubStatus.textContent = "Press the mic to record a spoken answer.";
    elements.coachNotes.innerHTML = `
      <li>Lead with the decision.</li>
      <li>Explain the tradeoff.</li>
      <li>Close with the measurable outcome.</li>
    `;
  }

  async function handleVoiceCapture() {
    try {
      await audioHandler.toggleRecording();
    } catch (error) {
      renderSystemMessage(error.message || "Could not access the microphone.", "error");
    }
  }

  elements.startQuestionBtn.addEventListener("click", generateQuestion);
  elements.generateFollowUpBtn.addEventListener("click", generateQuestion);
  elements.submitAnswerBtn.addEventListener("click", () => submitAnswer(elements.answerInput.value));
  elements.clearAnswerBtn.addEventListener("click", () => {
    elements.answerInput.value = "";
    audioHandler.setStatus("Idle", "Answer cleared.");
  });
  elements.micButton.addEventListener("click", handleVoiceCapture);
  elements.transcribeBtn.addEventListener("click", handleVoiceCapture);
  elements.speakQuestionBtn.addEventListener("click", () => {
    if (state.currentQuestion) {
      speakQuestion(state.currentQuestion.prompt);
    }
  });
  elements.voiceModeToggle.addEventListener("click", () => {
    state.voiceMode = !state.voiceMode;
    elements.voiceModeToggle.textContent = state.voiceMode ? "Voice mode on" : "Voice mode off";
    elements.voiceModeToggle.setAttribute("aria-pressed", String(state.voiceMode));
    elements.voiceMetric.textContent = state.voiceMode ? "On" : "Off";
  });
  elements.resetSessionBtn.addEventListener("click", resetSession);

  if (state.currentQuestion) {
    renderQuestion(state.currentQuestion, false);
    renderTranscriptItem("ai", "Interviewer", state.currentQuestion.prompt, { tag: "Ready" });
  } else {
    updateProgress();
  }

  if (state.currentQuestion) {
    startTimer();
  }

  updateProgress();
  elements.audioStatus.textContent = "Idle";
  elements.audioSubStatus.textContent = "Press the mic to record a spoken answer.";
});