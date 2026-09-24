const form = document.getElementById('login-form');
const error = document.getElementById('login-error');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  error.textContent = '';
  const username = form.username.value.trim();
  const password = form.password.value;

  try {
    const response = await fetch(`${CONFIG.BACKEND_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include', // required so the browser stores the httpOnly auth cookie
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || 'Login failed.');

    // A login always starts a fresh chatbot conversation.
    localStorage.removeItem('dpniti_chat_messages');
    // The auth token itself now lives in an httpOnly cookie set by the
    // server — it is never touched by JavaScript. Only non-sensitive
    // display fields go in localStorage, purely for the UI.
    localStorage.setItem('userName', data.user.name);
    localStorage.setItem('role', data.user.role);
    localStorage.setItem('allowedSem', data.user.allowedSem || '');
    window.location.href = '../dashboard.html';
  } catch (err) {
    error.textContent = err.message;
  }
});
