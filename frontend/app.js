/**
 * Lumix 4K Image Enhancer - Frontend Controller
 * Phase 1: Setup & Scaffolding
 * Phase 2: Core Upload Flow Integration
 * Phase 3: Upscaling Engine Integration
 * Phase 4: Async Job Handling + Progress Polling
 * Phase 5: Result Delivery — Before/After Slider, Auto-cleanup, Download
 */

const CONFIG = {
  DEFAULT_API_URL: 'https://image-enhancer-94el.onrender.com',
  STORAGE_KEY: 'lumix_api_url',
  MAX_FILE_SIZE: 10 * 1024 * 1024,
  ALLOWED_TYPES: ['image/jpeg', 'image/png', 'image/webp'],
  HEALTH_CHECK_INTERVAL: 15000,  // Re-check interval when online
  HEALTH_CHECK_RETRY_INTERVAL: 5000, // Fast retry when offline/waking
  HEALTH_CHECK_TIMEOUT: 65000,  // 65s — covers Render free-tier cold starts (30-60s)
  POLL_INTERVAL: 2000,
  POLL_MAX_ATTEMPTS: 150  // 5 minutes max
};

function getInitialApiUrl() {
  const saved = localStorage.getItem(CONFIG.STORAGE_KEY);
  // If hosted on HTTPS (like GitHub Pages) and the saved URL is HTTP localhost,
  // automatically upgrade to DEFAULT_API_URL to prevent mixed content blocking in Brave/Edge
  if (window.location.protocol === 'https:' && saved && (saved.startsWith('http://localhost') || saved.startsWith('http://127.0.0.1'))) {
    localStorage.setItem(CONFIG.STORAGE_KEY, CONFIG.DEFAULT_API_URL);
    return CONFIG.DEFAULT_API_URL;
  }
  return saved || CONFIG.DEFAULT_API_URL;
}

let state = {
  apiUrl: getInitialApiUrl(),
  selectedFile: null,
  isBackendOnline: false,
  currentJobId: null,
  isUploading: false,
  pollTimer: null,
  pollAttempts: 0
};

const elements = {
  backendStatus: document.getElementById('backend-status'),
  statusText: document.getElementById('status-text'),
  configBtn: document.getElementById('config-btn'),
  configModal: document.getElementById('config-modal'),
  modalOverlay: document.getElementById('modal-overlay'),
  modalCloseBtn: document.getElementById('modal-close-btn'),
  apiUrlInput: document.getElementById('api-url-input'),
  modalTestBtn: document.getElementById('modal-test-btn'),
  modalTestStatus: document.getElementById('modal-test-status'),
  modalSaveBtn: document.getElementById('modal-save-btn'),
  dropZone: document.getElementById('drop-zone'),
  fileInput: document.getElementById('file-input'),
  browseBtn: document.getElementById('browse-btn'),
  previewStage: document.getElementById('preview-stage'),
  fileName: document.getElementById('file-name'),
  fileStats: document.getElementById('file-stats'),
  imagePreview: document.getElementById('image-preview'),
  resetBtn: document.getElementById('reset-btn'),
  enhanceBtn: document.getElementById('enhance-btn'),
  enhanceBtnText: document.getElementById('enhance-btn-text'),
  // Phase 4 elements
  progressTracker: document.getElementById('progress-tracker'),
  progressStatusBadge: document.getElementById('progress-status-badge'),
  progressStatusLabel: document.getElementById('progress-status-label'),
  jobIdTag: document.getElementById('job-id-tag'),
  progressMessage: document.getElementById('progress-message'),
  progressBarFill: document.getElementById('progress-bar-fill'),
  progressPercent: document.getElementById('progress-percent'),
  completedResult: document.getElementById('completed-result'),
  resultEngine: document.getElementById('result-engine'),
  resultOutputDims: document.getElementById('result-output-dims'),
  resultTime: document.getElementById('result-time'),
  downloadActions: document.getElementById('download-actions'),
  downloadFormatSelect: document.getElementById('download-format-select'),
  downloadBtn: document.getElementById('download-btn'),
  uploadErrorMsg: document.getElementById('upload-error-msg'),
  toastContainer: document.getElementById('toast-container'),
  // Phase 5 elements
  stageBodyUpload: document.getElementById('stage-body-upload'),
  comparisonStage: document.getElementById('comparison-stage'),
  comparisonContainer: document.getElementById('comparison-container'),
  compareHandle: document.getElementById('compare-handle'),
  compareOriginalLayer: document.getElementById('compare-original-layer'),
  compareOriginalImg: document.getElementById('compare-original-img'),
  enhancedPreview: document.getElementById('enhanced-preview')
};

