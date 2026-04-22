const form = document.getElementById("video-form");
const submitButton = document.getElementById("submit-button");
const radios = document.querySelectorAll('input[name="image_mode"]');
const manualFields = document.getElementById("manual-fields");
const autoFields = document.getElementById("auto-fields");
const jobPanel = document.getElementById("job-panel");
const jobStatus = document.getElementById("job-status");
const jobMessage = document.getElementById("job-message");
const progressFill = document.getElementById("progress-fill");
const jobPercent = document.getElementById("job-percent");
const jobActions = document.getElementById("job-actions");
const downloadLink = document.getElementById("download-link");
const jobError = document.getElementById("job-error");
const previewPanel = document.getElementById("preview-panel");
const videoPreview = document.getElementById("video-preview");
const keywordInput = document.querySelector('input[name="keywords"]');
const imageInput = document.querySelector('input[name="images"]');

let activePoll = null;

function asProgress(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(number)));
}

function stopPolling() {
  if (activePoll) {
    window.clearInterval(activePoll);
    activePoll = null;
  }
  submitButton.disabled = false;
  submitButton.textContent = "Create video";
}

function updateMode() {
  const mode = document.querySelector('input[name="image_mode"]:checked')?.value;
  manualFields.classList.toggle("hidden", mode !== "manual");
  autoFields.classList.toggle("hidden", mode !== "auto");
  imageInput.required = mode === "manual";
  keywordInput.required = mode === "auto";
}

function resetPreview() {
  previewPanel.classList.add("hidden");
  videoPreview.pause();
  videoPreview.removeAttribute("src");
  videoPreview.load();
}

function paintJob(job) {
  const status = job.status || "failed";
  const progress = asProgress(job.progress);

  jobPanel.classList.remove("hidden");
  jobStatus.textContent = status;
  jobMessage.textContent = job.message || "Working";
  jobPercent.textContent = `${progress}%`;
  progressFill.style.width = `${progress}%`;
  jobStatus.dataset.state = status;

  if (status === "completed" && job.download_url) {
    jobActions.classList.remove("hidden");
    downloadLink.href = job.download_url;
    if (job.preview_url) {
      videoPreview.src = job.preview_url;
      previewPanel.classList.remove("hidden");
    }
  } else {
    jobActions.classList.add("hidden");
    resetPreview();
  }

  if (status === "failed" && job.error) {
    jobError.classList.remove("hidden");
    jobError.textContent = job.error;
  } else {
    jobError.classList.add("hidden");
    jobError.textContent = "";
  }
}

async function pollJob(statusUrl) {
  stopPolling();
  submitButton.disabled = true;
  submitButton.textContent = "Rendering...";

  const fetchStatus = async () => {
    try {
      const response = await fetch(statusUrl, { headers: { Accept: "application/json" } });
      const job = await response.json();

      if (!response.ok || job.error) {
        paintJob({
          status: "failed",
          progress: 100,
          message: "Render was interrupted",
          error: job.error || "The server could not find this render job. The app may have restarted.",
        });
        stopPolling();
        return;
      }

      paintJob(job);

      if (job.status === "completed" || job.status === "failed") {
        stopPolling();
      }
    } catch (_error) {
      paintJob({
        status: "failed",
        progress: 100,
        message: "Connection lost",
        error: "The server could not be reached. If this happened during rendering, the service may have restarted.",
      });
      stopPolling();
    }
  };

  await fetchStatus();
  activePoll = window.setInterval(fetchStatus, 1500);
}

async function submitForm(event) {
  event.preventDefault();
  submitButton.disabled = true;
  submitButton.textContent = "Queueing render...";
  jobActions.classList.add("hidden");
  jobError.classList.add("hidden");
  resetPreview();
  paintJob({ status: "queued", progress: 0, message: "Uploading files" });
  jobPanel.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const formData = new FormData(form);
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
      headers: { Accept: "application/json" },
    });

    const payload = await response.json();

    if (!response.ok) {
      submitButton.disabled = false;
      submitButton.textContent = "Create video";
      paintJob({
        status: "failed",
        progress: 100,
        message: "Could not start render",
        error: payload.error || "Unexpected error",
      });
      return;
    }

    submitButton.textContent = "Rendering...";
    await pollJob(payload.status_url);
  } catch (_error) {
    submitButton.disabled = false;
    submitButton.textContent = "Create video";
    paintJob({
      status: "failed",
      progress: 100,
      message: "Could not start render",
      error: "The server could not be reached. Please try again.",
    });
  }
}

form.addEventListener("submit", submitForm);
radios.forEach((radio) => {
  radio.addEventListener("change", updateMode);
});

updateMode();
