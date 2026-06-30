# Proven Search Query Sets

Tested query sets for different target audiences. Each set was validated against the X/Twitter API v2 recent search endpoint using `xurl`.

## AI Builders

Tested 2026-06-28. 15 queries yielded 305 unique posts, 123 in the last 4h, 41 after filters, 6 strong candidates drafted.

```
"just shipped" AI agent lang:en
"just shipped" LLM lang:en
"just shipped" robotics lang:en
"working on" AI agent lang:en
"working on" LLM inference lang:en
"built a" AI agent lang:en
"built a" robotics lang:en
#buildinpublic AI lang:en
#buildinpublic LLM lang:en
"just launched" AI agent lang:en
"open source" AI agent lang:en
"anyone using" local model lang:en
"struggling with" RAG lang:en
"working on" edge compute lang:en
"built a" autonomous drone lang:en
```

### Domain terms
AI agent, LLM, inference, robotics, local model, fine-tune, RAG, embedding, autonomous, Jetson, edge compute

### What worked
- 15 queries is a good number. More than 15 risks rate limits; fewer misses builders.
- The `lang:en` suffix is critical — without it, non-English posts waste filter slots.
- `#buildinpublic` queries surface the most genuine builders (people actively shipping, not just talking).

### Adjustments to consider
- Add `"just deployed" <term>` and `"wrote a" <term>` patterns for broader coverage.
- Consider `"show HN" <term>` — HN cross-posters tend to be serious builders.
- If rate limits hit, reduce to 10 queries and increase max_results to 40.

## Drone / Autonomous Vehicle Builders

Tested 2026-06-28. 15 drone queries combined with 15 AI queries yielded 501 unique posts, 114 in the last 4h, 32 after filters, 3 drone-specific posts found.

```
"built a" autonomous drone lang:en
"building a" drone lang:en
"autonomous drone" "open source" lang:en
PX4 OR ArduPilot lang:en
"drone" "computer vision" lang:en
"drone" "python" lang:en
"quadcopter" "built" lang:en
"drone" "raspberry pi" lang:en
"drone" "jetson" lang:en
"drone" "opencv" lang:en
"FPV" "programming" lang:en
"UAV" "autonomous" lang:en
"drone" "object detection" lang:en
"drone" "path planning" lang:en
"drone" "ROS" lang:en
```

### Domain terms
drone, quadcopter, FPV, UAV, PX4, ArduPilot, autonomous, Jetson, Raspberry Pi, OpenCV, object detection, path planning, ROS, computer vision, edge compute

### Builder signals to add
Extend the `builder_signals` list with: `drone, quadcopter, fpv, uav, px4, ardupilot`

### What worked
- PX4/ArduPilot queries surface the most technical drone builders (flight controller devs, not just pilots)
- "drone" + hardware queries (Jetson, Raspberry Pi) find people doing edge compute on drones
- Drone content has lower volume than AI builder content in a 4h window. Consider widening to 8h for drone-only tracks.

## Multi-track goals

If your goal spans multiple audience tracks (e.g. AI builders + drone builders):
1. For each track, derive its own set of queries and domain terms
2. Combine all queries into one search run — the dedup and filter pipeline handles mixed results automatically
3. When selecting top candidates, aim for a mix across tracks rather than all from one
4. Add track-specific builder signals so authors from each track get properly tagged

Combined AI + drone (30 queries) yielded 501 unique posts, 114 recent, 32 after filters — dedup handles overlap naturally (a post about "autonomous drone + AI agent" appears once).