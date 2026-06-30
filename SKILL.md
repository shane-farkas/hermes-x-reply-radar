---
name: x-reply-radar
description: "Given a strategic goal, find recent X posts worth engaging with and draft replies in the user's voice for manual review and posting."
version: 1.2.0
tags: [twitter, x, social-media, engagement, xurl, reply-drafting]
prerequisites:
  commands: [xurl]
---

# x-reply-radar — Strategic X Engagement Finder & Reply Drafter

Given a goal (who to reach, what angle, what style rules), this skill:
1. Searches X for recent posts (last 4 hours) matching the target audience
2. Filters out buried threads, dead posts, and off-topic content
3. Drafts replies in the user's voice for manual review and posting

The user posts the replies themselves on X. This skill never auto-posts.

---

## Workflow

### Step 1 — Intake the Goal

The user provides a goal that may include:
- Target audience (who they want to reach)
- Angle / positioning (how they want to be seen)
- Style rules (what to do, what to avoid)
- A GitHub URL for builder context
- Topic include/exclude filters

Parse the goal and extract these components. If the goal is ambiguous, ask for clarification before proceeding.

### Step 2 — Gather Builder Context (if GitHub URL provided)

If the goal includes a GitHub URL, fetch the user's public repos to understand what they actually build. Use `web_extract` on the profile URL, or:

```bash
curl -s https://api.github.com/users/USERNAME/repos?sort=updated | python3 -c "
import sys, json
repos = json.load(sys.stdin)
for r in repos:
    print(f'{r[\"name\"]}: {r[\"description\"] or \"(no desc)\"} [{r[\"language\"] or \"?\"}]')
"
```

Summarize the repos concisely (name, description, language). Use this to:
- Know what projects exist (for natural references only)
- Understand technical depth and domains
- NEVER force projects into replies unless directly relevant to the post's pain point

### Step 3 — Derive Search Queries

From the goal's audience and topic areas, derive 6-12 search queries. Patterns that find builders showing their work:

- `"just shipped" <domain_term>` — product launches
- `"working on" <domain_term>` — work in progress
- `"built a" <domain_term>` — completed builds
- `"#buildinpublic" <domain_term> lang:en` — builder community
- `"show HN" <domain_term>` — show-and-tell energy
- `"anyone using" <tool_term>` — pain point surfacing
- `"struggling with" <domain_term>` — help wanted
- `"just launched" <domain_term>` — new products
- `"open source" <domain_term>` — OSS builders
- `from:<specific_handle>` — if goal names specific accounts to monitor

Domain terms are extracted from the goal. For an AI/robotics goal: "AI agent", "LLM", "inference", "robotics", "local model", "fine-tune", "RAG", "embedding", "autonomous", "Jetson", "edge compute", etc.

See `references/query-sets.md` for a proven query set tested against an AI builder goal (15 queries, 305 results, 6 strong candidates).

### Step 4 — Execute Searches and Filter

Use `execute_code` to batch all searches, parse JSON, filter, and deduplicate. This keeps raw JSON out of the conversation context.

#### Search command

Use raw API mode with author expansions to get usernames in one call:

```bash
xurl '/2/tweets/search/recent?query=<URL_ENCODED_QUERY>&max_results=30&expansions=author_id&tweet.fields=created_at,public_metrics,lang,referenced_tweets,in_reply_to_user_id,possibly_sensitive&user.fields=name,username,description,public_metrics'
```

The response includes `data` (posts) and `includes.users` (author info indexed by `author_id`).

#### execute_code batch pattern

