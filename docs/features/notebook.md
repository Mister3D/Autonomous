# Bot notebook

**Status**: in place  
**Key files**: `autonomous/services/notebook.py`, `autonomous/api/bots.py`, `autonomous/pi_extensions/notebook.ts`, `autonomous/migrations/026_bot_notebook.sql`, `frontend/src/components/DetailsPane.vue`, `frontend/src/components/ChatPane.vue`  
**Last updated**: 2026-11-20 (survives chunked compaction; not a substitute for it)

## User behaviour

- Each bot has a private notebook. Other bots do not see it. It is not the shared household memory.
- Three kinds:
  - **Orders** — a lasting rule the human stated (« always verify the proxy is enabled »). One short sentence. The bot saves it immediately, no Confirm card.
  - **Open lines** — work left unfinished (« Server: the nginx update is still to do »). The bot writes the line before it leaves the subject, and removes it when the work is done.
  - **Notes** — a decision or a setup to keep (title + body). The title is listed every turn. The body is read with `notebook_get` when the subject comes back.
- A small centred **notebook card** appears in the thread (same width band as guard / tools): label « Added to notebook · Order / Still to do / Note » or « Removed from notebook », plus the entry text and time. Soft paper/ink styling, book icon. The tool call itself stays hidden.
- Details, just above Manager, has a one-line row **Bot notebook**. An eye in a round orb on the right (`UiOrb`, same control as MCP add) opens a dialog with the orders, open lines, and notes. An empty notebook still shows the short hint under the title. The bot writes and closes entries. The panel has no add or delete control.
- Chat clear does not wipe the notebook. Deleting the bot does.

## Implementation

- Table `bot_notebook` (`bot` = UUID). Caps: 12 orders, 10 open lines, 30 notes. Order/open body max 240 characters. Note body max 4000. Title max 80. The same title in the same kind updates that row.
- Vault secrets are refused (`notebook_secret`).
- `PiAgent.start_run` appends `attach_prompt` to the text sent to Pi. The chat bubble is unchanged. An empty notebook adds nothing. The block is not part of `--append-system-prompt` (that prefix stays frozen for the Pi process).
- Tools: `notebook_list`, `notebook_get`, `notebook_remember`, `notebook_close`. Hidden in the thread and in the PDF export. The system hint that names them is loaded when the Pi process starts.
- API: `GET/POST /bots/:name/notebook`, `GET/DELETE /bots/:name/notebook/:id`.
- A `system` message `meta.kind=notebook` is the thread line. The UI translates it from `meta.tier` / `meta.action`.

## Pitfalls

- An already-open Pi session does not see `notebook.ts` or the new hint until that process restarts. The trailer appears on the next `prompt()` as soon as the server process is running this code.
- The notebook is durable across Pi compaction, but it does **not** replace compaction. Huge sessions still need a successful summary (chunked with overlap — see [pi-agent.md](./pi-agent.md)); the notebook only keeps standing orders / open lines / note titles so the bot does not lose intent when history is compressed.
- Do not put the notebook into the system prompt on each message. That rewrites the prefix and busts the KV cache.
- Do not store per-bot rules in shared `memory_propose`. Household facts (name, tastes, rules for every bot) stay there.
- Reuse the same `title` to update a rule. A new title is a new row, until the cap.
- An unchanged save does not add another thread line.

## Quick check

```bash
python3 -m pytest tests/test_notebook.py -q
```
