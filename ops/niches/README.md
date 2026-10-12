# Adding a new course ("chapter") to The Guide

The Guide (theguide.company) teaches complete beginners to start a real side business. Each business is a
"chapter" with modules, short lessons, checklists and templates. You are writing ONE new chapter as a single JSON file.

Read one finished chapter in `web/niches/pack-1.js` first, so your output matches the house style and shape exactly.

## What to produce

Write ONE file: `<somewhere outside web/>/<id>.json`. Valid JSON, UTF-8, no comments.
Keys, in this order:

- `id` (given), `name` (given), `icon` (given), `color` (given), `description` (one plain sentence, 90-130 characters, starts with a verb like the reference).
- `modules`: exactly 4 objects `{ "title", "goal" }`. Title is short and concrete ("Set up your first job"), goal is one sentence on what the person can DO by the end.
  Suggested arc: 1 Start here (understand it, set up legally and simply, first customer-ready offer) -> 2 Do the work well (tools, process, quality, safety) -> 3 Find and win customers -> 4 Run it like a business (pricing, bookkeeping, repeat work, growing).
- `checklists`: exactly 2 objects `{ "title", "items": [6-8 short imperative strings] }` (e.g. a startup checklist and a before-every-job / per-order checklist).
- `templates`: exactly 2 objects `{ "title", "category", "body" }`. category is one of: Contract, Proposal, Estimate, Invoice, Email, Script, Policy. Body is a ready-to-use fill-in-the-blanks document with [Square Bracket] placeholders, 120-260 words, plain text with `\n\n` between paragraphs. Add one line at the end of any contract-type template: "This is a starting template, not legal advice. Have it checked for your area."
- `guides`: exactly 24 objects, SIX per module (`mod` 0,1,2,3), in the order they should be taken. In each module alternate `lesson`, `short`, `lesson`, `short`, `lesson`, `short`. Each guide has exactly these keys:
  `mod` (0-3), `kind` ("lesson" or "short"), `title`, `time` ("3 min" for lesson, "1 min" for short), `summary` (one sentence, 60-120 chars), `action` (one concrete thing to do today, starts with a verb, 1-2 sentences), `takeaway` (one short sentence), `content`.
  - Lesson `content`: 230-300 words. Short `content`: 100-135 words.
  - Use plain paragraphs separated by `\n\n`. A numbered list ("1. ...\n2. ...") or a short "Watch out for these:" list is fine in some lessons, but most are prose. No markdown headings, no bold markers, no emoji.
  - Do NOT include a `vid` key. We add it later.
- `breakdown`: this powers the "see the niche in pieces" screens in the app:
  ```
  "breakdown": {
    "group": "local" | "online" | "products" | "audience" | "bigger",   // given
    "oneLiner": "<= 60 characters, plain, what you do (e.g. 'Make cars look new at the customer's door')",
    "cost": "short honest label, e.g. 'Low: a few hundred dollars'",
    "difficulty": "Easy to start" | "Medium" | "Harder",
    "pieces": [ six objects in THIS order: "What it is", "Who it's for", "A normal week", "What it costs to start", "Tools you'll use", "The hard parts",
                each { "title", "body" (1-2 plain sentences, <= 200 chars), "points": [exactly 3 short strings, <= 70 chars each] } ]
  }
  ```

## Voice and rules (the owner reads this on his phone; so will the learners)

- Plain, short sentences. Talk to "you". Concrete and practical, like a good friend who has done it. No hype, no jargon, no filler.
- Every lesson teaches something the person can use this week. Every `action` is small, specific and doable in under an hour.
- NEVER promise or imply income ("you'll make $5k a month", "replace your job", "six figures", "passive income", "guaranteed"). No made-up statistics, no invented customer stories or testimonials, no "studies show". If you give an example price or time, label it as an example and tell the learner to check what is normal in their area.
- Anything touching licences, permits, insurance, health or food rules, safety, taxes, contracts or tax/legal advice: say plainly that rules differ by country/state/city and the learner should check their local rules (and talk to a qualified person where it matters). Do not state specific legal requirements you are not sure of. Never give tax or legal advice as if you were an accountant or lawyer.
- Only name real products and services that genuinely exist and fit (Square, Stripe, QuickBooks, Canva, Google Business Profile, Jobber, etc.). Do not recommend anything as if paid to. Don't invent features of real tools; keep tool descriptions general.
- Be honest about hard parts: slow starts, difficult customers, physical work, seasonality, competition.
- Module 1 (mod 0) is FREE for every visitor, so it has to be genuinely useful on its own: what the business really is, how to start simply and safely, and a first small offer.
- US-centric English with dollars, but nothing that breaks outside the US. No emoji anywhere except the `icon` field.
- Each module's `goal` must match what its six guides actually teach. No two guides in the chapter may share a title. Make the 24 titles specific, not generic ("Price a driveway wash by the square foot", not "Pricing tips").

## When done

1. `python3 ops/niches/validate_niche.py <id>.json`, then fix everything it reports until it prints OK.
2. Add the chapter's tool family to `ops/niches/tools.json` (`local`, `client`, `coaching`, `ecommerce` or `creator`; a `client` chapter also needs two tracker configs under `specialtyConfigs`).
3. `python3 ops/niches/build_pack.py --out web/niches/pack-N.js --label "batch N" <id>.json ...`, then add `<script src="niches/pack-N.js"></script>` next to the other pack tags in `web/index.html`.
4. A person reads the chapter before it ships. Run `bash ops/check.sh`.

A chapter with no narration yet shows no video button. Narration is made separately.
