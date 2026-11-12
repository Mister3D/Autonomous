# LLM settings (Pi models.json)

**Status**: in place  
**Key files**: `autonomous/services/setup_config.py`, `autonomous/services/chat_attachments.py`, `frontend/src/components/LlmSettings.vue`  
**Last updated**: 2026-11-13 (four cards: default model, providers, models, other models)

## User behaviour

- Settings → **LLM**: edit OpenAI-compatible providers written to `~/.pi/agent/models.json` (Pi schema).
- **Default model** (its own card): the only Pi ref a Manager-created bot receives, and the model preselected in the Create bot dialog (see [household.md](./household.md) and [bots-create.md](./bots-create.md)). Saved via `PUT /settings` (`bots.default_model`). The picker spans the card.
- Two clear blocks:
  1. **Providers** — add / edit API endpoints (id, URL, key). Save without needing a model.
  2. **Models** — same cards as providers: collapsed on arrival, trash on the row, **Add a model** opens one empty card. Fields start with the display name, then provider (placeholder until chosen; that pick fetches `/v1/models`), then the model id menu, vision, and limits.
- A model you just add stays open. Reload collapses saved cards again. An unsaved new card is kept if another save refreshes the list.
- Provider cards start **collapsed** (name only, at least one letter) on a short row. The caret opens the URL and key below the name. The name and the trash stay on the same pixels when the card opens. A provider you just add opens so it can be filled. Reload collapses them again.
- Each provider card has a trash control on that same row, at the right. It deletes the provider when no model uses it. If a model still lists that provider, the trash stays grey. Hover uses the same immediate custom tooltip as the large avatar (no browser `title`): a model uses this provider, or delete the provider. `DELETE /setup/llm?provider=` still returns `provider_in_use` if a model remains.
- **Other models** (its own card): one read-only table from `pi --list-models`, excluding providers edited in this page. A row appears only when Pi can already use that provider (`/login` or an API key). Rows are sorted alphabetically on `provider · model id`, then show context, max output, reasoning, and image flags from pi.dev. The list has no scrollbar of its own; it scrolls with the settings pane. The header sticks to the top of that pane on an opaque band, so a row cannot show through the titles. These models are picked on the bot’s details page, not edited here.
- Links to Pi docs for `/login` and advanced cases: [models](https://pi.dev/docs/latest/models), [providers](https://pi.dev/docs/latest/providers), [models configuration](https://pi.dev/docs/latest/models-configuration) — one docs line in the Providers card.
- Settings → LLM is four full-width cards (default model, providers, models, other models). Each card body uses a flex column gap (`0.75rem`). Nested fields in open provider/model rows use the same gap (no stacked `.settings-field` / `.setup-toolbar` margins). **Add a provider** and **Add a model** are centered.
- No global “max vision images” control in the UI: set it **per model**. Code fallback is still `guard.max_images_per_prompt` default **2** when the model has no `inputLimits.images.maxPerRequest` (also updated when a provider returns “at most N”).

## Implementation

- Source of truth for config: Pi `models.json` (`name`, `input`, `inputLimits.images.maxPerRequest`, `contextWindow`, `maxTokens`).
- `PUT /setup/llm`:
  - no `models` / `model` → update provider credentials only (keep existing models, or create empty);
  - `models: [...]` → full list replace for that provider (may be `[]`);
  - `model` → upsert one model on that provider.
- Writes are **merge-safe**: unknown fields (`cost`, `reasoning`, `compat`, resize profiles…) are kept.
- Autonomous **overlay**: `max_images_per_prompt(bot=…)` reads the bot’s model ref from Pi JSON and truncates vision prompts; if the provider returns “at most N images”, the limit is written back into that model entry (`remember_model_image_limit`) and the guard fallback is updated.

## Pitfalls / non-regressions

- Do not store a second parallel LLM catalog in SQLite.
- Do not drop unknown keys when saving a model.
- Do not require a model when saving provider credentials alone.
- Built-in providers via Pi `/login` stay outside this editor (custom OpenAI-compat only).
- Set `contextWindow` on custom models to the real vLLM `--max-model-len` (Pi defaults to **128K** when omitted — wrong compaction / overflow). Compaction headroom: `~/.pi/agent/settings.json` → `compaction.reserveTokens` / `keepRecentTokens` (and optional `modelOverrides`). Our Mister3D Qwen ref uses `contextWindow: 262144` with reserve **49152** / keepRecent **28000** so auto-compact leaves room before a fat tool batch. vLLM prefix caching has **no TTL** → leave Pi `cacheWarming` **off**; session-affinity headers only matter with several replicas behind a LB (single node: irrelevant).
- Future Autonomous code must not rewrite the Pi system prefix every message (no per-turn “now” / fresh memory in system) — see [pi-agent.md](./pi-agent.md) pitfalls.

## Quick check

```bash
pytest tests/test_llm_models_limits.py tests/test_setup_models.py -q
```