function init() {
  bindEvents();
  startHealthPolling();
}

let _healthTimer = null;

function startHealthPolling() {
  clearTimeout(_healthTimer);
  checkBackendHealth().then(online => {
    const nextInterval = online
      ? CONFIG.HEALTH_CHECK_INTERVAL
      : CONFIG.HEALTH_CHECK_RETRY_INTERVAL;
    _healthTimer = setTimeout(startHealthPolling, nextInterval);
  });
}

function bindEvents() {
  elements.backendStatus.addEventListener('click', openConfigModal);
  elements.configBtn.addEventListener('click', openConfigModal);
  elements.modalCloseBtn.addEventListener('click', closeConfigModal);
  elements.modalOverlay.addEventListener('click', closeConfigModal);
  elements.modalTestBtn.addEventListener('click', handleTestConnection);
  elements.modalSaveBtn.addEventListener('click', handleSaveConfig);

  elements.browseBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    elements.fileInput.click();
  });

  elements.dropZone.addEventListener('click', () => elements.fileInput.click());
  elements.fileInput.addEventListener('change', handleFileInputChange);

  ['dragenter', 'dragover'].forEach(ev => {
    elements.dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      elements.dropZone.classList.add('drag-over');
    });
  });

  ['dragleave', 'drop'].forEach(ev => {
    elements.dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      elements.dropZone.classList.remove('drag-over');
    });
  });

  elements.dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) processSelectedFile(files[0]);
  });

  elements.resetBtn.addEventListener('click', resetSelection);
  elements.enhanceBtn.addEventListener('click', handleUploadAndEnhance);

  elements.dropZone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      elements.fileInput.click();
    }
  });

  // Format dropdown change listener
  if (elements.downloadFormatSelect) {
    elements.downloadFormatSelect.addEventListener('change', updateDownloadUrl);
  }

  // Phase 5: comparison slider (mouse + touch)
  initComparisonSlider();
}

// ── Health Check ──────────────────────────────────────────────────────────────

async function checkBackendHealth() {
  // Only show 'Waking up' if we were previously offline, not on every poll
  if (!state.isBackendOnline) {
    updateStatusIndicator('waking', 'Waking up...');
  }
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), CONFIG.HEALTH_CHECK_TIMEOUT);
    const response = await fetch(`${state.apiUrl}/health`, {
      method: 'GET',
      mode: 'cors',
      headers: { 'Accept': 'application/json' },
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    if (response.ok) {
      const data = await response.json();
      if (data.status === 'ok') {
        state.isBackendOnline = true;
        updateStatusIndicator('online', 'Online');
        return true;
      }
    }
    throw new Error('Non-ok response');
  } catch {
    state.isBackendOnline = false;
    updateStatusIndicator('offline', 'Offline');
    return false;
  }
}

function updateStatusIndicator(cls, label) {
  elements.backendStatus.classList.remove('online', 'offline', 'checking', 'waking');
  elements.backendStatus.classList.add(cls);
  elements.statusText.textContent = label;
}

// ── Config Modal ──────────────────────────────────────────────────────────────

function openConfigModal() {
  elements.apiUrlInput.value = state.apiUrl;
  elements.modalTestStatus.textContent = '';
  elements.modalTestStatus.className = 'modal-test-status';
  elements.configModal.classList.remove('hidden');
  elements.apiUrlInput.focus();
}

function closeConfigModal() {
  elements.configModal.classList.add('hidden');
}

