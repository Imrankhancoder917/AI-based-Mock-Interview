document.addEventListener("DOMContentLoaded", () => {
  const toggles = document.querySelectorAll("[data-toggle-password]");

  toggles.forEach((toggle) => {
    toggle.addEventListener("click", () => {
      const targetId = toggle.getAttribute("data-target");
      const input = targetId ? document.getElementById(targetId) : null;

      if (!input) {
        return;
      }

      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      toggle.textContent = isPassword ? "Hide" : "Show";
    });
  });

  const forms = document.querySelectorAll(".auth-form");

  forms.forEach((form) => {
    // We only attach the basic confirm password logic if it's the register form
    if (form.querySelector('#confirm_password')) {
      form.addEventListener("submit", (event) => {
        const password = form.querySelector('#password');
        const confirmPassword = form.querySelector('#confirm_password');

        if (password && confirmPassword && password.value !== confirmPassword.value) {
          event.preventDefault();
          confirmPassword.classList.add("is-invalid");
          confirmPassword.focus();
        }
      });
    }
  });

  // --- Robot Receptionist Logic ---
  const speechBubble = document.getElementById('robot-speech');
  const speechText = document.getElementById('robot-speech-text');
  const robotAvatar = document.getElementById('login-robot');
  const waveform = document.getElementById('voice-waveform');
  const authForm = document.querySelector('form.auth-form');

  if (speechBubble && speechText && robotAvatar && authForm) {
    const isRegister = !!authForm.querySelector('#confirm_password');
    let isProcessing = false;

    // Time-based greeting logic for login
    function getDynamicGreeting() {
      const hour = new Date().getHours();
      if (hour >= 5 && hour < 12) return "Good Morning. Ready for today's interview?";
      if (hour >= 12 && hour < 17) return "Welcome back. Let's continue your preparation.";
      if (hour >= 17 && hour < 22) return "Good Evening. Your AI interviewer is ready.";
      return "Burning the midnight oil? Let's practice.";
    }

    // Default Messages
    const loginMessages = [
      "Ready for your next mock interview?",
      "Your AI interviewer is waiting.",
      "Let's prepare for your dream job.",
      "Resume analysis and interview practice in one place.",
      "Your interview workspace is ready."
    ];
    const registerMessages = [
      "Your journey to better interviews starts here.",
      "Create your account and unlock AI-powered preparation.",
      "Let's build your interview profile."
    ];
    
    const defaultMessages = isRegister ? registerMessages : loginMessages;
    let msgIndex = 0;

    // Set initial text
    if (!isRegister) {
      speechText.textContent = getDynamicGreeting();
    } else {
      speechText.textContent = "Welcome to InterviewForge. Let's create your AI interview workspace.";
    }

    // Initial welcome fade-in
    setTimeout(() => {
      speechBubble.classList.add('visible');
    }, 500);

    // Rotate messages
    const messageInterval = setInterval(() => {
      if (isProcessing) return;
      speechBubble.classList.remove('visible');
      setTimeout(() => {
        if (isProcessing) return;
        speechText.textContent = defaultMessages[msgIndex];
        msgIndex = (msgIndex + 1) % defaultMessages.length;
        speechBubble.classList.add('visible');
      }, 400);
    }, 5000);

    function setRobotState(state, message) {
      speechBubble.classList.remove('visible');
      
      setTimeout(() => {
        speechText.textContent = message;
        robotAvatar.classList.remove('robot-error-state', 'robot-success-state');
        
        if (state === 'error') {
          robotAvatar.classList.add('robot-error-state');
          waveform.classList.replace('speaking', 'idle');
        } else if (state === 'success') {
          robotAvatar.classList.add('robot-success-state');
          waveform.classList.replace('idle', 'speaking');
        } else if (state === 'processing') {
          waveform.classList.replace('idle', 'speaking');
        } else {
          waveform.classList.replace('idle', 'speaking');
        }
        
        speechBubble.classList.add('visible');
      }, 400);
    }

    // TTS playback helper
    async function playRobotVoice(text) {
      try {
        const res = await fetch('/api/speech/respond', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: text })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.ok && data.audio) {
            const audio = new Audio("data:audio/mp3;base64," + data.audio);
            audio.play();
          }
        }
      } catch (err) {
        console.error("Voice playback failed:", err);
      }
    }

    authForm.addEventListener('submit', async (e) => {
      if (isProcessing) {
        e.preventDefault();
        return;
      }

      const nameInput = document.getElementById('full_name');
      const emailInput = document.getElementById('email');
      const passwordInput = document.getElementById('password');
      const confirmInput = document.getElementById('confirm_password');
      
      const name = nameInput ? nameInput.value.trim() : '';
      const email = emailInput ? emailInput.value.trim() : '';
      const password = passwordInput ? passwordInput.value : '';
      const confirm = confirmInput ? confirmInput.value : '';

      // Intelligent Validation
      if (isRegister && !name) {
        e.preventDefault();
        setRobotState('error', "Please enter your full name to create an account.");
        return;
      }
      if (!email && !password) {
        e.preventDefault();
        setRobotState('error', "Please enter your email and password to continue.");
        return;
      }
      if (!email) {
        e.preventDefault();
        setRobotState('error', "Please enter your email address before continuing.");
        return;
      }
      if (!password) {
        e.preventDefault();
        setRobotState('error', "Your password is required to access InterviewForge.");
        return;
      }
      if (email && !email.includes('@')) {
        e.preventDefault();
        setRobotState('error', "That doesn't appear to be a valid email address.");
        return;
      }
      if (isRegister && password !== confirm) {
        e.preventDefault();
        setRobotState('error', "Your passwords do not match. Please verify.");
        return;
      }

      // Valid inputs, proceed to intercept
      e.preventDefault();
      isProcessing = true;
      setRobotState('processing', isRegister ? "Creating your account..." : "Analyzing credentials...");
      
      try {
        const formData = new FormData(authForm);
        const response = await fetch(authForm.action || window.location.href, {
          method: 'POST',
          body: formData,
          redirect: 'follow'
        });

        if (response.redirected) {
          // Success Redirect
          if (isRegister) {
            setRobotState('success', "Account created successfully. Welcome to InterviewForge.");
            playRobotVoice("Welcome to InterviewForge. Your AI workspace is ready.");
          } else {
            setRobotState('success', "Welcome back! Your AI interview workspace is ready.");
            playRobotVoice("Welcome back to InterviewForge.");
          }
          setTimeout(() => {
            window.location.href = response.url;
          }, 1500);
        } else {
          // Assume failure (server rendered the template with error)
          isProcessing = false;
          
          const html = await response.text();
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, 'text/html');
          const errorEl = doc.querySelector('.auth-error');
          let errorMsg = errorEl ? errorEl.textContent.trim() : (isRegister ? "Registration failed. Please try again." : "Login failed. Please verify your email and password.");
          
          setRobotState('error', errorMsg);
          
          // Update DOM error div
          let existingError = document.querySelector('.auth-error');
          if (!existingError && errorEl) {
            const newError = document.createElement('div');
            newError.className = 'auth-error';
            newError.textContent = errorMsg;
            authForm.parentNode.insertBefore(newError, authForm);
          } else if (existingError) {
            existingError.textContent = errorMsg;
          }
        }
      } catch (err) {
        isProcessing = false;
        setRobotState('error', "A network error occurred. Please try again.");
      }
    });
  }
});