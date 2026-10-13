# Social agent notes

- 2026-10-06 (set up by hand): Metricool connected (brand "The Guide": Instagram + TikTok).
  Posted ads 11–13 organically as the first test: Oct 6 22:25/22:30, Oct 7 and Oct 8
  (Instagram 10:00, TikTok 18:00). They're in social-posted.json and count toward the
  free plan's 20 posts this month (each network counts separately; resets on the 1st).
- Metricool needs a TikTok title (tiktokData.title) or it rejects the post.
- Video by public URL works (jsDelivr link pinned to a commit) — Metricool copies it.
- 2026-10-10 (free plan mode): 1 TikTok, affiliate/3e74973f, Oct 10 10:00 NY. 7/20 posts used in October. Rejected coaching/01078458 (messy overlapping text mid-transition) and creator/02b0e9ed (spinner-like icon). Cover at 4000ms worked.
- 2026-10-10 (2nd run, free plan mode): 1 Reel, ecommerce/04157e0b, Oct 10 12:00 NY (2h after the TikTok). 8/20 posts used in October. Also rendered design/11f6e477 and marketing/0080c838 (both fine, not posted). Cover 4700ms.
- 2026-10-11 (free plan mode): 1 TikTok, design/11f6e477, Oct 11 10:00 NY. 9/20 posts used in October. coaching/01078458 failed again (overlapping text mid-transition, 3rd time — renderer issue, skip it). creator/02b0e9ed rendered fine this time. Cover 5000ms.
- 2026-10-12 (free plan mode): 1 Reel, photo/01b381f6, Oct 12 10:00 NY. 10/20 posts used in October. Skipped coaching/01078458 (known renderer issue). Rejected local/0db994c6 (overlapping text mid-transition — same renderer issue). marketing/0080c838 rendered fine again, not posted. Cover 5000ms.
- 2026-10-13 (free plan mode): 1 TikTok, realestate/05a4b507, Oct 13 10:00 NY. 11/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue) and rendered the next three instead. creator/02b0e9ed and marketing/0080c838 fine, not posted. Cover 4500ms.