```python
from hermes_tools import terminal
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

queries = [
    # ... derived from goal
]

all_posts = []
author_cache = {}

for q in queries:
    encoded = quote(q)
    cmd = f'xurl \'/2/tweets/search/recent?query={encoded}&max_results=30&expansions=author_id&tweet.fields=created_at,public_metrics,lang,referenced_tweets,in_reply_to_user_id,possibly_sensitive&user.fields=name,username,description,public_metrics\' 2>&1'
    result = terminal(cmd)
    try:
        data = json.loads(result["output"])
    except:
        continue
    for user in data.get("includes", {}).get("users", []):
        author_cache[user["id"]] = user
    for post in data.get("data", []):
        post["_author"] = author_cache.get(post.get("author_id"), {})
        all_posts.append(post)

# Deduplicate
seen = set()
unique = []
for p in all_posts:
    if p["id"] not in seen:
        seen.add(p["id"])
        unique.append(p)

# Filter by recency (last 4 hours)
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=4)
recent = []
for p in unique:
    try:
        created = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
        if created > cutoff:
            recent.append(p)
    except:
        pass

# Filter by engagement and topic
filtered = []
for p in recent:
    metrics = p.get("public_metrics", {})
    replies = metrics.get("reply_count", 0)
    likes = metrics.get("like_count", 0)
    rts = metrics.get("retweet_count", 0)
    text = p.get("text", "").lower()
    author = p.get("_author", {})
    author_name = author.get("name", "").lower()
    author_desc = author.get("description", "").lower()
    username = author.get("username", "unknown")

    if p.get("referenced_tweets") and "retweeted" in [rt.get("type") for rt in p["referenced_tweets"]]:
        continue
    if replies > 50:
        continue
    if likes == 0 and replies == 0 and rts == 0:
        continue

    crypto_terms = ["crypto", "nft", "web3", "token", "solana", "ethereum", "bitcoin", "degen", "floor price", "mint"]
    if any(term in text or term in author_desc for term in crypto_terms):
        continue

    phil_terms = ["meaning of", "consciousness is", "we are all", "in the end", "life is about", "remember this"]
    if any(term in text for term in phil_terms):
        continue

    generic_terms = ["here's how to raise", "startup advice", "how to pitch", "how to network", "10 things"]
    if any(term in text for term in generic_terms):
        continue

    builder_signals = ["building", "shipping", "engineer", "founder", "developer", "maker", "tinker", "hardware", "software", "ai", "ml", "robot"]
    is_builder = any(s in author_desc or s in author_name for s in builder_signals)

    filtered.append({
        "id": p["id"], "text": p.get("text", ""), "created_at": p.get("created_at", ""),
        "username": username, "author_name": author.get("name", ""),
        "author_bio": author.get("description", ""),
        "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
        "replies": replies, "likes": likes, "retweets": rts,
        "impressions": metrics.get("impression_count", 0), "is_builder": is_builder,
        "url": f"https://x.com/{username}/status/{p['id']}"
    })

filtered.sort(key=lambda p: (p["is_builder"], p["likes"] + p["replies"] * 2), reverse=True)

for i, p in enumerate(filtered[:15], 1):
    print(f"--- Post {i} ---")
    print(f"URL: {p['url']}")
    print(f"Author: @{p['username']} ({p['author_name']})")
    print(f"Bio: {p['author_bio'][:120]}")
    print(f"Followers: {p['author_followers']}")
    print(f"Text: {p['text'][:300]}")
    print(f"Replies: {p['replies']} | Likes: {p['likes']} | RTs: {p['retweets']} | Impressions: {p['impressions']}")
    print(f"Builder: {p['is_builder']}")
    print()

print(f"Total unique: {len(unique)} | Recent (4h): {len(recent)} | After filters: {len(filtered)}")
```

### Step 5 — Select Top Candidates

From the filtered list, pick 5-10 best posts. For each, verify:
- The post has a natural opening for a technical observation or question
- The author is genuinely building something specific (not just opining)
- The thread isn't already a pile-on (too many replies = your reply gets lost)
- The post isn't from the user's own account (skip self-posts)

If fewer than 5 good candidates exist, report what you found honestly. Don't force bad fits.

### Step 6 — Read Full Context

Batch all context reads in `execute_code` using `hermes_tools.terminal`:

```python
from hermes_tools import terminal
import json

ids_to_read = [...]  # from Step 5 selection + any referenced tweet IDs

for post_id in ids_to_read:
    result = terminal(f'xurl read {post_id} 2>&1')
    try:
        d = json.loads(result["output"])
        t = d.get("data", {})
        print(f"=== {post_id} ===")
        print(t.get("text", "")[:600])
        print(f"Metrics: {json.dumps(t.get('public_metrics', {}))}")
    except:
        print(f"=== {post_id} === (parse failed or link-only post)")
    print()
```

If the post is a reply, include the parent post ID. If it quotes another tweet, include that too.

#### Amplification posts

