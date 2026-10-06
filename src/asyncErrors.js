// Express 4 does not catch errors thrown inside `async` route handlers.
// Without this, an unexpected error (for example a brief database hiccup)
// never reaches the error handler in index.js: the request never gets an
// answer and Node stops the whole server. This sends those errors to the
// normal error handler instead, so the visitor gets a friendly 500 and the
// server keeps running for everyone else.
const Layer = require('express/lib/router/layer');

const original = Layer.prototype.handle_request;

Layer.prototype.handle_request = function handleRequest(req, res, next) {
  const fn = this.handle;
  if (fn.length > 3) return original.call(this, req, res, next); // error handlers
  try {
    const result = fn(req, res, next);
    if (result && typeof result.then === 'function') result.catch(next);
  } catch (err) {
    next(err);
  }
};