async function handleTestConnection() {
  const testUrl = elements.apiUrlInput.value.trim().replace(/\/+$/, '');
  if (!testUrl) {
    elements.modalTestStatus.textContent = 'Please enter a valid URL';
    elements.modalTestStatus.className = 'modal-test-status error';
    return;
  }
  elements.modalTestStatus.textContent = 'Testing connection...';
  elements.modalTestStatus.className = 'modal-test-status';
  elements.modalTestBtn.disabled = true;
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);
    const res = await fetch(`${testUrl}/health`, {
      method: 'GET',
      mode: 'cors',
      headers: { Accept: 'application/json' },
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    if (res.ok) {
      const data = await res.json();
      elements.modalTestStatus.innerHTML = `
        <span class="test-status-content">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
          <span>Connected successfully (${data.service || 'Ready'})</span>
        </span>`;
      elements.modalTestStatus.className = 'modal-test-status success';
    } else {
      elements.modalTestStatus.innerHTML = `
        <span class="test-status-content">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span>Server responded with status ${res.status}</span>
        </span>`;
      elements.modalTestStatus.className = 'modal-test-status error';
    }
  } catch {
    elements.modalTestStatus.innerHTML = `
      <span class="test-status-content">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        <span>Could not connect. Verify server is running.</span>
      </span>`;
    elements.modalTestStatus.className = 'modal-test-status error';
  } finally {
    elements.modalTestBtn.disabled = false;
  }
}

function handleSaveConfig() {
  const newUrl = elements.apiUrlInput.value.trim().replace(/\/+$/, '');
  if (newUrl) {
    state.apiUrl = newUrl;
    localStorage.setItem(CONFIG.STORAGE_KEY, newUrl);
    checkBackendHealth();
    closeConfigModal();
  }
}

// ── File Handling ─────────────────────────────────────────────────────────────

function handleFileInputChange(e) {
  if (e.target.files && e.target.files.length > 0) processSelectedFile(e.target.files[0]);
}

function processSelectedFile(file) {
  hideError();
  if (!CONFIG.ALLOWED_TYPES.includes(file.type)) {
    showToast('Unsupported format. Please select a JPG, PNG, or WebP image.', 'error');
    return;
  }
  if (file.size > CONFIG.MAX_FILE_SIZE) {
    showToast(`File too large (${formatBytes(file.size)}). Max allowed is 10 MB.`, 'error');
    return;
  }

  state.selectedFile = file;
  state.currentJobId = null;

  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    elements.imagePreview.src = dataUrl;
    const img = new Image();
    img.onload = () => {
      elements.fileName.textContent = file.name;
      elements.fileStats.textContent = `${img.naturalWidth} × ${img.naturalHeight} px • ${formatBytes(file.size)}`;
      elements.dropZone.classList.add('hidden');
      elements.previewStage.classList.remove('hidden');
      setEnhanceButtonIdle();
    };
    img.src = dataUrl;
  };
  reader.readAsDataURL(file);
}

// ── Phase 5: Comparison Slider ───────────────────────────────────────────────

function initComparisonSlider() {
  const container = elements.comparisonContainer;
  const handle = elements.compareHandle;
  if (!container || !handle) return;

  let dragging = false;

  function setSliderPosition(clientX) {
    const rect = container.getBoundingClientRect();
    let pct = (clientX - rect.left) / rect.width;
    pct = Math.max(0.02, Math.min(0.98, pct));
    const pctPx = `${(pct * 100).toFixed(2)}%`;
    elements.compareOriginalLayer.style.clipPath = `inset(0 calc(100% - ${pctPx}) 0 0)`;
    elements.compareOriginalLayer.style.webkitClipPath = `inset(0 calc(100% - ${pctPx}) 0 0)`;
    handle.style.left = pctPx;
    handle.setAttribute('aria-valuenow', Math.round(pct * 100));
  }

  // Mouse
  handle.addEventListener('mousedown', (e) => { e.preventDefault(); dragging = true; });
  document.addEventListener('mousemove', (e) => { if (dragging) setSliderPosition(e.clientX); });
  document.addEventListener('mouseup', () => { dragging = false; });

  // Touch
  handle.addEventListener('touchstart', (e) => { e.preventDefault(); dragging = true; }, { passive: false });
  document.addEventListener('touchmove', (e) => {
    if (dragging && e.touches[0]) setSliderPosition(e.touches[0].clientX);
  }, { passive: true });
  document.addEventListener('touchend', () => { dragging = false; });

  // Click anywhere on container to jump handle
  container.addEventListener('click', (e) => {
    if (e.target === handle || handle.contains(e.target)) return;
    setSliderPosition(e.clientX);
  });

  // Keyboard arrow keys for accessibility
  handle.addEventListener('keydown', (e) => {
    const rect = container.getBoundingClientRect();
    const currentPct = parseFloat(handle.style.left) / 100;
    const step = 0.02;
    if (e.key === 'ArrowLeft') setSliderPosition(rect.left + (currentPct - step) * rect.width);
    if (e.key === 'ArrowRight') setSliderPosition(rect.left + (currentPct + step) * rect.width);
  });
}

