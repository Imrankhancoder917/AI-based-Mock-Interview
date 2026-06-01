document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("uploadForm");
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const browseBtn = document.querySelector(".browse-btn");
  const filePreview = document.getElementById("filePreview");
  const fileName = document.getElementById("fileName");
  const fileMeta = document.getElementById("fileMeta");
  const removeFileBtn = document.getElementById("removeFileBtn");
  const progressWrap = document.getElementById("progressWrap");
  const progressBar = document.getElementById("progressBar");
  const progressLabel = document.getElementById("progressLabel");
  const messageBox = document.getElementById("messageBox");
  const resultsArea = document.getElementById("resultsArea");
  const modeChips = document.querySelectorAll(".mode-chip");

  const initialResult = window.__UPLOAD_INITIAL_RESULT__;
  if (initialResult && resultsArea && resultsArea.hidden) {
    resultsArea.hidden = false;
  }

  const formatBytes = (bytes) => {
    if (!bytes) return "0 KB";
    const units = ["bytes", "KB", "MB", "GB"];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / Math.pow(1024, index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
  };

  const setMessage = (text, kind) => {
    if (!messageBox) return;
    messageBox.hidden = !text;
    messageBox.textContent = text;
    messageBox.className = `message-box ${kind || ""}`.trim();
  };

  const updatePreview = () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      filePreview.hidden = true;
      return;
    }

    fileName.textContent = file.name;
    fileMeta.textContent = `${file.type || "file"} · ${formatBytes(file.size)}`;
    filePreview.hidden = false;
  };

  const resetUploadState = () => {
    progressWrap.hidden = true;
    progressBar.style.width = "0%";
    progressLabel.textContent = "Preparing upload...";
  };

  browseBtn.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", () => {
    updatePreview();
    setMessage("", "");
  });

  removeFileBtn.addEventListener("click", () => {
    fileInput.value = "";
    filePreview.hidden = true;
    setMessage("File removed.", "");
    resetUploadState();
  });

  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragover");
    if (event.dataTransfer.files && event.dataTransfer.files[0]) {
      fileInput.files = event.dataTransfer.files;
      updatePreview();
      setMessage("File ready for upload.", "");
    }
  });

  modeChips.forEach((chip) => {
    const input = chip.querySelector("input");
    input.addEventListener("change", () => {
      modeChips.forEach((item) => item.classList.remove("active"));
      chip.classList.add("active");
    });
  });

  const renderResults = (result) => {
    if (!resultsArea) return;

    const renderChips = (items) => items.map((item) => `<span class="chip">${item}</span>`).join("");
    const renderList = (items) => items.map((item) => `<li>${item}</li>`).join("");
    const summary = result.summary || {};

    const sections = [`
      <div class="result-grid">
        <article class="result-card glass-card">
          <div class="result-header">
            <div>
              <span class="result-kicker">Parsed file</span>
              <h3>${result.filename || "Uploaded file"}</h3>
            </div>
            <span class="result-badge">${(result.document_type || "FILE").toUpperCase()}</span>
          </div>
          <p class="result-summary">Structured extraction completed successfully.</p>
        </article>
    `];

    if (summary.skills) sections.push(`<article class="result-card glass-card"><h3>Skills</h3><div class="chip-list">${renderChips(summary.skills)}</div></article>`);
    if (summary.projects) sections.push(`<article class="result-card glass-card"><h3>Projects</h3><ul class="result-list">${renderList(summary.projects)}</ul></article>`);
    if (summary.certifications) sections.push(`<article class="result-card glass-card"><h3>Certifications</h3><ul class="result-list">${renderList(summary.certifications)}</ul></article>`);
    if (summary.education) sections.push(`<article class="result-card glass-card"><h3>Education</h3><ul class="result-list">${renderList(summary.education)}</ul></article>`);
    if (summary.experience) sections.push(`<article class="result-card glass-card"><h3>Experience</h3><ul class="result-list">${renderList(summary.experience)}</ul></article>`);
    if (summary.required_skills) sections.push(`<article class="result-card glass-card"><h3>Required skills</h3><div class="chip-list">${renderChips(summary.required_skills)}</div></article>`);
    if (summary.responsibilities) sections.push(`<article class="result-card glass-card"><h3>Responsibilities</h3><ul class="result-list">${renderList(summary.responsibilities)}</ul></article>`);
    if (summary.technologies) sections.push(`<article class="result-card glass-card"><h3>Technologies</h3><div class="chip-list">${renderChips(summary.technologies)}</div></article>`);

    sections.push(`</div>`);
    resultsArea.innerHTML = sections.join("");
    resultsArea.hidden = false;
  };

  if (initialResult) {
    renderResults(initialResult);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();

    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      setMessage("Choose a file before uploading.", "error");
      return;
    }

    const formData = new FormData(form);
    const xhr = new XMLHttpRequest();

    progressWrap.hidden = false;
    progressBar.style.width = "8%";
    progressLabel.textContent = "Starting upload...";
    setMessage("Uploading securely...", "");

    xhr.open("POST", form.action || window.location.pathname, true);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.max(8, Math.round((event.loaded / event.total) * 100));
      progressBar.style.width = `${percent}%`;
      progressLabel.textContent = percent < 100 ? `Uploading ${percent}%` : "Finalizing parse...";
    });

    xhr.onreadystatechange = () => {
      if (xhr.readyState !== 4) return;

      if (xhr.status >= 200 && xhr.status < 300) {
        progressBar.style.width = "100%";
        progressLabel.textContent = "Upload complete";

        try {
          const response = JSON.parse(xhr.responseText);
          if (response.ok) {
            setMessage("File uploaded and parsed successfully.", "success");
            renderResults(response.result);
          } else {
            setMessage(response.error || "Upload failed.", "error");
          }
        } catch (error) {
          setMessage("The server returned an unexpected response.", "error");
        }
      } else {
        setMessage("Upload failed. Please try again.", "error");
      }

      setTimeout(resetUploadState, 900);
    };

    xhr.send(formData);
  });
});