#!/usr/bin/env python3
"""X Reply Radar: Web Dashboard

Zero-dependency HTTP server (Python stdlib only). Serves search candidates
with a browsable UI, draft replies, copy buttons, history, and on-demand
reply generation via an LLM API.

Configuration via environment variables:
  X_REPLY_RADAR_DIR          data directory (default: ~/.x-reply-radar)
  X_REPLY_RADAR_HOST         bind address (default: 127.0.0.1; set 0.0.0.0 to expose)
  X_REPLY_RADAR_PORT         port number (default: 8747)
  X_REPLY_RADAR_LLM_PROVIDER which LLM to use: together (default), openai, or anthropic
  X_REPLY_RADAR_LLM_MODEL    model name (default depends on the provider)
  X_REPLY_RADAR_LLM_URL      override the API endpoint (default depends on the provider)
  X_REPLY_RADAR_LLM_DISABLE_REASONING  if set (1/true/yes), sends reasoning:{enabled:false} to OpenAI-compatible providers
                                        (needed for reasoning models like DeepSeek-V4-Pro on Together, which otherwise
                                         burn max_tokens on thinking and return empty content)
  X_REPLY_RADAR_REPLY_PROMPT system prompt for reply generation (see DEFAULT_REPLY_PROMPT below)

API key: set the key env var for your provider (TOGETHER_API_KEY, OPENAI_API_KEY,
or ANTHROPIC_API_KEY), or a generic X_REPLY_RADAR_API_KEY. Keys are read from the
environment or from ~/.x-reply-radar/.env (also ~/.hermes/.env, ~/.env).
"""
import json
import os
import glob
import socket
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

# ---------- Configuration ----------
DATA_DIR = os.environ.get("X_REPLY_RADAR_DIR", os.path.expanduser("~/.x-reply-radar"))
RESULTS_DIR = os.path.join(DATA_DIR, "results")
CANDIDATES_FILE = os.path.join(DATA_DIR, "candidates.json")
PORT = int(os.environ.get("X_REPLY_RADAR_PORT", "8747"))
# Bind to loopback by default. The dashboard has no auth and the reply endpoint
# spends your LLM API key, so only expose it beyond localhost deliberately
# (e.g. X_REPLY_RADAR_HOST=0.0.0.0 behind a trusted network like Tailscale).
HOST = os.environ.get("X_REPLY_RADAR_HOST", "127.0.0.1")

# ---------- LLM config ----------
# Three providers work out of the box. Pick one with X_REPLY_RADAR_LLM_PROVIDER
# and set the matching API key. "together" and "openai" share the
# OpenAI-compatible chat-completions shape; "anthropic" uses the Messages API.
# Any other OpenAI-compatible endpoint works too: set provider to "openai" and
# override X_REPLY_RADAR_LLM_URL / X_REPLY_RADAR_LLM_MODEL.
PROVIDERS = {
    "together": {
        "style": "openai",
        "url": "https://api.together.xyz/v1/chat/completions",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "key_env": "TOGETHER_API_KEY",
    },
    "openai": {
        "style": "openai",
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "style": "anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-haiku-4-5",
        "key_env": "ANTHROPIC_API_KEY",
    },
}

PROVIDER = os.environ.get("X_REPLY_RADAR_LLM_PROVIDER", "together").lower()
if PROVIDER not in PROVIDERS:
    PROVIDER = "together"
_provider = PROVIDERS[PROVIDER]

# Explicit env overrides win over the provider's defaults.
LLM_STYLE = _provider["style"]
LLM_URL = os.environ.get("X_REPLY_RADAR_LLM_URL", _provider["url"])
LLM_MODEL = os.environ.get("X_REPLY_RADAR_LLM_MODEL", _provider["model"])
LLM_KEY_ENV = _provider["key_env"]
ANTHROPIC_VERSION = os.environ.get("X_REPLY_RADAR_ANTHROPIC_VERSION", "2023-06-01")

