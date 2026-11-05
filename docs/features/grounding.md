# GUI grounding (UI-TARS + judge)

**Status**: in place (localisation only — no click)  
**Key files**: `autonomous/services/grounding{,_image,_parse}.py`, `POST /bots/:name/screen/ground`, `vm_ground` (`pi_extensions/vm.ts`), `grounding.md`  
**Last updated**: 2026-11-06 (grounder URL SSRF gate + redirect re-check)

## User behaviour

- The Pi agent calls **`vm_ground`** (instruction in English).
- In the **chat**, capture, loop notes (UI-TARS, verdict, nudge, failure) and contiguous tools form a `ToolGroup`.
- **During the run** (unsealed group): **live preview of the last tool call** (any of them: `vm_*`, `browser_*`, … — args + result).
- **As soon as a message follows** (assistant, vault, etc.): the group is **sealed** → menu **collapsed** (unless the user opened it).
- **No** special "Target" / "Pointer actions" sections: `vm_ground`, `vm_click`, `vm_drag`, `vm_scroll` are **tool lines** like the others (collapsed). Cross / notes / overlay only appear when you **expand** that line.
- Tool response: `{ ok, x, y, loops[], max_loops, … }` — **no click**.

## Guard-rails (Settings)

| Key | Default | Role |
|-----|--------|------|
| `grounding.max_loops` | `2` | Grounder+check attempts (1–8), Settings UI. The four fields save by themselves (leaving the field or a short pause). |
| `guard.review_every` | `100` | LLM review (steer) every N tools since the last user/webhook/cron message (`0` = off) |
| `guard.max_actions` | `1000` | Hard stop after N tools (same window) |

Per-bot override possible via `bot.guard.*` (otherwise global settings). No `max_runtime_sec` in the product.

## Grounder config

Grounding is **off by default**: with no URL, grounding tools return
`grounder_unconfigured`. Enable it with env vars or a local
`AUTONOMOUS_HOME/grounder.env` (KEY=VALUE, gitignored with `data/`).

Server setup (UI-TARS and LLM on vLLM, VRAM, untested single-GPU configs): see
[GPU models in the README](../../README.md#gpu-models-optional-ui-tars-grounding-and-llm).

Priority: process env → `grounder.env` → `./TOKEN` (gitignored).

| Variable | Default |
|----------|--------|
| `AUTONOMOUS_GROUNDER_URL` | empty (disabled), e.g. `http://gpu-host:8000/v1` |
| `AUTONOMOUS_GROUNDER_MODEL` | `ui-tars-1.5-7b` |
| `AUTONOMOUS_GROUNDER_TOKEN` | empty (or `TOKEN` file) |

Click verification uses the **configured LLM** (Settings → LLM, i.e. the first provider of
`~/.pi/agent/models.json`): same base URL and key as the Pi agent, with its first model that
accepts images. There is no separate verifier endpoint; `AUTONOMOUS_VERIFIER_*` variables are ignored.

## API

```
POST /bots/:name/screen/ground
{
  "instruction": "the Login button",
  "verify": true,
  "check_exists": true,
  "show_in_chat": true,
  "max_retries": null
}
```

`max_retries` null → reads `grounding.max_loops`.

## Pitfalls / non-regressions

- Saving `grounder_url` (and runtime `_chat_completions`) uses the same SSRF gate as LLM URLs; redirects are re-checked (`urlopen_safe`).
- Role separation: the grounder points, the judge validates (short hollow reticle — no full-screen cross).
- Don't redisplay capture / grounding notes as separate items: `meta.kind=grounding` and `meta.grounding` captures stay in the adjacent tool group.
- Coords = original capture after remap.
- `show_in_chat=false` for silent tests.
- Restart the Pi session after changing `vm.ts`.
- After `ok`: Pi tools `vm_click` / `vm_drag` / `vm_type` / `vm_scroll` depending on `action`.
- Pi often omits `args` on `tool_execution_end`: Autonomous **keeps** those from the start + parses the result text → `meta.pointer` / `x,y,x2,y2` for the UI.
- Web nav: see [`browser-nav.md`](./browser-nav.md) — **gesture decided before** the ground (`action_hint`); DOM via `browser_snapshot` / `browser_frames_snapshot`.
- Slide drag: stretch only if `|dx|<160` and capped at ~240–320px (not 30% of the screen). Handle and target on the **same** Y row; `chrome_h` (~87) to map iframe→screen.

## Quick check

```bash
python3 -m pytest tests/test_grounding_parse.py -q
curl -s -H "Authorization: Bearer $(cat data/token)" \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"the Applications menu button","show_in_chat":true}' \
  http://127.0.0.1:8787/api/v1/bots/4/screen/ground
# Then open the bot's chat: a single collapsible group (capture / cross / notes inside).
```
