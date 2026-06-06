document.addEventListener("DOMContentLoaded", () => {
  // --- State Variables ---
  let resumeUploaded = false;
  let jdUploaded = false;
  
  let resumeData = null;
  let jdData = null;

  // --- Element Selectors ---
  // Step Indicators
  const step1Indicator = document.getElementById("step1Indicator");
  const step2Indicator = document.getElementById("step2Indicator");

  // Step 1 Views
  const uploadStepContent = document.getElementById("uploadStepContent");
  const analyzeBtn = document.getElementById("analyzeBtn");

  // Step 2 Views
  const analysisStepContent = document.getElementById("analysisStepContent");
  const resultsAreaInner = document.getElementById("resultsAreaInner");
  const resultsRoleTitle = document.getElementById("resultsRoleTitle");
  const btnRestartReview = document.getElementById("btnRestartReview");

  // Resume Upload Elements
  const resumeDropZone = document.getElementById("resumeDropZone");
  const resumeInput = document.getElementById("resumeInput");
  const resumeChooseBtn = document.getElementById("resumeChooseBtn");
  const resumePreview = document.getElementById("resumePreview");
  const resumeFileName = document.getElementById("resumeFileName");
  const resumeFileSize = document.getElementById("resumeFileSize");
  const resumeRemoveBtn = document.getElementById("resumeRemoveBtn");
  const resumeReplaceBtn = document.getElementById("resumeReplaceBtn");

  // Job Description Upload Elements
  const jdDropZone = document.getElementById("jdDropZone");
  const jdInput = document.getElementById("jdInput");
  const jdChooseBtn = document.getElementById("jdChooseBtn");
  const jdPreview = document.getElementById("jdPreview");
  const jdFileName = document.getElementById("jdFileName");
  const jdFileSize = document.getElementById("jdFileSize");
  const jdRemoveBtn = document.getElementById("jdRemoveBtn");
  const jdReplaceBtn = document.getElementById("jdReplaceBtn");

  // AI Processing Overlay Elements
  const processingOverlay = document.getElementById("processingOverlay");
  const overlayPercent = document.getElementById("overlayPercent");
  const overlayStatusTitle = document.getElementById("overlayStatusTitle");
  const overlayStatusDesc = document.getElementById("overlayStatusDesc");
  const overlayProgressBarFill = document.getElementById("overlayProgressBarFill");

  // --- Helper Functions ---
  const formatBytes = (bytes) => {
    if (!bytes) return "0 KB";
    const units = ["bytes", "KB", "MB", "GB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
  };

  const getFlattenedResumeSkills = (skills) => {
    if (!skills) return [];
    if (Array.isArray(skills)) return skills;
    if (typeof skills === 'object') {
      return Object.values(skills).reduce((acc, val) => {
        if (Array.isArray(val)) {
          return acc.concat(val);
        }
        return acc;
      }, []);
    }
    return [];
  };

  const updateAnalyzeButtonState = () => {
    if (resumeUploaded && jdUploaded) {
      analyzeBtn.disabled = false;
    } else {
      analyzeBtn.disabled = true;
    }
  };

  // --- Preloaded/Session State Initialization ---
  const initSessionState = () => {
    // Expose preloaded values if session contains parsed objects
    if (window.__SESSION_RESUME__) {
      resumeData = window.__SESSION_RESUME__;
      resumeUploaded = true;
      
      // Update Resume Preview card
      resumeFileName.textContent = "resume_profile.pdf (Parsed)";
      resumeFileSize.textContent = `Skills extracted: ${resumeData.skills ? resumeData.skills.length : 0}`;
      resumeDropZone.style.display = "none";
      resumePreview.style.display = "flex";
    }

    if (window.__SESSION_JD__) {
      jdData = window.__SESSION_JD__;
      jdUploaded = true;

      // Update JD Preview card
      jdFileName.textContent = "job_description.pdf (Parsed)";
      jdFileSize.textContent = `Required skills: ${jdData.required_skills ? jdData.required_skills.length : 0}`;
      jdDropZone.style.display = "none";
      jdPreview.style.display = "flex";
    }

    updateAnalyzeButtonState();
  };

  // --- AJAX File Upload Controller ---
  const uploadFile = (file, documentType) => {
    if (!file) return;

    // Check size limit: 5 MB
    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) {
      alert("File is too large. Max size is 5 MB.");
      return;
    }

    // Target elements depending on type
    const isResume = documentType === "resume";
    const dropZone = isResume ? resumeDropZone : jdDropZone;
    const previewCard = isResume ? resumePreview : jdPreview;
    const fileNameEl = isResume ? resumeFileName : jdFileName;
    const fileSizeEl = isResume ? resumeFileSize : jdFileSize;
    const fileInputEl = isResume ? resumeInput : jdInput;

    // Update dropzone during upload
    const originalDropText = dropZone.querySelector(".drop-text").textContent;
    dropZone.querySelector(".drop-text").textContent = "Parsing File Async...";
    dropZone.querySelector(".drop-illustration").style.transform = "scale(1.1) translateY(-4px)";

    const formData = new FormData();
    formData.append("document", file);
    formData.append("document_type", documentType);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload", true);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    xhr.onreadystatechange = () => {
      if (xhr.readyState !== 4) return;

      // Reset dropzone state text
      dropZone.querySelector(".drop-text").textContent = originalDropText;
      dropZone.querySelector(".drop-illustration").style.transform = "none";

      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText);
          if (response.ok) {
            // Update state
            if (isResume) {
              resumeUploaded = true;
              resumeData = response.result.summary || {};
            } else {
              jdUploaded = true;
              jdData = response.result.summary || {};
            }

            // Update previews
            fileNameEl.textContent = file.name;
            fileSizeEl.textContent = `${file.type || "Document"} · ${formatBytes(file.size)}`;
            
            // Toggle visibility
            dropZone.style.display = "none";
            previewCard.style.display = "flex";

            updateAnalyzeButtonState();
          } else {
            alert(response.error || "Parsing failed. Please verify document integrity.");
            fileInputEl.value = "";
          }
        } catch (error) {
          alert("The server returned an unexpected response.");
          fileInputEl.value = "";
        }
      } else {
        alert("Upload failed. Verify server status.");
        fileInputEl.value = "";
      }
    };

    xhr.send(formData);
  };

  // --- Resume Event Listeners ---
  resumeChooseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    resumeInput.click();
  });

  resumeInput.addEventListener("change", () => {
    if (resumeInput.files && resumeInput.files[0]) {
      uploadFile(resumeInput.files[0], "resume");
    }
  });

  resumeRemoveBtn.addEventListener("click", () => {
    resumeInput.value = "";
    resumeUploaded = false;
    resumeData = null;
    resumePreview.style.display = "none";
    resumeDropZone.style.display = "flex";
    updateAnalyzeButtonState();
  });

  resumeReplaceBtn.addEventListener("click", () => {
    resumeInput.click();
  });

  resumeDropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    resumeDropZone.classList.add("dragover");
  });

  resumeDropZone.addEventListener("dragleave", () => {
    resumeDropZone.classList.remove("dragover");
  });

  resumeDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    resumeDropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      resumeInput.files = e.dataTransfer.files;
      uploadFile(e.dataTransfer.files[0], "resume");
    }
  });

  // --- JD Event Listeners ---
  jdChooseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    jdInput.click();
  });

  jdInput.addEventListener("change", () => {
    if (jdInput.files && jdInput.files[0]) {
      uploadFile(jdInput.files[0], "jd");
    }
  });

  jdRemoveBtn.addEventListener("click", () => {
    jdInput.value = "";
    jdUploaded = false;
    jdData = null;
    jdPreview.style.display = "none";
    jdDropZone.style.display = "flex";
    updateAnalyzeButtonState();
  });

  jdReplaceBtn.addEventListener("click", () => {
    jdInput.click();
  });

  jdDropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    jdDropZone.classList.add("dragover");
  });

  jdDropZone.addEventListener("dragleave", () => {
    jdDropZone.classList.remove("dragover");
  });

  jdDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    jdDropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      jdInput.files = e.dataTransfer.files;
      uploadFile(e.dataTransfer.files[0], "jd");
    }
  });

  // --- HTML Parsed Results Renderer (Step 2) ---
  const renderAnalysisResults = (scores) => {
    const resumeSkills = getFlattenedResumeSkills(resumeData ? resumeData.skills : []);
    const jdSkills = jdData ? (jdData.required_skills || jdData.skills || []) : [];
    const resumeProjects = resumeData ? (resumeData.projects || []) : [];
    const resumeExperience = resumeData ? (resumeData.experience || []) : [];
    const jdResponsibilities = jdData ? (jdData.responsibilities || []) : [];
    
    // Normalize casing for overlap matching
    const normResumeSkills = resumeSkills.map(s => s.toLowerCase());
    const matchedSkills = jdSkills.filter(s => normResumeSkills.includes(s.toLowerCase()));
    const missingSkills = jdSkills.filter(s => !normResumeSkills.includes(s.toLowerCase()));

    // Generate Skills Table Rows
    const skillsListHTML = jdSkills.map(skill => {
      const isMatched = normResumeSkills.includes(skill.toLowerCase());
      return `
        <div class="match-skill-row" style="display: flex; align-items: center; justify-content: space-between; padding: 0.65rem 0.5rem; border-bottom: 1px solid #F1F5F9;">
          <span style="font-weight: 500; color: #334155; font-size: 0.9rem;">${skill}</span>
          ${isMatched 
            ? `<span style="color: #10B981; font-weight: 600; font-size: 0.85rem; display: flex; align-items: center; gap: 0.25rem;"><i class="bi bi-check-circle-fill"></i> Matched</span>`
            : `<span style="color: #F59E0B; font-weight: 600; font-size: 0.85rem; display: flex; align-items: center; gap: 0.25rem;"><i class="bi bi-exclamation-triangle-fill"></i> Missing Keyword</span>`
          }
        </div>
      `;
    }).join("");

    // Missing Gaps HTML
    const missingSkillsHTML = missingSkills.length > 0 
      ? missingSkills.map(s => `<span class="chip" style="background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.2); color: #D97706; padding: 0.4rem 0.75rem; border-radius: 99px; font-size: 0.8rem; font-weight: 600; border: 1px solid;">${s}</span>`).join("")
      : `<span style="color: #10B981; font-size: 0.9rem; font-weight: 500;"><i class="bi bi-check-all"></i> Awesome! No critical missing skills detected.</span>`;

    // Recommendations List HTML
    const recommendations = [
      `Incorporate measurable achievements using the <strong>X-Y-Z formula</strong> (e.g. Accomplished X as measured by Y by doing Z) into your projects.`,
      missingSkills.length > 0 
        ? `Explicitly reference missing keywords like <strong>${missingSkills.slice(0, 3).join(", ")}</strong> directly in your experience bullet points.`
        : `Your resume matches this JD extremely well. Focus on highlighting core architectural and system design patterns.`,
      `Add context about your team collaboration and scope of responsibilities for projects utilizing modern backend integrations.`,
      `Ensure that you upload a highly relevant target role description to get even tighter, localized AI feedback.`
    ];
    
    const recsHTML = recommendations.map(rec => `
      <li style="display: flex; gap: 0.75rem; align-items: flex-start;">
        <i class="bi bi-arrow-right-short text-primary" style="font-size: 1.25rem; margin-top: -0.1rem; flex-shrink:0;"></i>
        <span style="font-size: 0.9rem; color: #475569; line-height: 1.45;">${rec}</span>
      </li>
    `).join("");

    resultsAreaInner.innerHTML = `
      <div style="display: grid; grid-template-columns: 1fr; gap: 2rem;">
        
        <!-- Quick Insight Summary -->
        <article class="result-card glass-card" style="border: 1px solid #E2E8F0; border-radius: 20px; padding: 1.5rem;">
          <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0 0 0.75rem; color: #0F172A;">Match Overview</h3>
          <p style="font-size: 0.92rem; color: #475569; line-height: 1.6; margin: 0;">
            Our AI parser completed a structured alignment between your resume profile and the target role criteria. 
            We detected strong matches across <strong>${matchedSkills.length}</strong> core skills, while identifying 
            <strong>${missingSkills.length}</strong> critical keyword vacancies that might affect automated ATS compliance screening. 
            Review the breakdown and optimization steps below to prepare.
          </p>
        </article>

        <!-- Skills Table -->
        <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.5rem;">
          
          <article class="result-card glass-card" style="border: 1px solid #E2E8F0; border-radius: 20px; padding: 1.5rem;">
            <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0 0 1rem; color: #0F172A; display: flex; align-items: center; gap: 0.5rem;">
              <i class="bi bi-file-earmark-code" style="color: #2563EB;"></i> Resume Keywords
            </h3>
            <div class="chip-list" style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
              ${resumeSkills.map(s => `<span class="chip" style="background: rgba(37,99,235,0.05); border: 1px solid #E2E8F0; color: #334155; padding: 0.4rem 0.75rem; border-radius: 99px; font-size: 0.8rem; font-weight: 500;">${s}</span>`).join("")}
            </div>
          </article>

          <article class="result-card glass-card" style="border: 1px solid #E2E8F0; border-radius: 20px; padding: 1.5rem;">
            <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0 0 1rem; color: #0F172A; display: flex; align-items: center; gap: 0.5rem;">
              <i class="bi bi-list-task" style="color: #8B5CF6;"></i> Target Skills Alignment
            </h3>
            <div style="max-height: 250px; overflow-y: auto; padding-right: 0.25rem;">
              ${skillsListHTML || '<span style="color: #64748B; font-style: italic;">No specific target skills required.</span>'}
            </div>
          </article>

        </div>

        <!-- Missing Keyword Alert -->
        <article class="result-card glass-card" style="border: 1px solid #F59E0B; background: rgba(245, 158, 11, 0.01); border-radius: 20px; padding: 1.5rem;">
          <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0 0 0.5rem; color: #D97706; display: flex; align-items: center; gap: 0.5rem;">
            <i class="bi bi-exclamation-octagon-fill"></i> Missing Skills Detected
          </h3>
          <p style="font-size: 0.88rem; color: #64748B; margin: 0 0 1rem; line-height: 1.5;">
            These skills are highly requested in the job description but were not identified on your resume. Add these to avoid ATS filters.
          </p>
          <div class="chip-list" style="display: flex; flex-wrap: wrap; gap: 0.6rem;">
            ${missingSkillsHTML}
          </div>
        </article>

        <!-- Dynamic Recommendations Checklist -->
        <article class="result-card glass-card" style="border: 1px solid #E2E8F0; border-radius: 20px; padding: 1.5rem;">
          <h3 style="font-size: 1.1rem; font-weight: 700; margin: 0 0 1rem; color: #0F172A; display: flex; align-items: center; gap: 0.5rem;">
            <i class="bi bi-lightbulb" style="color: #10B981;"></i> Tailored Improvement Suggestions
          </h3>
          <ul class="recs-list" style="list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1rem;">
            ${recsHTML}
          </ul>
        </article>

      </div>
    `;
  };

  // --- Dynamic Processing Overlay Animation (Simulates AI deep analysis) ---
  const startAIDeepAnalysis = () => {
    processingOverlay.style.display = "flex";
    
    let progress = 0;
    const progressDuration = 3800; // 3.8 seconds total
    const updateInterval = 80;
    const stepsCount = progressDuration / updateInterval;
    const stepVal = 100 / stepsCount;

    const interval = setInterval(() => {
      progress += stepVal;
      const displayPercent = Math.min(100, Math.floor(progress));
      
      // Update UI Text & Percentage
      overlayPercent.textContent = `${displayPercent}%`;
      overlayProgressBarFill.style.width = `${displayPercent}%`;
      
      // Spinner SVG Dash Offset (Circle circumference is ~276.46)
      const circumference = 276.46;
      const offset = circumference - (displayPercent / 100) * circumference;
      const progressCircle = processingOverlay.querySelector(".spinner-progress-circle");
      if (progressCircle) {
        progressCircle.style.strokeDashoffset = offset;
      }

      // Cycle Progressive Analysis Status Phrases
      if (displayPercent < 20) {
        overlayStatusTitle.textContent = "Reading Resume...";
        overlayStatusDesc.textContent = "Parsing document text structure and scanning layouts...";
      } else if (displayPercent < 40) {
        overlayStatusTitle.textContent = "Analyzing Skills...";
        overlayStatusDesc.textContent = "Extracting technical tools, frameworks, and projects...";
      } else if (displayPercent < 60) {
        overlayStatusTitle.textContent = "Matching Job Description...";
        overlayStatusDesc.textContent = "Comparing resume assets with target role criteria...";
      } else if (displayPercent < 80) {
        overlayStatusTitle.textContent = "Calculating ATS Score...";
        overlayStatusDesc.textContent = "Detecting core keyword alignment and layout compatibility...";
      } else {
        overlayStatusTitle.textContent = "Generating Suggestions...";
        overlayStatusDesc.textContent = "Forging personalized, actionable resume improvements...";
      }

      if (progress >= 100) {
        clearInterval(interval);
        
        // Hide Overlay after completion delay
        setTimeout(() => {
          processingOverlay.style.display = "none";
          
          // Complete step transitions
          step1Indicator.classList.remove("active");
          step1Indicator.classList.add("completed");
          step2Indicator.classList.add("active");

          uploadStepContent.style.display = "none";
          analysisStepContent.style.display = "block";

          // Calculate and render dynamic matching outcomes
          const resumeSkills = getFlattenedResumeSkills(resumeData ? resumeData.skills : []);
          const jdSkills = jdData ? (jdData.required_skills || jdData.skills || []) : [];
          const normResumeSkills = resumeSkills.map(s => s.toLowerCase());
          const matchedSkills = jdSkills.filter(s => normResumeSkills.includes(s.toLowerCase()));

          // Overlap calculation formula:
          let calculatedMatch = 50;
          if (jdSkills.length > 0) {
            calculatedMatch = Math.round(60 + (matchedSkills.length / jdSkills.length) * 36);
          }
          const calculatedATS = Math.round(65 + Math.min(33, resumeSkills.length * 1.6));

          // Set Circle Metrics
          document.getElementById("matchScoreText").textContent = `${calculatedMatch}%`;
          document.getElementById("atsScoreText").textContent = `${calculatedATS}%`;

          // Circle Stroke Alignments
          const matchCircle = analysisStepContent.querySelector(".circle-match");
          const atsCircle = analysisStepContent.querySelector(".circle-ats");
          if (matchCircle) matchCircle.style.strokeDasharray = `${calculatedMatch}, 100`;
          if (atsCircle) atsCircle.style.strokeDasharray = `${calculatedATS}, 100`;

          // Set Title
          const targetRole = jdData ? (jdData.title || jdData.target_role || "Target Role") : "Target Role";
          resultsRoleTitle.textContent = `Alignment for ${targetRole}`;

          renderAnalysisResults();

          // Scroll to top of main contents
          window.scrollTo({ top: 0, behavior: "smooth" });
        }, 300);
      }
    }, updateInterval);
  };

  // --- Step 2 Return Transition ---
  btnRestartReview.addEventListener("click", () => {
    // Reset Indicators
    step2Indicator.classList.remove("active");
    step1Indicator.classList.remove("completed");
    step1Indicator.classList.add("active");

    // Toggle Content Views
    analysisStepContent.style.display = "none";
    uploadStepContent.style.display = "block";

    // Re-verify upload state
    updateAnalyzeButtonState();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // --- Click Handler for Analyze Button ---
  analyzeBtn.addEventListener("click", () => {
    startAIDeepAnalysis();
  });


  // ==========================================================================
  // FLOATING AI CHAT WIDGET CONTROLLER (BUG 3 INTEGRATION)
  // ==========================================================================
  const chatWidget = document.getElementById('chatWidget');
  const chatBody = document.getElementById('chatBody');
  const chatInput = document.getElementById('chatInput');
  const chatSend = document.getElementById('chatSend');
  
  const chatMinimize = document.getElementById('chatMinimize');
  const chatMaximize = document.getElementById('chatMaximize');
  const chatClose = document.getElementById('chatClose');

  const btnSidebarChat = document.querySelector('.btn-chat-ai');
  const btnRobotCardChat = document.getElementById('btnRobotCardChat');

  const openChatWidget = (customGreetingText) => {
    if (!chatWidget) return;
    chatWidget.style.display = 'flex';
    chatWidget.classList.remove('minimized');
    
    if (customGreetingText && chatBody) {
      // Append a customized contextual greeting
      appendMessage('bot', customGreetingText);
    }
    
    if (chatBody) chatBody.scrollTop = chatBody.scrollHeight;
  };

  // Sidebar Chat trigger
  if (btnSidebarChat) {
    btnSidebarChat.addEventListener('click', (e) => {
      e.stopPropagation();
      openChatWidget("Hi! How can I help you navigate your dashboard, setup interviews, or prepare your technical materials?");
    });
  }

  // Robot Card Chat trigger
  if (btnRobotCardChat) {
    btnRobotCardChat.addEventListener('click', (e) => {
      e.stopPropagation();
      openChatWidget("Hi! I notice you are reviewing your resume. Would you like some actionable advice on resolving missing keywords, explaining gap years, or restructuring project milestones?");
    });
  }

  // Chat window control actions
  if (chatClose) {
    chatClose.addEventListener('click', () => {
      chatWidget.style.display = 'none';
    });
  }

  if (chatMinimize) {
    chatMinimize.addEventListener('click', () => {
      chatWidget.classList.toggle('minimized');
    });
  }

  if (chatMaximize) {
    chatMaximize.addEventListener('click', () => {
      chatWidget.classList.toggle('maximized');
      if (chatWidget.classList.contains('maximized')) {
        chatMaximize.className = 'bi bi-fullscreen-exit';
      } else {
        chatMaximize.className = 'bi bi-fullscreen';
      }
    });
  }

  const initialMessages = [
    {
      sender: 'bot',
      text: "Hi! I'm your InterviewForge Assistant.<br><br>I can help you review your resume, format projects, find missing skills, or prepare for mock interviews.",
      suggestions: [
        "How is the match score computed?",
        "How do I optimize for ATS scanners?",
        "What formatting details does the AI look for?",
        "Can I start a practice interview immediately?"
      ]
    }
  ];

  function appendMessage(sender, text, suggestions = []) {
    if (!chatBody) return;
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${sender === 'bot' ? 'bot-msg' : 'user-msg'}`;
    msgDiv.innerHTML = text;

    if (suggestions.length > 0) {
      const suggestDiv = document.createElement('div');
      suggestDiv.className = 'chat-suggestions';
      suggestions.forEach(promptText => {
        const btn = document.createElement('button');
        btn.className = 'chat-suggestion-btn';
        btn.innerText = promptText;
        btn.addEventListener('click', () => {
          handleUserInput(promptText);
        });
        suggestDiv.appendChild(btn);
      });
      msgDiv.appendChild(suggestDiv);
    }

    chatBody.appendChild(msgDiv);
    chatBody.scrollTo({
      top: chatBody.scrollHeight,
      behavior: 'smooth'
    });
  }

  let typingIndicator = null;

  function showTypingIndicator() {
    if (typingIndicator || !chatBody) return;
    
    typingIndicator = document.createElement('div');
    typingIndicator.className = 'typing-indicator';
    typingIndicator.innerHTML = `
      <span>Assistant is typing</span>
      <div class="typing-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
    `;
    chatBody.appendChild(typingIndicator);
    chatBody.scrollTo({
      top: chatBody.scrollHeight,
      behavior: 'smooth'
    });
  }

  function hideTypingIndicator() {
    if (typingIndicator) {
      typingIndicator.remove();
      typingIndicator = null;
    }
  }

  async function handleUserInput(text) {
    if (!text.trim()) return;

    appendMessage('user', text);
    if (chatInput) chatInput.value = '';

    showTypingIndicator();

    try {
      const response = await fetch('/api/chat-assistant', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: text })
      });

      const data = await response.json();
      
      setTimeout(() => {
        hideTypingIndicator();
        if (data.ok) {
          appendMessage('bot', data.reply);
        } else {
          appendMessage('bot', "Sorry, I encountered an issue retrieving the response. Please try again.");
        }
      }, 1000);

    } catch (err) {
      setTimeout(() => {
        hideTypingIndicator();
        appendMessage('bot', "Offline fallback: InterviewForge is designed to help you prepare for technical interviews using adaptive question flows, automated scoring, and detailed roadmap checklists. Let me know what specific page or feature you need help with!");
      }, 1000);
    }
  }

  if (chatSend && chatInput) {
    chatSend.addEventListener('click', () => {
      handleUserInput(chatInput.value);
    });

    chatInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        handleUserInput(chatInput.value);
      }
    });
  }

  if (chatBody) {
    chatBody.innerHTML = '';
    initialMessages.forEach(m => {
      appendMessage(m.sender, m.text, m.suggestions);
    });
  }


  // --- Start Session & View Initialization ---
  initSessionState();
});