// ── Phase 4: Upload & Async Job Polling ───────────────────────────────────────

async function handleUploadAndEnhance() {
  if (!state.selectedFile || state.isUploading) return;

  hideError();
  clearPollTimer();
  setEnhanceButtonUploading();
  state.isUploading = true;

  const formData = new FormData();
  formData.append('file', state.selectedFile);

  try {
    const response = await fetch(`${state.apiUrl}/enhance?engine=auto`, {
      method: 'POST',
      body: formData
    });
    const data = await response.json();

    if (!response.ok) throw new Error(data.detail || `Upload failed with HTTP ${response.status}`);

    state.currentJobId = data.job_id;

    // Show progress tracker
    elements.progressTracker.classList.remove('hidden');
    elements.downloadActions.classList.add('hidden');
    elements.completedResult.classList.add('hidden');
    elements.jobIdTag.textContent = `Job: ${data.job_id.substring(0, 8)}…`;
    updateProgress(data.progress || 10, data.status, 'Queued – starting enhancement...');
    setEnhanceButtonProcessing();

    showToast('Image uploaded! AI enhancement started in background…', 'success');

    // Start polling
    state.pollAttempts = 0;
    pollJobStatus(data.job_id);

  } catch (err) {
    showError(err.message);
    showToast(err.message, 'error');
    setEnhanceButtonIdle();
  } finally {
    state.isUploading = false;
  }
}

async function pollJobStatus(jobId) {
  if (state.pollAttempts >= CONFIG.POLL_MAX_ATTEMPTS) {
    showError('Polling timeout — the job is taking too long. Please try again.');
    setEnhanceButtonIdle();
    return;
  }
  state.pollAttempts++;

  try {
    const res = await fetch(`${state.apiUrl}/status/${jobId}`);
    if (!res.ok) throw new Error(`Status poll failed: HTTP ${res.status}`);
    const job = await res.json();

    updateProgress(job.progress || 0, job.status, job.progress_message || '');

    if (job.status === 'completed') {
      onJobCompleted(job);
    } else if (job.status === 'failed') {
      onJobFailed(job.error || 'Enhancement failed on the server.');
    } else {
      // Still processing — schedule next poll
      state.pollTimer = setTimeout(() => pollJobStatus(jobId), CONFIG.POLL_INTERVAL);
    }
  } catch (err) {
    // Network hiccup — retry
    state.pollTimer = setTimeout(() => pollJobStatus(jobId), CONFIG.POLL_INTERVAL * 2);
  }
}

function onJobCompleted(job) {
  clearPollTimer();
  updateProgress(100, 'completed', 'Enhancement complete! 4K output ready for download.');
  setEnhanceBtnCompleted();

  // Populate result stats
  const result = job.result || {};
  const od = result.output_dimensions || {};
  elements.resultEngine.textContent = (result.engine || 'Unknown')
    .replace('High-Fidelity + Unsharp Mask', 'Lanczos HQ')
    .replace('Super-Resolution (AI)', 'Real-ESRGAN AI');
  elements.resultOutputDims.textContent = od.width && od.height ? `${od.width} × ${od.height} px` : '--';
  elements.resultTime.textContent = result.processing_time_sec != null ? `${result.processing_time_sec}s` : '--';
  elements.completedResult.classList.remove('hidden');

  // Set download link with chosen format
  state.currentJobId = job.job_id;
  updateDownloadUrl();
  elements.downloadActions.classList.remove('hidden');

  // ── Phase 5: Reveal before/after comparison slider ───────────────────────
  const previewUrl = `${state.apiUrl}/preview/${job.job_id}`;
  elements.enhancedPreview.src = previewUrl;
  elements.compareOriginalImg.src = elements.imagePreview.src; // local data URL

  // Hide upload-only preview, show comparison
  elements.stageBodyUpload.classList.add('hidden');
  elements.comparisonStage.classList.remove('hidden');

  // Reset slider to 50%
  elements.compareOriginalLayer.style.clipPath = 'inset(0 50% 0 0)';
  elements.compareOriginalLayer.style.webkitClipPath = 'inset(0 50% 0 0)';
  elements.compareHandle.style.left = '50%';
  elements.compareHandle.setAttribute('aria-valuenow', '50');
  // ─────────────────────────────────────────────────────────────────────────

  showToast('4K enhancement complete! Drag the slider to compare.', 'success');
}

