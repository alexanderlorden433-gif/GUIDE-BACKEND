// The name other members see next to a post, win or mentor card: the part of
// the email before the "@" (what the app has always shown). The full email
// address stays private — it is never sent to other members.
function publicName(email) {
  return String(email || '').split('@')[0] || 'Guide User';
}

module.exports = { publicName };
