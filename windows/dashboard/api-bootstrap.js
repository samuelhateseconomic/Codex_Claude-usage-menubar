/* Short-lived launch exchange. Session cookie is HttpOnly; CSRF stays in memory. */
(async () => {
  const target = document.getElementById('state');
  const token = new URLSearchParams(location.hash.slice(1)).get('launch');
  history.replaceState(null, '', location.pathname);
  try {
    const response = token ? await fetch('/api/v1/session/bootstrap', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type':'application/json'}, body: JSON.stringify({launch_token:token})
    }) : await fetch('/api/v1/session', {credentials:'same-origin'});
    if (!response.ok) throw new Error('launch');
    const session = await response.json();
    const csrf = session.data.csrf_token;
    const status = await fetch('/api/v1/status', {credentials:'same-origin'});
    if (!status.ok || !csrf) throw new Error('status');
    const data = await status.json();
    target.textContent = data.data.ready
      ? (data.data.freshness === 'stale' ? 'Local usage service is ready with retained or stale data.' : 'Local usage service is ready.')
      : (data.data.indexing ? 'Local usage is being indexed. Open again when indexing completes.' : 'Local usage is unavailable. Check index status and local settings.');
  } catch {
    target.textContent = 'The local launch expired or failed. Open again through the application.';
  }
})();
