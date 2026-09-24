(() => {
  // The page itself is already gated server-side (Nginx checks the httpOnly
  // auth cookie via /auth/verify before it ever sends this HTML file). This
  // script no longer decides *whether* the page loads — it just fetches the
  // authoritative session info for the UI and wires up logout.
  //
  // If this script runs at all, Nginx already confirmed a valid session,
  // so we don't need to re-redirect here except as a defensive fallback
  // (e.g. if this page is ever served a different way in the future).

  window.DPnitiAuth = {
    role: localStorage.getItem('role') || '',
    allowedSem: Number(localStorage.getItem('allowedSem')) || null,
    name: localStorage.getItem('userName') || '',
    async logout() {
      try {
        await fetch(`${CONFIG.BACKEND_URL}/api/auth/logout`, {
          method: 'POST',
          credentials: 'include',
        });
      } catch (e) {
        // Even if the network call fails, still clear local UI state and
        // send the user to login — the cookie will simply expire naturally.
      }
      localStorage.clear();
      window.location.replace('login/index.html');
    },
  };

  // Refresh role/name from the server's verified session on load, in case
  // localStorage is stale (e.g. an old tab, or the values were edited in
  // devtools) — the server's JWT claims are always the real source of truth.
  fetch(`${typeof CONFIG !== 'undefined' ? CONFIG.BACKEND_URL : ''}/api/auth/verify`, {
    credentials: 'include',
  })
    .then((res) => (res.ok ? res.json() : Promise.reject()))
    .then((data) => {
      const user = data?.user;
      if (!user) return;
      window.DPnitiAuth.role = user.role || window.DPnitiAuth.role;
      window.DPnitiAuth.allowedSem = user.allowed_sem ?? window.DPnitiAuth.allowedSem;
      window.DPnitiAuth.name = user.name || window.DPnitiAuth.name;
      localStorage.setItem('role', window.DPnitiAuth.role);
      localStorage.setItem('userName', window.DPnitiAuth.name);
      localStorage.setItem('allowedSem', window.DPnitiAuth.allowedSem ?? '');
      applyRoleVisibility();
    })
    .catch(() => {
      // Verify failed — session cookie is missing/expired. Nginx will catch
      // this on the next navigation, but bounce immediately for a snappier UX.
      window.location.replace('login/index.html');
    });

  function applyRoleVisibility() {
    if (window.DPnitiAuth.role === 'student') {
      document.querySelectorAll('[data-staff-only]').forEach((element) => element.remove());
    }
  }

  window.addEventListener('DOMContentLoaded', applyRoleVisibility);
})();
