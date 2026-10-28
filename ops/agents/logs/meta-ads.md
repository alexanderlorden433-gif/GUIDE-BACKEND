# Meta Ads agent notes

## 2026-10-10 (Sat)
- Metricool metaAds campaign/ad connectors (FACA*/FADE*) return empty rows; evolution connector (FAEV*) does return daily rows. Use FAEV04/FAEV01/FAEV05 as a fallback.
- Live check done (off-schedule, because Metricool showed no delivery): campaign ACTIVE but Meta reports no delivery since launch. Asked Alexander to check Billing / ad review in Ads Manager.
- Setup gaps vs. plan seen in live check: ad set targets US only (plan: US/CA/UK/AU); ad named "New Leads Ad" (plan: ad01-47-videos); no URL tags (UTMs missing); Multi-advertiser ads enrolled. Reported to Alexander, not changed.
- Ad set ID 120254342583220640, ad ID 120254342583210640.

## 2026-10-11 (Sun)
- Metricool evolution (FAEV*) still shows zero delivery every day Oct 4-11; FACA*/FADE* still empty. No Adspirer ad calls (not a check day, status unchanged). Reminded Alexander about Billing / ad review.
- Next live check: Mon Oct 12 — confirm delivery status and whether the setup gaps above were fixed.

## 2026-10-13 (Tue)
- No Oct 12 note found, so did a make-up live check today (Adspirer 3/15 used after it, resets Nov 4).
- Still zero delivery every day Oct 4-13 (FAEV*). FACA*/FADE* still empty. Campaign, ad set and ad all show ACTIVE, budget $5/day, but no delivery — Adspirer does not show billing or review status, so the blocker must be seen in Ads Manager (Billing / Account quality / ad review).
- Setup gaps unchanged: US only, ad named "New Leads Ad", no URL tags, Multi-advertiser ads enrolled.
- Next live check: Thu Oct 15.

## 2026-10-14 (Wed)
- Still zero delivery every day Oct 4-13 (FAEV*). FACA*/FADE* still empty. No Adspirer ad calls (not a check day, nothing changed). Adspirer 3/15, resets Nov 4.
- Next live check: Thu Oct 15 — confirm whether delivery started and whether setup gaps were fixed.

## 2026-10-15 (Thu)
- Live check done (Adspirer 5/15 after it, resets Nov 4). Campaign, ad set, ad all ACTIVE, budget $5/day, still no delivery since launch (FAEV* zero Oct 4-14; FACA*/FADE* empty). Ad set "budget remaining" shows $0.00.
- Setup gaps unchanged: US only, ad named "New Leads Ad", no URL tags, Multi-advertiser ads enrolled.
- Next live check: Mon Oct 19.

