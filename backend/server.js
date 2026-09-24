require('dotenv').config();

const express = require('express');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const mysql = require('mysql2/promise');

const app = express();
const port = Number(process.env.PORT || 5000);
const jwtSecret = process.env.JWT_SECRET;
const allowedOrigins = (process.env.FRONTEND_ORIGIN || 'http://localhost')
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);
const useSecureCookie = String(process.env.COOKIE_SECURE || 'false').toLowerCase() === 'true';

if (!jwtSecret) {
  throw new Error('JWT_SECRET must be configured');
}
if (!process.env.DB_PASSWORD) {
  throw new Error('DB_PASSWORD must be configured');
}

const pool = mysql.createPool({
  host: process.env.DB_HOST || 'localhost',
  user: process.env.DB_USER || 'root',
  password: process.env.DB_PASSWORD,
  database: process.env.DB_DATABASE || 'auth_db',
  waitForConnections: true,
  connectionLimit: 10,
});

app.use(cors({ origin: allowedOrigins, credentials: true }));
app.use(express.json());
app.use(cookieParser());

const COOKIE_NAME = 'authToken';
const COOKIE_MAX_AGE_MS = 8 * 60 * 60 * 1000; // 8h, matches JWT expiry below

function setAuthCookie(res, token) {
  res.cookie(COOKIE_NAME, token, {
    httpOnly: true,
    secure: useSecureCookie,   // set COOKIE_SECURE=true once you're behind real HTTPS
    sameSite: 'lax',
    maxAge: COOKIE_MAX_AGE_MS,
    path: '/',
  });
}

app.get('/api/health', (_req, res) => res.json({ success: true }));

function semesterFromUsername(username) {
  const normalized = username.trim().toLowerCase();
  if (normalized.startsWith('23bcp')) return 7;
  if (normalized.startsWith('24bcp')) return 5;
  return null;
}

// Very small in-memory rate limiter for login attempts, keyed by IP.
// Fine for a single-instance deployment; swap for a real store (e.g. redis)
// if you ever run more than one backend instance.
const loginAttempts = new Map(); // ip -> { count, firstAttemptAt }
const LOGIN_WINDOW_MS = 1 * 60 * 1000;
const LOGIN_MAX_ATTEMPTS = 3;

function loginRateLimiter(req, res, next) {
  const ip = req.ip;
  const now = Date.now();
  const entry = loginAttempts.get(ip);

  if (!entry || now - entry.firstAttemptAt > LOGIN_WINDOW_MS) {
    loginAttempts.set(ip, { count: 1, firstAttemptAt: now });
    return next();
  }

  if (entry.count >= LOGIN_MAX_ATTEMPTS) {
    return res.status(429).json({
      success: false,
      message: 'Too many login attempts. Please try again in a few minutes.',
    });
  }

  entry.count += 1;
  next();
}

app.post('/api/auth/login', loginRateLimiter, async (req, res) => {
  const username = String(req.body?.username || '').trim();
  const password = String(req.body?.password || '');

  if (!username || !password) {
    return res.status(400).json({ success: false, message: 'Username and password are required.' });
  }

  try {
    const [rows] = await pool.execute(
      'SELECT id, username, password_hash, display_name, role, semester, active FROM users WHERE username = ? LIMIT 1',
      [username]
    );
    const user = rows[0];
    const valid = user && user.active && await bcrypt.compare(password, user.password_hash);

    if (!valid) {
      return res.status(401).json({ success: false, message: 'Invalid credentials.' });
    }

    const prefixSemester = user.role === 'student' ? semesterFromUsername(user.username) : null;
    if (prefixSemester !== null && user.semester !== prefixSemester) {
      return res.status(409).json({
        success: false,
        message: `Account semester does not match its username prefix. Expected semester ${prefixSemester}.`,
      });
    }
    const allowedSemester = user.role === 'student'
      ? (prefixSemester ?? user.semester)
      : null;

    const claims = {
      sub: String(user.id),
      username: user.username,
      name: user.display_name,
      role: user.role,
      allowed_sem: allowedSemester,
    };
    const token = jwt.sign(claims, jwtSecret, { expiresIn: '8h' });

    // Successful login clears any rate-limit strikes for this IP.
    loginAttempts.delete(req.ip);

    setAuthCookie(res, token);

    // Non-sensitive fields the frontend uses for UI only. The actual
    // authority for role/allowedSem is always the signed JWT the server
    // re-checks on every request, not these values.
    return res.json({
      success: true,
      user: {
        id: user.id,
        username: user.username,
        name: user.display_name,
        role: user.role,
        allowedSem: claims.allowed_sem,
      },
    });
  } catch (error) {
    console.error('Login failed:', error.message);
    return res.status(500).json({ success: false, message: 'Authentication service is unavailable.' });
  }
});

// Called by Nginx's auth_request for every protected page, and by the
// frontend on load to know whether the session is still valid.
app.get('/api/auth/verify', (req, res) => {
  const token = req.cookies?.[COOKIE_NAME];
  if (!token) {
    return res.status(401).json({ success: false });
  }
  try {
    const claims = jwt.verify(token, jwtSecret);
    // Nginx's auth_request only cares about the status code, but returning
    // the claims here also lets the frontend call this endpoint directly
    // to refresh its own copy of role/name for the UI.
    return res.json({ success: true, user: claims });
  } catch (error) {
    return res.status(401).json({ success: false });
  }
});

app.post('/api/auth/logout', (req, res) => {
  res.clearCookie(COOKIE_NAME, { path: '/' });
  return res.json({ success: true });
});

app.listen(port, () => console.log(`Auth API running on http://localhost:${port}`));
