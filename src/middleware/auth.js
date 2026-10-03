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

module.exports = { requireAuth, signToken };