## 2026-10-16 (Fri)
- Still zero delivery every day Oct 4-15 (FAEV*). FACA*/FADE* still empty. No Adspirer ad calls (not a check day, nothing changed). Adspirer 5/15, resets Nov 4.
- Live app and ads.json both say Pro $24.99/mo (CLAUDE.md's $28.99 is out of date; ads are fine).
- Next live check: Mon Oct 19.

## 2026-10-18 (Sun)
- No Oct 17 note found. Adspirer shows 6/15 used (was 5/15 on Oct 16) — one action used outside these notes. Resets Nov 4.
- Still zero delivery every day Oct 4-17 (FAEV*). FACA*/FADE* still empty. No Adspirer ad calls (not a check day, nothing changed). No push sent (same blocker as already reported).
- Next live check: Mon Oct 19 — confirm delivery and setup gaps; add weekly review.

## 2026-10-19 (Mon)
- Live check done (Adspirer 7/15 after it, resets Nov 4). Campaign, ad set, ad all ACTIVE, budget $5/day, still no delivery since launch (FAEV* zero Oct 4-18; FACA*/FADE* empty). Ad set "budget remaining" still $0.00.
- Setup gaps unchanged: US only, ad named "New Leads Ad", no URL tags, Multi-advertiser ads enrolled.
- Gmail connector (theguidesupport@ inbox): only Meta email in 20 days is an unread "Confirm your business email" for Theguidecompany from Oct 5. No billing/rejection emails there. Flagged to Alexander.
- Next live check: Thu Oct 22.

## 2026-10-20 (Tue)
- Still zero delivery every day Oct 4-19 (FAEV*). FACA*/FADE* still empty. No Adspirer ad calls (not a check day, nothing changed). Adspirer 7/15, resets Nov 4.
- No push sent (same blocker as already reported). Next live check: Thu Oct 22.

## 2026-10-21 (Wed)
- FIRST DELIVERY: Metricool campaign data (FACA*) now shows a little delivery on Oct 20 only (well under the daily budget, 1 link click, 0 registrations). Nothing Oct 5-19, nothing yet for Oct 21. Ad-level FADE* still empty (lag).
- Treat Oct 20 as day 1 of learning: no edits before Oct 23 except to stop harm. No Adspirer ad calls (not a check day). Adspirer 7/15, resets Nov 4.
- Push sent (delivery started). Next live check: Thu Oct 22 — confirm delivery, review status, and setup gaps.

## 2026-10-22 (Thu)
- Live check done (Adspirer 8/15 after it, resets Nov 4). Campaign, ad set, ad all ACTIVE, budget $5/day. Delivery still only on Oct 20 (tiny, 1 link click, 0 registrations); nothing yet for Oct 21 (may be lag). FADE* still empty.
- Setup gaps unchanged in live config: US only, ad named "New Leads Ad", no URL tags, Multi-advertiser ads enrolled. Proposed one combined fix for Oct 23+ (after learning window), needs Alexander's OK.
- Gmail: no Meta billing/rejection emails in last 20 days.
- Push sent (live-check summary + proposal). Next live check: Mon Oct 26.

## 2026-10-23 (Fri)
- Delivery still only on Oct 20 (tiny, 1 link click, 0 registrations). Oct 21 and Oct 22 both empty in FACA* two days later — looks like delivery stopped again, not lag. FADE* still empty.
- No Adspirer ad calls (not a check day; nothing to pause). Adspirer 8/15, resets Nov 4. Setup-fix proposal from Oct 22 still waiting for Alexander's OK.
- Push sent (delivery stalled again). Next live check: Mon Oct 26 (or sooner if Alexander approves the fix).

## 2026-10-24 (Sat)
- Still no delivery Oct 21, 22, 23 (FAEV* zero; FACA* lifetime unchanged = only the tiny Oct 20 delivery). FADE* still empty.
- Adspirer shows 9/15 (was 8/15 on Oct 23) — one action used outside these notes. Resets Nov 4. No Adspirer ad calls today (not a check day, nothing to pause).
- No push sent (same stall already reported Oct 23; setup-fix proposal still waiting). Next live check: Mon Oct 26.

## 2026-10-25 (Sun)
- Still no new delivery: FACA* lifetime unchanged (only the tiny Oct 20 delivery, 1 link click, 0 registrations); yesterday (Oct 24) empty. FADE* still empty.
- Adspirer 9/15 (unchanged), resets Nov 4. No Adspirer ad calls (not a check day, nothing to pause). Setup-fix proposal from Oct 22 still waiting for Alexander's OK.
- No push sent (same stall already reported Oct 23). Next live check: Mon Oct 26 — include weekly review.

## 2026-10-27 (Tue)
- No Oct 26 note found. Adspirer shows 10/15 (was 9/15 on Oct 25) — likely the Monday live check, not logged here. Resets Nov 4. Only 5 left: 4 kept in reserve, so live checks should be skipped unless needed.
- Still no new delivery: FACA* lifetime unchanged (only the tiny Oct 20 delivery, 1 link click, 0 registrations); Oct 23-26 all empty. FADE* still empty.
- No Adspirer ad calls (not a check day, nothing to pause). Setup-fix proposal from Oct 22 still waiting for Alexander's OK.
- No push sent (same stall already reported). Next live check: Thu Oct 29 — only if it leaves 4 actions in reserve (it would: 11/15).

## 2026-10-28 (Wed)
- Still no new delivery: FACA* lifetime unchanged (only the tiny Oct 20 delivery, 1 link click, 0 registrations); yesterday (Oct 27) and last 7 days empty. FADE* still empty.
- Adspirer 10/15 (unchanged), resets Nov 4. No Adspirer ad calls (not a check day, nothing to pause). Setup-fix proposal from Oct 22 still waiting for Alexander's OK.
- No push sent (same stall already reported). Next live check: Thu Oct 29 (leaves 4 in reserve: 11/15).
