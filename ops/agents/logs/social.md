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
- 2026-10-14 (free plan mode): 1 Reel, ugc/18d79da3, Oct 14 10:00 NY. 12/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue). marketing/0080c838 and social/07aad8d3 rendered fine, not posted. Cover 5000ms.
- 2026-10-15 (free plan mode): 1 TikTok, marketing/0080c838, Oct 15 10:00 NY. 13/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue). creator/02b0e9ed and social/07aad8d3 rendered fine, not posted. jsDelivr url failed ("Failed to normalize media"), raw_url worked. Cover 4000ms.
- 2026-10-16 (free plan mode): 1 Reel, social/07aad8d3, Oct 16 10:00 NY. 14/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue). creator/02b0e9ed rendered fine, trading/01230763 rendered, not posted. jsDelivr url worked this time. Cover 3500ms.
- 2026-10-17 (free plan mode): 1 TikTok, video/05efc793, Oct 17 10:00 NY. 15/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue) and trading/01230763 (money topic). creator/02b0e9ed and va/03b1fbfa rendered fine, not posted. jsDelivr url worked. Cover 4500ms.
- 2026-10-18 (free plan mode): 1 Reel, writing/07cfe972, Oct 18 10:00 NY. 16/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue) and trading/01230763 (money topic). creator/02b0e9ed and va/03b1fbfa rendered fine, not posted. jsDelivr url worked. Cover 4500ms.
- 2026-10-19 (free plan mode): 1 TikTok, ecommerce/08878ed8, Oct 19 18:00 NY (best time). 17/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue) and trading/01230763 (money topic). creator/02b0e9ed and va/03b1fbfa rendered (va fine), not posted. jsDelivr url worked. Cover 4500ms.
- 2026-10-20 (free plan mode): 1 Reel, va/03b1fbfa, Oct 20 10:00 NY. 18/20 posts used in October. Skipped coaching/01078458 and local/0db994c6 (known renderer issue), trading/01230763 (money topic) and creator/02b0e9ed (tax/income topic). Rejected design/1325e4e4 (overlapping text mid-transition). affiliate/43f614a3 rendered fine, not posted. jsDelivr url worked. Cover 4500ms.
- 2026-10-21 (free plan mode): 1 TikTok, ugc/1e17157a, Oct 21 10:00 NY (best time). 19/20 posts used in October. Skipped coaching/01078458, local/0db994c6 (renderer issue), trading/01230763, creator/02b0e9ed (money topics), design/1325e4e4 (rejected before). Rejected photo/0451f7e8 (overlapping text mid-transition). affiliate/43f614a3 rendered fine, not posted (income angle). jsDelivr url worked. Cover 5500ms.
- 2026-10-22 (free plan mode): 1 Reel, writing/2b6129ce, Oct 22 10:00 NY (best time). 20/20 posts used in October — plan full until Nov 1. Skipped the known-bad/money-topic lessons. Rejected realestate/09559fef and marketing/040693fc (overlapping text mid-transition caught in frames). jsDelivr url worked. Cover 5750ms.
- 2026-10-23 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-24 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-25 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-26 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-27 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-28 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-29 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
- 2026-10-30 (free plan mode): posted nothing — October is full (20/20). Posting restarts Nov 1.