DEFAULT_REPLY_PROMPT = """You draft a concise reply to a social media post on behalf of the user.

Rules:
- Casual, direct, lowercase, brief
- One sharp technical question or observation per reply. That's it.
- No cheerleading, no opening with praise ("great post!", "love this!")
- **No em dashes. Ever.** Use commas, periods, or restructure the sentence instead. Em dashes are an AI-writing tell.
- No AI-sounding vocabulary ("delve", "tapestry", "navigate", "it's worth noting")
- No generic platitudes. No "congrats on shipping!" unless you have something specific to add after it.
- Match the register of the post. Technical if they're technical, casual if they're casual.
- Keep under 280 characters when possible.
- Output ONLY the reply text. No preamble, no explanation, no quotes, no labels."""

REPLY_SYSTEM_PROMPT = os.environ.get("X_REPLY_RADAR_REPLY_PROMPT", DEFAULT_REPLY_PROMPT)


def _load_api_key():
    """Find the API key for the active provider.

    Checks the provider's key env var (TOGETHER_API_KEY, OPENAI_API_KEY, or
    ANTHROPIC_API_KEY) and a generic X_REPLY_RADAR_API_KEY, looking first in the
    environment and then in common .env files.
    """
    candidates = [LLM_KEY_ENV, "X_REPLY_RADAR_API_KEY"]
    for name in candidates:
        val = os.environ.get(name, "")
        if val:
            return val
    for env_path in (
        os.path.expanduser("~/.hermes/.env"),
        os.path.expanduser("~/.x-reply-radar/.env"),
        os.path.expanduser("~/.env"),
    ):
        if not os.path.exists(env_path):
            continue
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):]
                for name in candidates:
                    prefix = name + "="
                    if line.startswith(prefix):
                        return line[len(prefix):].strip().strip('"').strip("'")
    return ""


