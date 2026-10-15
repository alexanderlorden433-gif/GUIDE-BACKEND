// How big a JSON request each part of the API accepts.
//
// Most routes only ever get a few short fields, so 16 KB is plenty and keeps
// junk out. A few routes legitimately carry more:
//   - PUT /api/account saves the person's whole progress in one go (every
//     finished lesson, tools, business data, Guider chats). An active learner
//     passes 16 KB quickly; the route itself allows up to 512 KB.
//   - POST /api/ai-chat sends the last 20 messages of a Guider conversation
//     plus the chapter's lesson list; a few long answers pass 16 KB.
//   - POST /api/sites/ai sends the member's whole page, what they wrote about
//     their business and a few lessons from their chapter (about 12 KB at most).
// Before this, the first two were cut off at 16 KB, so saving silently stopped working
// and The Guider stopped answering once someone had used the app for a while.
//
// The Stripe webhook needs the raw body, so it is mounted before any of these.
const LIMITS = [
  ['/api/account', '600kb'],
  ['/api/ai-chat', '200kb'],
  ['/api/sites/ai', '48kb'],
];
const DEFAULT_LIMIT = '16kb';

function useJsonParsers(app, express) {
  for (const [path, limit] of LIMITS) app.use(path, express.json({ limit }));
  // a body that one of the parsers above already read is skipped here
  app.use(express.json({ limit: DEFAULT_LIMIT }));
}

module.exports = { useJsonParsers, LIMITS, DEFAULT_LIMIT };
