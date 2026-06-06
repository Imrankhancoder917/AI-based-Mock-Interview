document.addEventListener("DOMContentLoaded", () => {
  // --- 1. Counter Animations ---
  const counters = document.querySelectorAll('.stat-value.counter');

  counters.forEach(counter => {
    const targetText = counter.innerText;
    // Extract numbers from text (e.g., "94%", "12", "7.5")
    const targetMatch = targetText.match(/[\d.]+/);
    if (!targetMatch) return;

    const targetValue = parseFloat(targetMatch[0]);
    const isFloat = targetText.includes('.');
    const suffix = targetText.replace(/[\d.]+/g, '');

    let startValue = 0;
    const duration = 1500; // 1.5s
    const startTime = performance.now();

    function updateCounter(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);

      // Easing out cubic
      const easeProgress = 1 - Math.pow(1 - progress, 3);
      const currentVal = startValue + (targetValue - startValue) * easeProgress;

      counter.innerText = (isFloat ? currentVal.toFixed(1) : Math.floor(currentVal)) + suffix;

      if (progress < 1) {
        requestAnimationFrame(updateCounter);
      } else {
        counter.innerText = targetText; // Ensure exact final value
      }
    }

    requestAnimationFrame(updateCounter);
  });

  // --- 2. Chart.js Performance Overview ---
  const ctx = document.getElementById('performanceChart');
  if (ctx && window.Chart) {
    const gradient = ctx.getContext('2d').createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(37,99,235,0.2)');
    gradient.addColorStop(1, 'rgba(37,99,235,0)');

    // Animation for drawing line left-to-right
    const totalDuration = 2000;
    const delayBetweenPoints = totalDuration / 7;
    const previousY = (ctx) => ctx.index === 0 ? ctx.chart.scales.y.getPixelForValue(100) : ctx.chart.getDatasetMeta(ctx.datasetIndex).data[ctx.index - 1].getProps(['y'], true).y;

    const animation = {
      x: {
        type: 'number',
        easing: 'linear',
        duration: delayBetweenPoints,
        from: NaN, // the default
        delay(ctx) {
          if (ctx.type !== 'data' || ctx.xStarted) return 0;
          ctx.xStarted = true;
          return ctx.index * delayBetweenPoints;
        }
      },
      y: {
        type: 'number',
        easing: 'linear',
        duration: delayBetweenPoints,
        from: previousY,
        delay(ctx) {
          if (ctx.type !== 'data' || ctx.yStarted) return 0;
          ctx.yStarted = true;
          return ctx.index * delayBetweenPoints;
        }
      }
    };

    const bootstrap = window.__DASHBOARD_BOOTSTRAP__ || {};
    const chartLabels = bootstrap.chartLabels || [];
    const chartData = bootstrap.chartData || [];

    new Chart(ctx, {
      type: 'line',
      data: {
        labels: chartLabels,
        datasets: [{
          label: 'Interview Score',
          data: chartData,
          borderColor: '#2563EB',
          borderWidth: 3,
          backgroundColor: gradient,
          fill: true,
          tension: 0.4,
          pointBackgroundColor: '#FFFFFF',
          pointBorderColor: '#2563EB',
          pointBorderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation,
        interaction: {
          intersect: false,
          mode: 'index',
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0F172A',
            titleFont: { family: 'Inter', size: 13 },
            bodyFont: { family: 'Inter', size: 14, weight: 'bold' },
            padding: 12,
            cornerRadius: 8,
            displayColors: false
          }
        },
        scales: {
          x: {
            grid: { display: false, drawBorder: false },
            ticks: { font: { family: 'Inter', size: 12 }, color: '#64748B' }
          },
          y: {
            grid: { color: '#E2E8F0', borderDash: [5, 5], drawBorder: false },
            ticks: { font: { family: 'Inter', size: 12 }, color: '#64748B', stepSize: 20 },
            min: 0,
            max: 100
          }
        }
      }
    });
  }

  // --- 3. Circular Progress (Top Skills) ---
  const circle = document.querySelector('.circular-chart .circle');
  if (circle) {
    const targetPercentage = parseInt(circle.getAttribute('data-percentage') || "85", 10);
    // circle length is 100 (dasharray="100, 100") if using viewbox 0 0 36 36
    setTimeout(() => {
      circle.style.strokeDasharray = `${targetPercentage}, 100`;
    }, 500); // Wait for page to load
  }

  // --- 4. Notification Dropdown (BUG 2) ---
  const notificationBell = document.getElementById('notificationBell');
  const notificationDropdown = document.getElementById('notificationDropdown');
  const notificationBadge = document.getElementById('notificationBadge');
  const notificationList = document.getElementById('notificationList');
  const markAllReadBtn = document.getElementById('markAllRead');
  const clearAllBtn = document.getElementById('clearAllNotifications');

  const bootstrap = window.__DASHBOARD_BOOTSTRAP__ || {};
  let notifications = bootstrap.notifications || [];

  // Render notifications in dropdown
  function renderNotifications() {
    if (!notificationList) return;
    notificationList.innerHTML = '';

    const unreadCount = notifications.filter(n => n.unread).length;
    if (unreadCount > 0 && notificationBadge) {
      notificationBadge.innerText = unreadCount;
      notificationBadge.style.display = 'inline-block';
    } else if (notificationBadge) {
      notificationBadge.style.display = 'none';
    }

    if (notifications.length === 0) {
      notificationList.innerHTML = '<div class="empty-notifications text-center p-3 text-muted" style="font-size: 0.85rem; font-weight: 500;">No new notifications.</div>';
      return;
    }

    notifications.forEach(n => {
      const item = document.createElement('div');
      item.className = `notification-item ${n.unread ? 'unread' : ''}`;
      item.dataset.id = n.id;

      // Map icons to background colors matching dashboard styles
      let bgStyle = 'background: rgba(37,99,235,0.1); color: #2563EB;';
      if (n.icon.includes('check') || n.icon.includes('trophy')) {
        bgStyle = 'background: rgba(16,185,129,0.1); color: #10B981;';
      } else if (n.icon.includes('text') || n.icon.includes('dots')) {
        bgStyle = 'background: rgba(139,92,246,0.1); color: #8B5CF6;';
      } else if (n.icon.includes('bookmark') || n.icon.includes('bell')) {
        bgStyle = 'background: rgba(245,158,11,0.1); color: #F59E0B;';
      }

      item.innerHTML = `
        <div class="notification-item-icon" style="${bgStyle}">
          <i class="${n.icon}"></i>
        </div>
        <div class="notification-item-content">
          <span class="notification-item-title">${n.title}</span>
          <span class="notification-item-desc">${n.desc}</span>
          <span class="notification-item-time">${n.time}</span>
        </div>
      `;

      item.addEventListener('click', () => {
        n.unread = false;
        renderNotifications();
      });

      notificationList.appendChild(item);
    });
  }

  // Toggle dropdown on click
  if (notificationBell && notificationDropdown) {
    notificationBell.addEventListener('click', (e) => {
      e.stopPropagation();
      notificationDropdown.classList.toggle('active');
    });

    // Close on click outside
    document.addEventListener('click', (e) => {
      if (!notificationBell.contains(e.target)) {
        notificationDropdown.classList.remove('active');
      }
    });

    notificationDropdown.addEventListener('click', (e) => {
      e.stopPropagation();
    });
  }

  // Mark all as read
  if (markAllReadBtn) {
    markAllReadBtn.addEventListener('click', () => {
      notifications.forEach(n => n.unread = false);
      renderNotifications();
    });
  }

  // Clear all
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', () => {
      notifications = [];
      renderNotifications();
    });
  }

  // Initialize notifications render
  renderNotifications();

  // --- 5. AI Assistant Floating Chat Widget (BUG 3) ---
  const chatWidget = document.getElementById('chatWidget');
  const chatBody = document.getElementById('chatBody');
  const chatInput = document.getElementById('chatInput');
  const chatSend = document.getElementById('chatSend');

  const chatMinimize = document.getElementById('chatMinimize');
  const chatMaximize = document.getElementById('chatMaximize');
  const chatClose = document.getElementById('chatClose');

  // Sidebar Need Help Card click triggers
  const sidebarHelpCard = document.querySelector('.sidebar-ai-card');
  const sidebarHelpBtn = document.querySelector('.btn-chat-ai');

  function openChatWidget() {
    if (chatWidget) {
      chatWidget.style.display = 'flex';
      chatWidget.classList.remove('minimized');
      // Scroll to bottom
      if (chatBody) chatBody.scrollTop = chatBody.scrollHeight;
    }
  }

  if (sidebarHelpCard) {
    sidebarHelpCard.addEventListener('click', (e) => {
      if (e.target !== sidebarHelpBtn) {
        openChatWidget();
      }
    });
  }

  if (sidebarHelpBtn) {
    sidebarHelpBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openChatWidget();
    });
  }

  // Chat controls: Min/Max/Close
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

  // Chat History & Message Rendering
  const initialMessages = [
    {
      sender: 'bot',
      text: "Hi! I'm your InterviewForge Assistant.<br><br>I can help you understand features, reports, interviews, and dashboard analytics.",
      suggestions: [
        "How do mock interviews work?",
        "How is my score calculated?",
        "How can I improve my performance?",
        "Where can I download my report?"
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

});
