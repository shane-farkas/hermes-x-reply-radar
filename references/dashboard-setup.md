# Dashboard Setup Recipe

Complete setup for the automated X Reply Radar dashboard mode.

## Files

| File | Purpose |
|------|---------|
| `search.py` | Standalone search script. Calls xurl via subprocess, filters/dedupes, writes `candidates.json` with both `candidates` (top 15 ranked) and `filtered_all` (all posts that passed filters). No external dependencies. |
| `server.py` | Zero-dep web dashboard. Python stdlib `http.server` only. Serves on port 8747. |
| `candidates.json` | Latest raw candidates from search.py (intermediate file). |
| `results/results_YYYYMMDD_HHMMSS.json` | Timestamped results from each cron run (what the dashboard displays). |

## Setup Steps

### 1. Install xurl

Install [xurl](https://github.com/nicepkg/xurl) and authenticate:

```bash
xurl auth status
xurl whoami
```

### 2. Create data directory

```bash
mkdir -p ~/.x-reply-radar/results
```

### 3. Run a search

```bash
python3 search.py
```

This writes `~/.x-reply-radar/candidates.json` with filtered candidates.

### 4. Start the dashboard

```bash
python3 server.py
# → http://localhost:8747
```

### 5. systemd service (optional, for auto-start on boot)

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

Requires lingering enabled:
```bash
sudo loginctl enable-linger $(whoami)
```

### 6. Cron job

Run `search.py` every 4 hours via crontab:

```bash
# crontab -e
0 */4 * * * /usr/bin/python3 /path/to/x-reply-radar/search.py
```

Or use a scheduler like Hermes Agent's cron system for agent-driven runs that also draft replies.

### 7. On-demand reply generation (optional)

Set `TOGETHER_API_KEY` to enable the "Generate Reply" button on the All Filtered tab:

```bash
export TOGETHER_API_KEY=your_key_here
# or write to ~/.x-reply-radar/.env
```

The server uses Llama-3.3-70B by default. Override with `X_REPLY_RADAR_LLM_MODEL` and `X_REPLY_RADAR_LLM_URL` for any OpenAI-compatible API.

## Results JSON schema

Each results file has `timestamp`, `stats`, `candidates` (5-8 selected with draft replies), and `filtered_all` (all posts that passed filters).

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dashboard shows "Loading..." forever | server.py not running | Check if process is running |
| Copy button clicks but nothing copies | Non-HTTPS access (e.g. tailscale IP) | server.py has execCommand fallback — make sure you have the latest version |
| Cron runs but no results file appears | xurl auth expired or search.py failed | Run `python3 search.py` manually to diagnose |
| New results don't appear on dashboard | Browser cache | Dashboard auto-refreshes every 5 min; hard refresh with Ctrl+Shift+R |
| Tabs stack vertically instead of side by side | Tabs container missing `class="tabs"` | Add `class="tabs"` to the div — the CSS targets the class, not the id |