#!/usr/bin/env python3
"""X Reply Radar — Search & Filter Script

Runs xurl searches against the X/Twitter API v2 recent search endpoint,
filters candidates, and writes results to candidates.json.

Standalone — no Hermes tools needed, just subprocess + xurl.

Configuration via environment variables:
  X_REPLY_RADAR_DIR     — data directory (default: ~/.x-reply-radar)
  X_REPLY_RADAR_XURL     — path to xurl binary (default: ~/.local/bin/xurl)
  X_REPLY_RADAR_MY_ID    — your X user ID (to skip self-posts, optional)
  X_REPLY_RADAR_QUERIES — comma-separated list of search queries (optional override)
"""
import subprocess
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ---------- Configuration ----------
DATA_DIR = os.environ.get("X_REPLY_RADAR_DIR", os.path.expanduser("~/.x-reply-radar"))
XURL = os.environ.get("X_REPLY_RADAR_XURL", os.path.expanduser("~/.local/bin/xurl"))
MY_ID = os.environ.get("X_REPLY_RADAR_MY_ID", "")
RESULTS_DIR = DATA_DIR
CANDIDATES_FILE = os.path.join(RESULTS_DIR, "candidates.json")

# Default query set — tuned for AI builders, adjust for your own goal.
# Override at runtime with X_REPLY_RADAR_QUERIES (comma-separated).
DEFAULT_QUERIES = [
    '"just shipped" AI agent lang:en',
    '"just shipped" LLM lang:en',
    '"just shipped" robotics lang:en',
    '"working on" AI agent lang:en',
    '"working on" LLM inference lang:en',
    '"built a" AI agent lang:en',
    '"built a" robotics lang:en',
    '#buildinpublic AI lang:en',
    '#buildinpublic LLM lang:en',
    '"just launched" AI agent lang:en',
    '"open source" AI agent lang:en',
    '"anyone using" local model lang:en',
    '"struggling with" RAG lang:en',
    '"working on" edge compute lang:en',
]

QUERIES = (
    os.environ.get("X_REPLY_RADAR_QUERIES", "").split(",")
    if os.environ.get("X_REPLY_RADAR_QUERIES")
    else DEFAULT_QUERIES
)


def run_search(query):
    """Run a single xurl search against the X API v2 recent search endpoint."""
    encoded = quote(query)
    endpoint = (
        f"/2/tweets/search/recent?query={encoded}&max_results=30"
        "&expansions=author_id"
        "&tweet.fields=created_at,public_metrics,lang,referenced_tweets,in_reply_to_user_id,possibly_sensitive"
        "&user.fields=name,username,description,public_metrics"
    )
    try:
        result = subprocess.run(
            [XURL, endpoint],
            capture_output=True, text=True, timeout=30
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"  WARN: query failed: {query[:50]}... ({e})", file=sys.stderr)
        return {}


def main():
    all_posts = []
    author_cache = {}

    for i, q in enumerate(QUERIES, 1):
        print(f"  [{i}/{len(QUERIES)}] {q[:60]}...")
        data = run_search(q)
        for user in data.get("includes", {}).get("users", []):
            author_cache[user["id"]] = user
        for post in data.get("data", []):
            post["_author"] = author_cache.get(post.get("author_id"), {})
            all_posts.append(post)

    # Deduplicate by post ID
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
        except Exception:
            pass

    # Filter by engagement and topic
    filtered = []
    for p in recent:
        if MY_ID and p.get("author_id") == MY_ID:
            continue

        metrics = p.get("public_metrics", {})
        replies = metrics.get("reply_count", 0)
        likes = metrics.get("like_count", 0)
        rts = metrics.get("retweet_count", 0)
        impressions = metrics.get("impression_count", 0)
        text = p.get("text", "").lower()
        author = p.get("_author", {})
        author_name = author.get("name", "").lower()
        author_desc = author.get("description", "").lower()
        username = author.get("username", "unknown")

        # Skip retweets
        if p.get("referenced_tweets"):
            if "retweeted" in [rt.get("type") for rt in p["referenced_tweets"]]:
                continue

        # Skip buried threads (>50 replies)
        if replies > 50:
            continue

        # Skip dead posts (zero engagement)
        if likes == 0 and replies == 0 and rts == 0:
            continue

        # Skip crypto-adjacent
        crypto_terms = ["crypto", "nft", "web3", "token", "solana", "ethereum",
                        "bitcoin", "degen", "floor price", "mint"]
        if any(term in text or term in author_desc for term in crypto_terms):
            continue

        # Skip purely philosophical / motivational
        phil_terms = ["meaning of", "consciousness is", "we are all",
                      "in the end", "life is about", "remember this"]
        if any(term in text for term in phil_terms):
            continue

        # Skip generic founder advice
        generic_terms = ["here's how to raise", "startup advice",
                         "how to pitch", "how to network", "10 things"]
        if any(term in text for term in generic_terms):
            continue

        # Author quality: prefer builders
        builder_signals = ["building", "shipping", "engineer", "founder",
                           "developer", "maker", "tinker", "hardware",
                           "software", "ai", "ml", "robot"]
        is_builder = any(s in author_desc or s in author_name for s in builder_signals)

        filtered.append({
            "id": p["id"],
            "text": p.get("text", ""),
            "created_at": p.get("created_at", ""),
            "author_id": p.get("author_id", ""),
            "username": username,
            "author_name": author.get("name", ""),
            "author_bio": author.get("description", ""),
            "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
            "replies": replies,
            "likes": likes,
            "retweets": rts,
            "impressions": impressions,
            "is_builder": is_builder,
            "in_reply_to": p.get("in_reply_to_user_id"),
            "referenced": p.get("referenced_tweets", []),
            "url": f"https://x.com/{username}/status/{p['id']}"
        })

    # Rank: builders first, then by engagement
    filtered.sort(key=lambda p: (p["is_builder"], p["likes"] + p["replies"] * 2), reverse=True)

    output = {
        "timestamp": now.isoformat(),
        "stats": {
            "total_unique": len(unique),
            "recent_4h": len(recent),
            "after_filters": len(filtered)
        },
        "candidates": filtered[:15],
        "filtered_all": filtered
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(CANDIDATES_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nSearch complete: {len(unique)} unique, {len(recent)} recent, {len(filtered)} after filters")
    print(f"Top {min(15, len(filtered))} candidates written to {CANDIDATES_FILE}")
    print(f"Stats: {json.dumps(output['stats'])}")


if __name__ == "__main__":
    main()