def generate_reply_llm(post_data: dict) -> dict:
    """Call the configured LLM provider to generate a reply draft.
    Returns {"draft_reply": "..."} or {"error": "..."}."""
    api_key = _load_api_key()
    if not api_key:
        return {"error": f"No API key found. Set {LLM_KEY_ENV} in env or ~/.x-reply-radar/.env"}

    text = post_data.get("text", "")
    username = post_data.get("username", "unknown")
    author_name = post_data.get("author_name", "")
    author_bio = post_data.get("author_bio", "")

    user_msg = f'Post by @{username} ({author_name}):\n"{text}"\n'
    if author_bio:
        user_msg += f"\nAuthor bio: {author_bio}"

    if LLM_STYLE == "anthropic":
        # Anthropic Messages API: system is a top-level field, the reply text
        # comes back as content[0].text, and auth uses x-api-key.
        body = json.dumps({
            "model": LLM_MODEL,
            "max_tokens": 200,
            "system": REPLY_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_msg}],
        }).encode()
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "user-agent": "x-reply-radar/1.0",
        }
    else:
        # OpenAI-compatible chat completions (Together, OpenAI, or any
        # compatible endpoint via X_REPLY_RADAR_LLM_URL).
        body_dict = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.5,
            "max_tokens": 200,
        }
        # Reasoning models (e.g. DeepSeek-V4-Pro on Together) burn the entire
        # max_tokens budget on internal "thinking" tokens and return an empty
        # content string. Setting X_REPLY_RADAR_LLM_DISABLE_REASONING=1 sends
        # the standard OpenAI-style reasoning:{enabled:false} flag, which
        # Together and most OpenAI-compatible providers honor to suppress
        # thinking output. Anthropic uses thinking={"type":"disabled"}
        # separately and is handled below.
        if os.environ.get("X_REPLY_RADAR_LLM_DISABLE_REASONING", "").lower() in ("1", "true", "yes"):
            body_dict["reasoning"] = {"enabled": False}
        body = json.dumps(body_dict).encode()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "x-reply-radar/1.0",
        }

    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(30)
    try:
        req = urllib.request.Request(LLM_URL, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if LLM_STYLE == "anthropic":
            reply = data["content"][0]["text"].strip()
        else:
            reply = data["choices"][0]["message"]["content"].strip()
        return {"draft_reply": reply}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:150]}"}
    finally:
        socket.setdefaulttimeout(prev)


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>X Reply Radar</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:20px;max-width:900px;margin:0 auto}
h1{font-size:1.5rem;margin-bottom:4px}
.subtitle{color:#8b949e;font-size:.85rem;margin-bottom:12px}
.stats{display:flex;gap:8px;margin-bottom:12px;font-size:.8rem;color:#8b949e;flex-wrap:wrap}
.stats span{background:#161b22;padding:4px 10px;border-radius:6px;border:1px solid #30363d}
.stats .clickable{cursor:pointer;transition:all .15s}
.stats .clickable:hover{border-color:#58a6ff;color:#58a6ff}
#history{margin-bottom:20px}
select{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 10px;font-size:.85rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:16px;overflow:hidden}
.card-header{padding:12px 16px;border-bottom:1px solid #21262d}
.card-header a{color:#58a6ff;text-decoration:none;font-weight:600}
.card-header .name{color:#8b949e;font-weight:400}
.card-header .followers{float:right;color:#8b949e;font-size:.8rem}
.bio{color:#8b949e;font-size:.8rem;margin-top:4px}
.post-text{padding:12px 16px;font-size:.9rem;line-height:1.5;white-space:pre-wrap;word-wrap:break-word}
.metrics{padding:8px 16px;display:flex;gap:14px;font-size:.75rem;color:#8b949e;border-top:1px solid #21262d;border-bottom:1px solid #21262d}
.why{padding:8px 16px;font-size:.8rem;color:#8b949e;font-style:italic}
.draft-box{margin:12px 16px;background:#1c2128;border:1px solid #30363d;border-radius:6px;padding:12px;font-family:'SF Mono','Fira Code',monospace;font-size:.85rem;line-height:1.5;white-space:pre-wrap}
.actions{padding:0 16px 12px;display:flex;gap:10px;align-items:center}
button{background:#238636;color:#fff;border:none;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:.8rem}
button:hover{background:#2ea043}
button.copied{background:#1f6feb}
.actions a{color:#58a6ff;font-size:.8rem;text-decoration:none}
.actions a:hover{text-decoration:underline}
.notes{padding:0 16px 12px;font-size:.75rem;color:#8b949e}
.notes strong{color:#e6edf3}
.pending{color:#d29922;font-style:italic}
.empty{text-align:center;padding:60px 20px;color:#8b949e}
.empty h2{color:#e6edf3;margin-bottom:8px}
.footer{margin-top:24px;padding-top:16px;border-top:1px solid #21262d;font-size:.75rem;color:#484f58;text-align:center}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:600;margin-left:6px}
.badge-builder{background:#1f6feb33;color:#58a6ff}
.badge-selected{background:#23863633;color:#3fb950}
.tabs{display:flex;flex-wrap:nowrap;gap:0;margin-bottom:16px;border-bottom:1px solid #30363d}
.tab{padding:10px 18px;cursor:pointer;color:#8b949e;font-size:.9rem;border-bottom:2px solid transparent;transition:all .15s;user-select:none;white-space:nowrap}
.tab:hover{color:#e6edf3}
.tab.active{color:#58a6ff;border-bottom-color:#58a6ff}
.tab .count{font-size:.75rem;background:#21262d;padding:2px 6px;border-radius:4px;margin-left:4px}
.tab.active .count{background:#1f6feb33;color:#58a6ff}
.tab-content{display:none}
.tab-content.active{display:block}
.filtered-card{background:#0d1117;border:1px solid #21262d;border-radius:6px;margin-bottom:8px;overflow:hidden}
.filtered-card .post-text{font-size:.85rem}
.filtered-card .card-header{padding:8px 12px}
.filtered-card .metrics{padding:6px 12px;font-size:.7rem}
.filtered-card .card-header a{font-size:.85rem}
.filtered-card .bio{font-size:.75rem}
.filtered-actions{padding:4px 12px 10px;display:flex;gap:10px;align-items:center}
.filtered-actions a{color:#58a6ff;font-size:.75rem;text-decoration:none}
.filtered-actions a:hover{text-decoration:underline}
button.gen-btn{background:#1f6feb33;color:#58a6ff;border:1px solid #58a6ff44;padding:4px 12px;font-size:.75rem}
button.gen-btn:hover{background:#1f6feb44}
button.gen-btn:disabled{opacity:.5;cursor:wait}
.filtered-card .draft-box{margin:8px 12px;font-size:.8rem;padding:10px}
.filtered-card .actions{padding:0 12px 10px}
</style>
</head>
<body>
<h1>X Reply Radar</h1>
<div class="subtitle" id="subtitle">Loading...</div>
<div class="stats" id="stats"></div>
<div id="history"><select id="history-select" onchange="loadResult(this.value)"></select></div>
<div id="tabs" class="tabs"></div>
<div id="content"><div class="empty"><h2>Loading...</h2></div></div>
<div class="footer">cron every 4h &middot; auto-refresh 5min &middot; copy with fallback &middot; on-demand reply gen</div>
<script>
let _data=null;
let _activeTab='suggested';

async function fetchJSON(u){const r=await fetch(u);return r.json()}
function fmt(n){if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return''+n}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

async function loadResults(){
  const data=await fetchJSON('/api/results');
  const sel=document.getElementById('history-select');
  if(!data.files||data.files.length===0){
    sel.style.display='none';
    document.getElementById('subtitle').textContent='No runs yet - showing raw candidates from latest search';
    document.getElementById('stats').innerHTML='';
    loadCandidates();return;
  }
  sel.style.display='block';
  sel.innerHTML=data.files.map((f,i)=>{
    // Filename is UTC: results_YYYYMMDD_HHMMSS.json -> parse as UTC, render in local TZ
    const m=f.match(/results_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.json/);
    const l=m?new Date(Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6])).toLocaleString():f;
    return `<option value="${f}" ${i===0?'selected':''}>${l}</option>`;
  }).join('');
  loadResult(data.files[0]);
}

async function loadResult(fn){
  const data=await fetchJSON('/api/results/'+fn);
  _data=data;
  renderTabs(data);
  renderTabContent(data);
}

function renderTabs(data){
  const sub=document.getElementById('subtitle');
  const st=document.getElementById('stats');
  const ts=data.timestamp?new Date(data.timestamp).toLocaleString():'';
  sub.textContent=ts?('Last run: '+ts):'Latest search results';
  const s=data.stats||{};
  const selCount=(data.candidates||[]).length;
  const filtAll=data.filtered_all||[];
  const selIds=new Set((data.candidates||[]).map(c=>c.id));
  const filtCount=filtAll.filter(p=>!selIds.has(p.id)).length;
  st.innerHTML=`<span>Unique: ${s.total_unique||'?'}</span><span>Recent (4h): ${s.recent_4h||'?'}</span>`+
    `<span class="clickable" onclick="switchTab('filtered')">Filtered: ${filtCount||s.after_filters||'?'} \u25B8</span>`+
    `<span>Selected: ${selCount}</span>`;
  document.getElementById('tabs').innerHTML=
    `<div class="tab ${_activeTab==='suggested'?'active':''}" onclick="switchTab('suggested')">Suggested <span class="count">${selCount}</span></div>`+
    `<div class="tab ${_activeTab==='filtered'?'active':''}" onclick="switchTab('filtered')">All Filtered <span class="count">${filtCount}</span></div>`;
}

function switchTab(tab){
  _activeTab=tab;
  if(_data){renderTabs(_data);renderTabContent(_data);}
}

function renderTabContent(data){
  const c=document.getElementById('content');
  if(_activeTab==='suggested') renderSuggested(data,c);
  else renderFilteredTab(data,c);
}

function renderSuggested(data,c){
  if(!data.candidates||data.candidates.length===0){c.innerHTML='<div class="empty"><h2>No candidates</h2></div>';return}
  c.innerHTML=data.candidates.map((p,i)=>{
    const m=p.metrics||{};
    const dr=p.draft_reply
      ?`<div class="draft-box">${esc(p.draft_reply)}</div><div class="actions"><button onclick="copyR(${i},this)">Copy</button><a href="${p.url}" target="_blank">Open on X &rarr;</a></div>`
      :`<div class="draft-box pending">No draft reply yet</div><div class="actions"><a href="${p.url}" target="_blank">Open on X &rarr;</a></div>`;
    const ns=p.notes?`<div class="notes"><strong>Notes:</strong> ${esc(p.notes)}</div>`:'';
    const wy=p.why_selected?`<div class="why">Why: ${esc(p.why_selected)}</div>`:'';
    const bd=p.is_builder?' <span class="badge badge-builder">builder</span>':'';
    return `<div class="card" id="card-${i}"><div class="card-header"><span class="followers">${fmt(p.followers||0)} followers</span><a href="https://x.com/${p.username}" target="_blank">@${p.username}</a> <span class="name">(${esc(p.author_name||'')})</span>${bd}<div class="bio">${esc((p.author_bio||'').slice(0,150))}</div></div><div class="post-text">${esc(p.text||'')}</div><div class="metrics"><span>Replies: ${m.replies??p.replies??0}</span><span>Likes: ${m.likes??p.likes??0}</span><span>RTs: ${m.retweets??p.retweets??0}</span><span>Imp: ${fmt(m.impressions??p.impressions??0)}</span></div>${wy}${dr}${ns}</div>`;
  }).join('');
}

function renderFilteredTab(data,c){
  const selIds=new Set((data.candidates||[]).map(c=>c.id));
  const nonSel=(data.filtered_all||[]).filter(p=>!selIds.has(p.id));
  if(nonSel.length===0){c.innerHTML='<div class="empty"><h2>No other filtered posts</h2></div>';return}
  c.innerHTML=nonSel.map((p,i)=>{
    const m=p.metrics||{};
    const bd=p.is_builder?' <span class="badge badge-builder">builder</span>':'';
    return `<div class="filtered-card" data-pid="${p.id}"><div class="card-header"><span class="followers">${fmt(p.followers||p.author_followers||0)} followers</span><a href="https://x.com/${p.username}" target="_blank">@${p.username}</a> <span class="name">(${esc(p.author_name||'')})</span>${bd}<div class="bio">${esc((p.author_bio||'').slice(0,120))}</div></div><div class="post-text">${esc((p.text||'').slice(0,400))}</div><div class="metrics"><span>Replies: ${m.replies??p.replies??0}</span><span>Likes: ${m.likes??p.likes??0}</span><span>RTs: ${m.retweets??p.retweets??0}</span><span>Imp: ${fmt(m.impressions??p.impressions??0)}</span></div><div class="filtered-actions"><a href="${p.url}" target="_blank">Open on X &rarr;</a><button class="gen-btn" onclick="generateReply(this,${i})">Generate Reply</button></div><div class="draft-container" id="fdraft-${i}"></div></div>`;
  }).join('');
}

let _filteredPosts=[];
const _origRenderFiltered=renderFilteredTab;
renderFilteredTab=function(data,c){
  const selIds=new Set((data.candidates||[]).map(c=>c.id));
  _filteredPosts=(data.filtered_all||[]).filter(p=>!selIds.has(p.id));
  _origRenderFiltered(data,c);
};

async function generateReply(btn,i){
  const post=_filteredPosts[i];
  if(!post){return}
  btn.disabled=true;
  btn.textContent='Generating...';
  const container=document.getElementById('fdraft-'+i);
  container.innerHTML='<div class="draft-box pending">Generating reply...</div>';
  try{
    const resp=await fetch('/api/generate-reply',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        id:post.id,
        text:post.text,
        username:post.username,
        author_name:post.author_name,
        author_bio:post.author_bio
      })
    });
    const data=await resp.json();
    if(data.draft_reply){
      container.innerHTML=`<div class="draft-box">${esc(data.draft_reply)}</div><div class="actions"><button onclick="copyFilteredDraft(${i},this)">Copy</button><a href="${post.url}" target="_blank">Reply on X &rarr;</a></div>`;
    }else{
      container.innerHTML=`<div class="draft-box pending">Failed: ${esc(data.error||'unknown error')}</div>`;
    }
  }catch(e){
    container.innerHTML=`<div class="draft-box pending">Failed: ${esc(e.message)}</div>`;
  }
  btn.disabled=false;
  btn.textContent='Generate Reply';
}

function copyFilteredDraft(i,btn){
  const box=document.querySelector('#fdraft-'+i+' .draft-box');
  if(!box){return}
  const text=box.textContent;
  function ok(){btn.textContent='Copied!';btn.classList.add('copied');setTimeout(()=>{btn.textContent='Copy';btn.classList.remove('copied')},2000);}
  function fail(){btn.textContent='Failed';setTimeout(()=>{btn.textContent='Copy'},2000);}
  if(navigator.clipboard&&window.isSecureContext){
    navigator.clipboard.writeText(text).then(ok).catch(()=>fallbackCopy(text,ok,fail));
  }else{fallbackCopy(text,ok,fail)}
}

async function loadCandidates(){
  try{
    const d=await fetchJSON('/api/candidates');
    if(d.candidates&&d.candidates.length>0){
      d.candidates.forEach(c=>{if(!c.metrics)c.metrics={replies:c.replies,likes:c.likes,retweets:c.retweets,impressions:c.impressions}});
      _data=d;
      _filteredPosts=(d.filtered_all||[]);
      renderTabs(d);
      renderTabContent(d);
    }else{
      document.getElementById('content').innerHTML='<div class="empty"><h2>No results yet</h2><p>First cron run will populate this page.</p></div>';
    }
  }catch(e){
    document.getElementById('content').innerHTML='<div class="empty"><h2>No results yet</h2><p>First cron run will populate this page.</p></div>';
  }
}

function copyR(i,btn){
  const box=document.querySelector('#card-'+i+' .draft-box');
  const text=box.textContent;
  function ok(){btn.textContent='Copied!';btn.classList.add('copied');setTimeout(()=>{btn.textContent='Copy';btn.classList.remove('copied')},2000);}
  function fail(){btn.textContent='Failed';setTimeout(()=>{btn.textContent='Copy'},2000);}
  if(navigator.clipboard&&window.isSecureContext){
    navigator.clipboard.writeText(text).then(ok).catch(()=>fallbackCopy(text,ok,fail));
  }else{fallbackCopy(text,ok,fail)}
}
function fallbackCopy(text,ok,fail){
  try{
    const ta=document.createElement('textarea');
    ta.value=text;ta.style.position='fixed';ta.style.left='-9999px';
    document.body.appendChild(ta);ta.select();
    const r=document.execCommand('copy');
    document.body.removeChild(ta);
    if(r)ok();else fail();
  }catch(e){fail()}
}

loadResults();
setInterval(loadResults,300000);
</script>
</body>
</html>"""


class RadarHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/':
            self._send_html(HTML_PAGE)

        elif path == '/api/results':
            files = sorted(
                glob.glob(os.path.join(RESULTS_DIR, "results_*.json")),
                reverse=True
            )
            self._send_json({"files": [os.path.basename(f) for f in files]})

        elif path.startswith('/api/results/'):
            filename = unquote(path[len('/api/results/'):])
            if '/' in filename or '..' in filename:
                self._send_json({"error": "forbidden"}, 403)
                return
            filepath = os.path.join(RESULTS_DIR, filename)
            if not os.path.exists(filepath):
                self._send_json({"error": "not found"}, 404)
                return
            with open(filepath) as f:
                self._send_json(json.load(f))

        elif path == '/api/candidates':
            if not os.path.exists(CANDIDATES_FILE):
                self._send_json({"error": "no candidates yet", "candidates": []})
                return
            with open(CANDIDATES_FILE) as f:
                self._send_json(json.load(f))

        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/api/generate-reply':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self._send_json({"error": "empty body"}, 400)
                return
            try:
                body = json.loads(self.rfile.read(content_length))
            except (json.JSONDecodeError, ValueError):
                self._send_json({"error": "invalid JSON"}, 400)
                return

            if not body.get("text"):
                self._send_json({"error": "missing post text"}, 400)
                return

            result = generate_reply_llm(body)
            self._send_json(result)

        else:
            self._send_json({"error": "not found"}, 404)

    def _send_html(self, content):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"X Reply Radar dashboard running on {HOST}:{PORT}")
    print(f"  http://localhost:{PORT}")
    print(f"  Data dir: {DATA_DIR}")
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print(f"  WARNING: bound to {HOST} (no auth) - only do this on a trusted network")
    server = ThreadingHTTPServer((HOST, PORT), RadarHandler)
    server.serve_forever()