Some results are amplification posts — someone sharing/boosting another person's build. For these:
- Note in the presentation that it's an amplification post
- The reply may make more sense directed at the original builder
- Offer to find the original builder if the user prefers to reply there instead

### Step 7 — Draft Replies

For each selected post, draft a reply following the user's style constraints from the goal.

#### Default style (ALWAYS defer to goal-specific rules)

- Casual, direct, lowercase, brief
- One sharp observation, question, or technical detail per reply. That's it.
- Never cheerlead. Never open with praise ("great post!", "love this!").
- Never pitch yourself directly.
- Only mention the user's projects if the post describes a real pain point that a project genuinely solves. When in doubt, leave it out.
- Ask pointed technical questions when someone shares what they're building.
- Offer to test their stuff when appropriate.
- No em dashes. No AI-sounding vocabulary ("delve", "tapestry", "navigate", "it's worth noting").
- No generic platitudes.
- Match the register of the post. If they're technical, be technical. If they're casual, be casual.
- Keep it under 280 characters when possible.

#### What NOT to draft

- Replies that just agree or validate ("100%", "so true")
- Replies that hijack the thread to talk about the user's projects
- Replies that could apply to any post ("interesting approach, tell me more")
- Replies longer than the original post
- Replies that argue or correct unless the user's goal explicitly calls for that

### Step 8 — Present for Review

Present each candidate in this format:

```
POST N
  Author: @handle (Name) — Followers: N
  Bio: (first 100 chars)
  URL: https://x.com/handle/status/ID
  Post text: (full text)
  Replies: N | Likes: N | Impressions: N
  Why selected: (1-2 sentences on why this post fits the goal)
  Context: (if part of a thread, 1 sentence on the parent)

  DRAFT REPLY:
  (the drafted reply text)

  Notes: (any relevant notes)
```

---

## Automated Dashboard Mode

Instead of running inline in a chat session, the radar can run on a cron schedule with a web dashboard. See `references/dashboard-setup.md` for the complete setup recipe.

### Architecture

- `search.py` — standalone search script (subprocess + xurl, no agent tools needed). Runs queries, filters, writes `candidates.json`.
- `server.py` — zero-dependency web dashboard (Python stdlib `http.server`). Serves on port 8747.
- `results/` — timestamped JSON files from each cron run.
- `candidates.json` — latest raw candidates.

### Cron job

Run `search.py` every 4 hours. The cron agent or script then:
1. Reads `candidates.json`
2. Selects top 5-8 candidates
3. Reads full context with `xurl read POST_ID`
4. Drafts replies per the goal's style rules
5. Writes results to `results/results_YYYYMMDD_HHMMSS.json`

---

## Important Rules

1. NEVER auto-post. Always present drafts for manual review.
2. Respect the user's style constraints from the goal EXACTLY.
3. If no good candidates found, say so honestly. Don't force bad fits.
4. Keep raw JSON out of the conversation — use execute_code for batch search/filter.
5. Verify xurl auth before starting: `xurl auth status` + `xurl whoami`. Do NOT pipe either to python3 for parsing — it triggers a security scan. Run them bare or inside execute_code.
6. The 4-hour window is a default. If the goal specifies a different window, use that.
7. Skip the user's own posts (match author_id against the whoami result).
8. If the goal names specific accounts to monitor, always include `from:handle` queries.

## Pitfalls

- **Security scan on `xurl | python3` pipes**: Piping xurl output to python3 in a terminal call triggers a HIGH security scan. Fix: always use `execute_code` with `hermes_tools.terminal` for any xurl output that needs JSON parsing.
- **Amplification posts inflate candidate count**: Many "just shipped" / "built a" results are amplifiers sharing someone else's work. Check whether the post text describes the author's own work or someone else's.
- **`xurl read` on video/link-only posts returns bare URLs**: Some quoted posts are just t.co links with no text. Don't treat this as a parse error.
- **Copy button fails on non-HTTPS**: `navigator.clipboard` API only works on HTTPS or localhost. server.py has a `document.execCommand('copy')` fallback for non-secure contexts.
- **CSS class vs id mismatch breaks flex tabs**: The tabs container must have `class="tabs"` (not just `id="tabs"`) for the flex layout CSS to apply.