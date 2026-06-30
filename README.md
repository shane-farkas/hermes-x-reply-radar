# X Reply Radar

Strategic X/Twitter engagement finder with a web dashboard. Searches X for recent posts worth replying to, filters out noise, drafts replies in your voice for manual review — **never auto-posts**.

## What it does

1. **Searches** X for recent posts (last 4 hours) matching your target audience
2. **Filters** out buried threads, dead posts, retweets, crypto, and philosophical noise
3. **Ranks** by builder signals + engagement to surface the best candidates
4. **Drafts** replies in your voice for manual review and posting
5. **Dashboard** — browsable web UI with tabs, copy buttons, history, and on-demand reply generation

You post the replies yourself on X. This tool never auto-posts.

## Architecture

```
search.py  →  candidates.json  →  server.py (dashboard on :8747)
                              ↘  results/results_YYYYMMDD_HHMMSS.json
```

| Component | Description |
|-----------|-------------|
| `search.py` | Standalone search script. Calls `xurl` via subprocess, filters/dedupes, writes `candidates.json` with top 15 ranked + all filtered posts. No external dependencies. |
| `server.py` | Zero-dependency web dashboard (Python stdlib `http.server` only — no Flask). Serves a single-page app with inline JS/CSS. |
| `results/` | Timestamped JSON files from each cron/manual run. |
| `candidates.json` | Latest raw candidates (intermediate file). |

## Requirements

- **Python 3.8+** (stdlib only — no pip install needed)
- **[xurl](https://github.com/nicepkg/xurl)** — X/Twitter CLI tool with API v2 access
- **Optional**: [Together AI](https://together.ai) API key for on-demand reply generation (Llama-3.3-70B). Works without it — just no "Generate Reply" button.

## Quick Start

```bash
# Clone
git clone https://github.com/USER/x-reply-radar.git
cd x-reply-radar

# Create data directory
mkdir -p ~/.x-reply-radar/results

# Verify xurl is installed and authenticated
xurl auth status
xurl whoami

# Run a search
python3 search.py

# Start the dashboard
python3 server.py
# → open http://localhost:8747
```

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `X_REPLY_RADAR_DIR` | `~/.x-reply-radar` | Data directory for candidates.json and results/ |
| `X_REPLY_RADAR_XURL` | `~/.local/bin/xurl` | Path to xurl binary |
| `X_REPLY_RADAR_MY_ID` | _(empty)_ | Your X user ID — skips your own posts |
| `X_REPLY_RADAR_QUERIES` | _(built-in defaults)_ | Comma-separated search queries (overrides defaults) |
| `X_REPLY_RADAR_PORT` | `8747` | Dashboard port |
| `TOGETHER_API_KEY` | _(env)_ | Together AI key for on-demand reply generation |
| `X_REPLY_RADAR_LLM_MODEL` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | LLM model for reply generation |
| `X_REPLY_RADAR_LLM_URL` | Together AI endpoint | LLM API endpoint (any OpenAI-compatible API) |
| `X_REPLY_RADAR_REPLY_PROMPT` | _(built-in default)_ | System prompt for reply generation |

### Customizing search queries

The default query set targets AI builders. For other audiences, set `X_REPLY_RADAR_QUERIES` or edit the `DEFAULT_QUERIES` list in `search.py`. See [`references/query-sets.md`](references/query-sets.md) for proven query sets (AI builders, drone/robotics, etc.).

### Customizing the reply prompt

Set `X_REPLY_RADAR_REPLY_PROMPT` to control how the LLM drafts replies. The default is generic — add your name, projects, and style rules:

```bash
export X_REPLY_RADAR_REPLY_PROMPT="You draft replies as [your name]. Rules: casual, lowercase, one sharp question per reply. Never cheerlead. Keep under 280 chars."
```

Or write it to `~/.x-reply-radar/.env`:

```
TOGETHER_API_KEY=your_key_here
X_REPLY_RADAR_REPLY_PROMPT=Your custom system prompt here
```

## Automated Mode (cron + systemd)

### systemd service

```ini
# ~/.config/systemd/user/x-radar.service
[Unit]
Description=X Reply Radar Dashboard
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/x-reply-radar/server.py
Restart=always
RestartSec=5
Environment=HOME=/home/user

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now x-radar.service
```

### Cron job

Run `search.py` every 4 hours via crontab or your scheduler:

```bash
# crontab -e
0 */4 * * * X_REPLY_RADAR_DIR=/home/user/.x-reply-radar /usr/bin/python3 /path/to/x-reply-radar/search.py
```

The dashboard auto-refreshes every 5 minutes, so new results appear without a manual refresh.

### Results JSON schema

Each run writes `results_YYYYMMDD_HHMMSS.json`:

```json
{
  "timestamp": "ISO 8601 UTC",
  "stats": {"total_unique": N, "recent_4h": N, "after_filters": N, "selected": N},
  "candidates": [
    {
      "id": "post id",
      "url": "https://x.com/username/status/ID",
      "username": "handle",
      "author_name": "display name",
      "author_bio": "bio text",
      "followers": N,
      "text": "full post text",
      "metrics": {"replies": N, "likes": N, "retweets": N, "impressions": N},
      "is_builder": true,
      "why_selected": "1-2 sentences",
      "draft_reply": "the drafted reply text",
      "notes": "relevant notes"
    }
  ],
  "filtered_all": [...]
}
```

## Dashboard UI

- **Suggested tab** — selected candidates with draft replies, copy buttons, "Open on X" links
- **All Filtered tab** — every post that passed filters but wasn't selected. Each card has a "Generate Reply" button for on-demand LLM drafting.
- **History dropdown** — browse past runs
- **Copy buttons** — with `execCommand` fallback for non-HTTPS access (e.g. over Tailscale IP)
- **Auto-refresh** — every 5 minutes

## Hermes Agent Integration

This repo includes a `SKILL.md` for [Hermes Agent](https://hermes-agent.nousresearch.com/) users. If you run Hermes, the skill enables a chat-driven workflow where the agent runs searches, reads full post context, and drafts replies in your voice — all from a messaging platform like Telegram.

See [`SKILL.md`](SKILL.md) and [`references/dashboard-setup.md`](references/dashboard-setup.md) for the full Hermes integration guide.

## How filtering works

Posts are filtered out if they:
- Are retweets (no original text)
- Have >50 replies (your reply gets buried)
- Have zero engagement (likes, replies, retweets all 0)
- Are crypto-adjacent (text or author bio contains crypto terms)
- Are purely philosophical/motivational
- Are generic founder advice ("how to raise", "startup advice", etc.)
- Are from your own account (if `X_REPLY_RADAR_MY_ID` is set)

Authors are tagged as "builders" if their bio/name contains signals like: building, shipping, engineer, founder, developer, maker, tinker, hardware, software, AI, ML, robot. Builder-tagged posts rank higher.

## License

MIT — see [LICENSE](LICENSE).