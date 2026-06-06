document.addEventListener("DOMContentLoaded", () => {
  const bootstrapState = window.__INTERVIEW_BOOTSTRAP__ || {};
  
  // Build initial state for navigable Option B
  const initialHistory = bootstrapState.interviewState?.history || [];
  const currentQ = bootstrapState.initialQuestion || bootstrapState.interviewState?.current_question || null;
  
  const questions = initialHistory.map(h => ({
    question: { prompt: h.question, kind: h.kind },
    draftAnswer: h.answer,
    score: h.score,
    evaluated: true,
    modified: false
  }));
  
  if (currentQ) {
    questions.push({
      question: currentQ,
      draftAnswer: "",
      score: null,
      evaluated: false,
      modified: false
    });
  }
  
  const state = {
    resumeProfile: bootstrapState.interviewState?.resume_profile || {},
    jobDescription: bootstrapState.interviewState?.job_description || {},
    history: initialHistory,
    questions: questions,
    activeIndex: questions.length > 0 ? questions.length - 1 : 0,
    difficulty: bootstrapState.interviewState?.difficulty || 5,
    voiceMode: true,
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
    prevQuestionBtn: document.getElementById("prevQuestionBtn"),
    nextQuestionBtn: document.getElementById("nextQuestionBtn"),
    finishInterviewBtn: document.getElementById("finishInterviewBtn"),
    generateFollowUpBtn: document.getElementById("generateFollowUpBtn"),
    modifiedBadge: document.getElementById("modifiedBadge"),
    micButton: document.getElementById("micButton"),
    waveform: document.getElementById("waveform"),
    audioStatus: document.getElementById("audioStatus"),
    audioSubStatus: document.getElementById("audioSubStatus"),
    answerInput: document.getElementById("answerInput"),
    transcribeBtn: document.getElementById("transcribeBtn"),
    submitAnswerBtn: document.getElementById("submitAnswerBtn"),
    submitAnswerBtnText: document.getElementById("submitAnswerBtnText"),
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
      elements.answerInput.value = transcript;
      elements.audioSubStatus.textContent = "Transcript ready. Edit if needed.";
      elements.submitAnswerBtn.dataset.pendingVoice = "1";
      elements.submitAnswerBtn.disabled = false;
      if (elements.submitAnswerBtnText) elements.submitAnswerBtnText.disabled = false;
      saveCurrentDraft();
    },
    onStateChange: ({ recording, speaking }) => {
      elements.voiceMetric.textContent = recording ? "Recording" : speaking ? "Speaking" : "Off";
    },
    onError: (error) => {
      renderSystemMessage(error.message || "Audio processing failed.", "error");
    },
  });

  function saveCurrentDraft() {
    if (state.questions.length > 0) {
      const q = state.questions[state.activeIndex];
      const val = elements.answerInput.value;
      if (q.evaluated && q.draftAnswer !== val) {
        q.modified = true;
      }
      q.draftAnswer = val;
      updateBadgeVisibility();
    }
  }

  function updateBadgeVisibility() {
    if (state.questions.length > 0 && state.questions[state.activeIndex].modified && elements.modifiedBadge) {
      elements.modifiedBadge.style.display = 'inline-block';
    } else if (elements.modifiedBadge) {
      elements.modifiedBadge.style.display = 'none';
    }
  }

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
    if (!state.timerHandle) {
      state.sessionStartedAt = state.sessionStartedAt || Date.now();
      updateTimer();
      state.timerHandle = window.setInterval(updateTimer, 1000);
    }
  }

  function stopTimer() {
    if (state.timerHandle) {
      window.clearInterval(state.timerHandle);
      state.timerHandle = null;
    }
  }

  function renderQuestion(qObj, animate = true) {
    if (!qObj || !qObj.question) return;

    const apply = () => {
      const question = qObj.question;
      elements.questionKind.textContent = question.kind || "adaptive";
      elements.questionText.textContent = question.prompt || "No question available.";
      elements.questionDifficulty.textContent = `D${question.difficulty || state.difficulty}`;
      elements.questionScore.textContent = question.trap ? "Trap" : "Live";
      elements.questionHint.textContent = question.trap
        ? "This one is designed to test your assumptions."
        : "Answer like you are in a senior interview: precise, concise, and rooted in tradeoffs.";
      elements.difficultyBadge.textContent = `${question.difficulty || state.difficulty} / 10`;
      elements.sessionMetric.textContent = question.trap ? "Trap mode" : "Live";
      
      elements.questionCard.classList.remove("transition-out");
      elements.questionCard.classList.add("transition-in");
      window.setTimeout(() => elements.questionCard.classList.remove("transition-in"), 320);
      
      elements.answerInput.value = qObj.draftAnswer || "";
      
      updateBadgeVisibility();
      updateProgress();
      updateNavigationButtons();
      
      if (!qObj.evaluated) {
        startTimer();
      }
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
    const totalMax = 15;
    const activeDisplay = state.questions.length > 0 ? state.activeIndex + 1 : 0;
    const percent = Math.min(100, Math.round((activeDisplay / totalMax) * 100));
    elements.progressFill.style.width = `${percent}%`;
    elements.progressLabel.textContent = `Question ${activeDisplay} of ${totalMax}`;
    elements.roundMetric.textContent = String(activeDisplay);
    elements.difficultyBadge.textContent = `${state.difficulty} / 10`;
  }

  function updateNavigationButtons() {
    // Previous Button
    if (state.activeIndex <= 0) {
      elements.prevQuestionBtn.disabled = true;
    } else {
      elements.prevQuestionBtn.disabled = false;
    }

    // Finish / Next logic
    if (state.questions.length >= 15 && state.activeIndex === 14) {
      elements.nextQuestionBtn.style.display = 'none';
      elements.finishInterviewBtn.style.display = 'inline-block';
    } else {
      elements.nextQuestionBtn.style.display = 'inline-block';
      elements.finishInterviewBtn.style.display = 'none';
    }

    // If it's an already evaluated question, Next Question is just a local jump. 
    // If it's the latest question and NOT evaluated, Next Question submits it.
  }

  async function speakQuestion(text) {
    if (!state.voiceMode) return;
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
    if (elements.nextQuestionBtn) elements.nextQuestionBtn.disabled = true;

    try {
      // Rebuild history from state.questions strictly for generating the next adaptative step
      const tempHistory = state.questions.filter(q => q.evaluated).map(q => ({
        question: q.question.prompt,
        answer: q.draftAnswer,
        score: q.score,
        kind: q.question.kind
      }));

      const response = await fetch(endpoints.generateQuestion, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_profile: state.resumeProfile,
          job_description: state.jobDescription,
          session_history: tempHistory,
          difficulty: state.difficulty,
        }),
      });

      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Unable to generate the next question.");

      const newQ = {
        question: payload.question,
        draftAnswer: "",
        score: null,
        evaluated: false,
        modified: false
      };
      state.questions.push(newQ);
      state.activeIndex = state.questions.length - 1;
      state.difficulty = payload.difficulty || state.difficulty;
      elements.sessionMetric.textContent = "Live";
      
      renderQuestion(state.questions[state.activeIndex]);
      renderSystemMessage("New interviewer prompt loaded.");
      speakQuestion(payload.question.prompt);
    } catch (error) {
      renderSystemMessage(error.message, "error");
      elements.sessionMetric.textContent = "Error";
    } finally {
      elements.startQuestionBtn.disabled = false;
      if (elements.nextQuestionBtn) elements.nextQuestionBtn.disabled = false;
      updateProgress();
      updateNavigationButtons();
    }
  }

  async function submitAnswer(options = {}) {
    saveCurrentDraft();
    const qObj = state.questions[state.activeIndex];
    const answer = qObj.draftAnswer.trim();
    
    if (!answer) {
      renderSystemMessage("Write or speak an answer before submitting.", "error");
      return;
    }

    elements.sessionMetric.textContent = "Scoring";
    elements.submitAnswerBtn.disabled = true;
    elements.transcribeBtn.disabled = true;
    if (elements.nextQuestionBtn) elements.nextQuestionBtn.disabled = true;

    try {
      const tempHistory = state.questions.filter(q => q.evaluated).map(q => ({
        question: q.question.prompt,
        answer: q.draftAnswer,
        score: q.score,
        kind: q.question.kind
      }));

      const response = await fetch(endpoints.processAnswer, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answer,
          current_question: qObj.question,
          session_history: tempHistory,
          resume_profile: state.resumeProfile,
          job_description: state.jobDescription,
          difficulty: state.difficulty,
        }),
      });

      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Unable to process the answer.");

      const evaluation = payload.evaluation;
      qObj.score = evaluation.score;
      qObj.evaluated = true;
      state.difficulty = payload.difficulty || state.difficulty;
      
      // We don't push to state.history anymore, we just mark current as evaluated.
      // The backend returns a next_question, we push it to state.questions!
      if (state.questions.length < 15) {
        const nextQ = {
          question: payload.next_question,
          draftAnswer: "",
          score: null,
          evaluated: false,
          modified: false
        };
        state.questions.push(nextQ);
        state.activeIndex = state.questions.length - 1;
        renderQuestion(state.questions[state.activeIndex]);
        speakQuestion(payload.next_question.prompt);
      } else {
        renderSystemMessage("Interview completed. Please finish the interview to download your report.", "info");
        updateNavigationButtons();
      }

    } catch (error) {
      renderSystemMessage(error.message || "Submission failed.", "error");
      elements.sessionMetric.textContent = "Error";
    } finally {
      elements.submitAnswerBtn.disabled = false;
      elements.transcribeBtn.disabled = false;
      if (elements.nextQuestionBtn) elements.nextQuestionBtn.disabled = false;
      delete elements.submitAnswerBtn.dataset.pendingVoice;
    }
  }

  function goPrevious() {
    saveCurrentDraft();
    if (state.activeIndex > 0) {
      state.activeIndex--;
      renderQuestion(state.questions[state.activeIndex]);
    }
  }

  function goNext() {
    saveCurrentDraft();
    const qObj = state.questions[state.activeIndex];
    
    // Case 1: Viewing an old evaluated question, jump to next without API call
    if (qObj.evaluated && state.activeIndex < state.questions.length - 1) {
      state.activeIndex++;
      renderQuestion(state.questions[state.activeIndex]);
    } 
    // Case 2: Latest question, submit and generate
    else if (!qObj.evaluated) {
      submitAnswer();
    }
    // Case 3: Editing latest question but it's evaluated? Just jump if available.
  }

  function resetSession() {
    state.history = [];
    state.questions = [];
    state.activeIndex = 0;
    state.sessionStartedAt = null;
    stopTimer();
    elements.transcriptList.innerHTML = "";
    elements.answerInput.value = "";
    elements.progressFill.style.width = "0%";
    elements.progressLabel.textContent = "Question 0 of 15";
    elements.audioStatus.textContent = "Idle";
    elements.audioSubStatus.textContent = "Press the mic to record a spoken answer.";
  }

  async function handleVoiceCapture() {
    try {
      await audioHandler.toggleRecording();
    } catch (error) {
      renderSystemMessage(error.message || "Could not access the microphone.", "error");
    }
  }

  // Bindings
  elements.startQuestionBtn.addEventListener("click", generateQuestion);
  if (elements.prevQuestionBtn) elements.prevQuestionBtn.addEventListener("click", goPrevious);
  if (elements.nextQuestionBtn) elements.nextQuestionBtn.addEventListener("click", goNext);
  
  if (elements.finishInterviewBtn) {
    elements.finishInterviewBtn.addEventListener("click", async () => {
      saveCurrentDraft();
      elements.finishInterviewBtn.disabled = true;
      elements.finishInterviewBtn.innerHTML = 'Finishing <i class="bi bi-hourglass-split"></i>';
      
      const tempHistory = state.questions.filter(q => q.evaluated).map(q => ({
        question: q.question.prompt,
        answer: q.draftAnswer,
        score: q.score,
        kind: q.question.kind
      }));

      try {
        await fetch('/api/interview/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_history: tempHistory })
        });
      } catch (e) {
        console.error("Sync failed:", e);
      }
      
      window.location.href = '/reports/latest';
    });
  }

  // Answer saving on typing
  if (elements.answerInput) {
    elements.answerInput.addEventListener("input", () => {
      const hasText = !!elements.answerInput.value.trim();
      if (elements.submitAnswerBtnText) elements.submitAnswerBtnText.disabled = !hasText;
      saveCurrentDraft();
    });
  }

  if (elements.submitAnswerBtn) elements.submitAnswerBtn.addEventListener("click", () => goNext());
  if (elements.submitAnswerBtnText) elements.submitAnswerBtnText.addEventListener("click", () => goNext());

  elements.clearAnswerBtn.addEventListener("click", () => {
    elements.answerInput.value = "";
    saveCurrentDraft();
    if (elements.submitAnswerBtnText) elements.submitAnswerBtnText.disabled = true;
    audioHandler.setStatus("Idle", "Answer cleared.");
  });
  
  elements.micButton.addEventListener("click", handleVoiceCapture);
  elements.transcribeBtn.addEventListener("click", handleVoiceCapture);
  elements.speakQuestionBtn.addEventListener("click", () => {
    if (state.questions[state.activeIndex]) {
      speakQuestion(state.questions[state.activeIndex].question.prompt);
    }
  });

  elements.resetSessionBtn.addEventListener("click", resetSession);

  // Init
  if (state.questions.length > 0) {
    renderQuestion(state.questions[state.activeIndex], false);
  } else {
    updateProgress();
  }

  elements.audioStatus.textContent = "Idle";
  elements.audioSubStatus.textContent = "Press the mic to record a spoken answer.";
});