function updateDownloadUrl() {
  if (!state.currentJobId) return;
  const format = elements.downloadFormatSelect ? elements.downloadFormatSelect.value : 'png';
  elements.downloadBtn.href = `${state.apiUrl}/download/${state.currentJobId}?format=${format}`;
}

function onJobFailed(errorMsg) {
  clearPollTimer();
  updateProgress(100, 'failed', `Failed: ${errorMsg}`);
  showError(errorMsg);
  setEnhanceButtonIdle();
  showToast(`Enhancement failed: ${errorMsg}`, 'error');
}

function updateProgress(percent, status, message) {
  const pct = Math.max(0, Math.min(100, percent));
  elements.progressBarFill.style.width = `${pct}%`;
  elements.progressPercent.textContent = `${pct}%`;
  elements.progressMessage.textContent = message || '';

  // Update badge
  const badge = elements.progressStatusBadge;
  badge.classList.remove('processing', 'completed', 'failed', 'success');
  if (status === 'completed') {
    badge.classList.add('completed');
    elements.progressStatusLabel.textContent = 'Completed';
  } else if (status === 'failed') {
    badge.classList.add('failed');
    elements.progressStatusLabel.textContent = 'Failed';
  } else {
    badge.classList.add('processing');
    elements.progressStatusLabel.textContent = status === 'queued' ? 'Queued' : 'Processing';
  }
}

function clearPollTimer() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

// ── Button State Helpers ──────────────────────────────────────────────────────

function setEnhanceButtonIdle() {
  elements.enhanceBtn.disabled = false;
  elements.enhanceBtn.innerHTML = `
    <svg class="btn-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>
    </svg>
    <span>Upload &amp; Enhance</span>`;
}

function setEnhanceButtonUploading() {
  elements.enhanceBtn.disabled = true;
  elements.enhanceBtn.innerHTML = `<span class="spinner"></span><span>Uploading...</span>`;
}

function setEnhanceButtonProcessing() {
  elements.enhanceBtn.disabled = true;
  elements.enhanceBtn.innerHTML = `<span class="spinner"></span><span>Processing...</span>`;
}

function setEnhanceBtnCompleted() {
  elements.enhanceBtn.disabled = true;
  elements.enhanceBtn.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <path d="M20 6 9 17l-5-5"/>
    </svg>
    <span>Enhancement Complete</span>`;
}

// ── Reset & Utilities ─────────────────────────────────────────────────────────

function resetSelection() {
  clearPollTimer();
  state.selectedFile = null;
  state.currentJobId = null;
  state.isUploading = false;
  state.pollAttempts = 0;
  elements.fileInput.value = '';
  elements.imagePreview.src = '';
  elements.progressTracker.classList.add('hidden');
  elements.downloadActions.classList.add('hidden');
  if (elements.downloadFormatSelect) elements.downloadFormatSelect.value = 'png';
  elements.completedResult.classList.add('hidden');
  // Phase 5: hide comparison, restore upload preview
  elements.comparisonStage.classList.add('hidden');
  elements.stageBodyUpload.classList.remove('hidden');
  elements.enhancedPreview.src = '';
  elements.compareOriginalImg.src = '';
  hideError();
  setEnhanceButtonIdle();
  elements.previewStage.classList.add('hidden');
  elements.dropZone.classList.remove('hidden');
}

function showError(msg) {
  elements.uploadErrorMsg.textContent = msg;
  elements.uploadErrorMsg.classList.remove('hidden');
}

function hideError() {
  elements.uploadErrorMsg.textContent = '';
  elements.uploadErrorMsg.classList.add('hidden');
}

function showToast(message, type = 'info') {
  if (!elements.toastContainer) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-text">${message}</span>
    <button type="button" class="toast-close-btn" aria-label="Close notification">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M18 6 6 18M6 6l12 12"/>
      </svg>
    </button>`;
  toast.querySelector('.toast-close-btn').addEventListener('click', () => toast.remove());
  elements.toastContainer.appendChild(toast);
  setTimeout(() => {
    if (toast.parentNode) {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px) scale(0.95)';
      setTimeout(() => toast.remove(), 250);
    }
  }, 5000);
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

document.addEventListener('DOMContentLoaded', init);
