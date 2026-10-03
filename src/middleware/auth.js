const jwt = require('jsonwebtoken');

const JWT_ISSUER = 'theguide';
const JWT_AUDIENCE = 'theguide-app';

// Fail fast if the secret isn't set — better than silently signing with
// undefined, which jwt.sign would throw on anyway but with a confusing error.
if (!process.env.JWT_SECRET) {
  console.error('FATAL: JWT_SECRET environment variable is not set.');
  process.exit(1);
}

/**
 * Reads the "Authorization: Bearer <token>" header, verifies it, and attaches
 * { id, email } to req.user. Rejects with 401 if missing or invalid.
 */
function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : null;

  if (!token) {
    return res.status(401).json({ error: 'Missing or invalid Authorization header.' });
  }

  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET, {
      issuer: JWT_ISSUER,
      audience: JWT_AUDIENCE,
    });
    req.user = { id: payload.sub, email: payload.email };
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token.' });
  }
}

/**
 * Like requireAuth, but never rejects: attaches req.user when a valid token is
 * present and simply carries on when it isn't. For public endpoints (like
 * analytics collection) that behave slightly differently for signed-in users.
 */
function optionalAuth(req, res, next) {
  const header = req.headers.authorization || '';
  // Beacon-style requests can't set headers, so they may carry the token in
  // the body instead (field "tk").
  const bodyToken = req.body && typeof req.body.tk === 'string' ? req.body.tk : null;
  const token = header.startsWith('Bearer ') ? header.slice(7) : bodyToken;
  if (token) {
    try {
      const payload = jwt.verify(token, process.env.JWT_SECRET, {
        issuer: JWT_ISSUER,
        audience: JWT_AUDIENCE,
      });
      req.user = { id: payload.sub, email: payload.email };
    } catch (err) { /* treat as signed out */ }
  }
  next();
}

function signToken(user) {
  return jwt.sign(
    { sub: user.id, email: user.email },
    process.env.JWT_SECRET,
    {
      expiresIn: process.env.JWT_EXPIRES_IN || '30d',
      issuer: JWT_ISSUER,
      audience: JWT_AUDIENCE,
    }
  );
}

module.exports = { requireAuth, optionalAuth, signToken };
