(() => {
  const video = document.getElementById('video');
  const snap = document.getElementById('snap');
  const guide = document.getElementById('guide');
  const pill = document.getElementById('pill');
  const pillText = document.getElementById('pillText');
  const msg = document.getElementById('msg');
  const modeEl = document.getElementById('mode');
  const depthFile = document.getElementById('depthFile');
  const captureBtn = document.getElementById('captureBtn');
  const retakeBtn = document.getElementById('retakeBtn');
  const resultPanel = document.getElementById('resultPanel');
  const resultTitle = document.getElementById('resultTitle');
  const resultMsg = document.getElementById('resultMsg');
  const progress = document.getElementById('progress');
  const metrics = document.getElementById('metrics');
  const preview = document.getElementById('preview');
  const hintList = document.getElementById('hintList');

  let stream = null;
  let ready = false;
  let validating = false;
  let readySince = 0;
  let pollTimer = null;
  let jobTimer = null;
  let lastJobId = null;

  function setStatus(state, text, message) {
    pill.className = 'status-pill' + (state === 'ready' ? ' ready' : state === 'bad' ? ' bad' : '');
    pillText.textContent = text;
    guide.className = 'guide ' + (state === 'ready' ? 'ready' : 'wait');
    if (message) msg.textContent = message;
    captureBtn.classList.toggle('ready', state === 'ready');
  }

  async function startCamera() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 1600 },
        },
      });
      video.srcObject = stream;
      await video.play();
      captureBtn.disabled = false;
      setStatus('wait', 'Aligning…', 'Point top-down at foot + reference.');
      pollTimer = setInterval(validateLoop, 450);
    } catch (err) {
      setStatus('bad', 'Camera blocked', 'Allow camera permission and reload.');
      msg.textContent = String(err.message || err);
    }
  }

  function grabBlob() {
    const w = video.videoWidth || 720;
    const h = video.videoHeight || 960;
    snap.width = w;
    snap.height = h;
    const ctx = snap.getContext('2d');
    ctx.drawImage(video, 0, 0, w, h);
    return new Promise((resolve) => snap.toBlob(resolve, 'image/jpeg', 0.85));
  }

  async function validateLoop() {
    if (validating || video.readyState < 2 || video.style.display === 'none') return;

    validating = true;
    try {
      const blob = await grabBlob();
      if (!blob) return;
      const fd = new FormData();
      fd.append('frame', blob, 'frame.jpg');
      fd.append('mode', modeEl.value);
      const res = await fetch('/api/validate', { method: 'POST', body: fd });
      const data = await res.json();
      ready = !!data.ready;
      if (ready) {
        if (!readySince) readySince = Date.now();
        setStatus('ready', 'Ready', data.message || 'Ready — hold still and capture');
        // Auto-capture after holding ready ~1.2s for smoother tester UX
        if (Date.now() - readySince > 1200 && !lastJobId) {
          // optional auto — only prompt via button glow; don't force auto to avoid surprise
        }
      } else {
        readySince = 0;
        setStatus('wait', 'Not ready', data.message || 'Adjust framing');
      }
      hintList.innerHTML = (data.hints || []).map((h) => `<li>${h}</li>`).join('');
    } catch (e) {
      setStatus('wait', 'Checking…', 'Validation paused — check connection');
    } finally {
      validating = false;
    }
  }

  async function capture() {
    const blob = await grabBlob();
    if (!blob) return;

    // Freeze UI immediately
    video.style.display = 'none';
    snap.style.display = 'block';
    captureBtn.style.display = 'none';
    retakeBtn.style.display = 'inline-block';
    clearInterval(pollTimer);
    pollTimer = null;

    resultPanel.classList.add('show');
    resultTitle.textContent = 'Captured';
    resultMsg.textContent = modeEl.value === 'depth'
      ? 'Photo saved. Depth measurement continues in the background…'
      : 'Measuring in the background…';
    progress.style.display = 'block';
    metrics.style.display = 'none';
    preview.style.display = 'none';
    setStatus('ready', 'Captured', 'Processing…');

    const fd = new FormData();
    fd.append('image', blob, 'capture.jpg');
    fd.append('mode', modeEl.value);
    if (depthFile.files[0]) {
      fd.append('depth', depthFile.files[0]);
      if (depthFile.files[0].name.toLowerCase().endsWith('.png')) {
        fd.append('depth_scale', '0.001');
      }
    }

    try {
      const res = await fetch('/api/jobs', { method: 'POST', body: fd });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      lastJobId = data.job_id;
      if (data.status === 'awaiting_depth') {
        resultTitle.textContent = 'Waiting for depth';
        resultMsg.textContent = data.message || 'Attach a LiDAR depth file below, or retake with card mode.';
        progress.style.display = 'none';
        return;
      }
      pollJob(lastJobId);
    } catch (e) {
      resultTitle.textContent = 'Failed';
      resultMsg.textContent = String(e.message || e);
      progress.style.display = 'none';
    }
  }

  function pollJob(jobId) {
    clearInterval(jobTimer);
    jobTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        if (data.status === 'awaiting_depth') {
          resultTitle.textContent = 'Waiting for depth';
          resultMsg.textContent = data.message || 'Upload depth to finish.';
          progress.style.display = 'none';
          return;
        }
        if (data.status === 'queued' || data.status === 'running') {
          resultTitle.textContent = 'Processing';
          resultMsg.textContent = 'Running measurement in the background…';
          progress.style.display = 'block';
          return;
        }
        clearInterval(jobTimer);
        jobTimer = null;
        progress.style.display = 'none';

        if (data.status === 'error') {
          resultTitle.textContent = 'Could not measure';
          resultMsg.textContent = data.error || 'Try a clearer top-down shot.';
          return;
        }

        const r = data.result;
        resultTitle.textContent = 'Result';
        resultMsg.textContent = `Mode: ${data.mode}`;
        metrics.style.display = 'grid';
        document.getElementById('mCm').textContent = `${r.cm} cm`;
        document.getElementById('mEu').textContent = r.eu;
        document.getElementById('mUsM').textContent = r.us_men;
        document.getElementById('mUsW').textContent = r.us_women;
        if (data.preview_url) {
          preview.src = data.preview_url;
          preview.style.display = 'block';
        }
      } catch (e) {
        clearInterval(jobTimer);
        resultTitle.textContent = 'Error';
        resultMsg.textContent = String(e.message || e);
        progress.style.display = 'none';
      }
    }, 700);
  }

  // If user picks depth file after awaiting_depth
  depthFile.addEventListener('change', async () => {
    if (!lastJobId || !depthFile.files[0]) return;
    const st = await fetch(`/api/jobs/${lastJobId}`).then((r) => r.json());
    if (st.status !== 'awaiting_depth') return;
    const fd = new FormData();
    fd.append('depth', depthFile.files[0]);
    if (depthFile.files[0].name.toLowerCase().endsWith('.png')) {
      fd.append('depth_scale', '0.001');
    }
    resultTitle.textContent = 'Processing';
    resultMsg.textContent = 'Depth attached — finishing in the background…';
    progress.style.display = 'block';
    await fetch(`/api/jobs/${lastJobId}/depth`, { method: 'POST', body: fd });
    pollJob(lastJobId);
  });

  function retake() {
    clearInterval(jobTimer);
    jobTimer = null;
    lastJobId = null;
    readySince = 0;
    snap.style.display = 'none';
    video.style.display = 'block';
    captureBtn.style.display = 'inline-block';
    retakeBtn.style.display = 'none';
    resultPanel.classList.remove('show');
    metrics.style.display = 'none';
    preview.style.display = 'none';
    setStatus('wait', 'Aligning…', 'Point top-down at foot + reference.');
    if (!pollTimer) pollTimer = setInterval(validateLoop, 450);
  }

  captureBtn.addEventListener('click', capture);
  retakeBtn.addEventListener('click', retake);
  modeEl.addEventListener('change', () => {
    readySince = 0;
    ready = false;
    setStatus('wait', 'Aligning…', 'Mode changed — re-check framing.');
  });

  startCamera();
})();
