(() => {
  const panel = document.getElementById('maintenance-jobs');
  if (!panel || panel.dataset.active !== '1') return;
  const labels = { queued: 'En attente', running: 'En cours', done: 'Terminée', failed: 'Échec' };
  const poll = async () => {
    try {
      const response = await fetch(panel.dataset.statusUrl, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok || response.redirected) return;
      const data = await response.json();
      let active = false;
      for (const job of data.jobs) {
        active ||= job.status === 'queued' || job.status === 'running';
        const row = panel.querySelector(`[data-job="${job.id}"]`);
        if (!row) continue;
        row.querySelector('progress').value = job.progress;
        row.querySelector('.job-message').textContent =
          job.message || 'En attente du service de maintenance…';
        const state = row.querySelector('.job-status');
        state.textContent = labels[job.status] || job.status;
        state.className = `file-state job-status ${job.status === 'done' ? 'available' : job.status === 'failed' ? 'missing' : 'expired'}`;
      }
      if (!active) document.getElementById('jobs-finished').hidden = false;
      else window.setTimeout(poll, 5000);
    } catch {
      window.setTimeout(poll, 10000);
    }
  };
  window.setTimeout(poll, 2000);
})();
