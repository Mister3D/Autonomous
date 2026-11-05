# LLM settings (Pi models.json)

**Status**: in place  
**Key files**: `autonomous/services/setup_config.py`, `autonomous/services/chat_attachments.py`, `frontend/src/components/LlmSettings.vue`  
**Last updated**: 2026-11-06 (per-model limits in Pi JSON + Autonomous overlay)

## User behaviour

- Settings → **LLM**: edit OpenAI-compatible providers written to `~/.pi/agent/models.json` (Pi schema).
- Per model: API id, display **name**, vision flag, **max images / request**, **context window**, **max output tokens**.
- **Save per model**: button disabled while unchanged; enabled on edit; disabled again after a successful save. Provider URL/key has its own save.
- Fetch model ids from the endpoint (`GET /v1/models`), then refine limits in the list.
- Links to Pi docs for `/login` and advanced cases: [models](https://pi.dev/docs/latest/models), [models configuration](https://pi.dev/docs/latest/models-configuration).
- No global “max vision images” control in the UI: set it **per model**. Code fallback is still `guard.max_images_per_prompt` default **2** when the model has no `inputLimits.images.maxPerRequest` (also updated when a provider returns “at most N”).

## Implementation

- Source of truth for config: Pi `models.json` (`name`, `input`, `inputLimits.images.maxPerRequest`, `contextWindow`, `maxTokens`).
- Writes are **merge-safe**: unknown fields (`cost`, `reasoning`, `compat`, resize profiles…) are kept.
- Autonomous **overlay**: `max_images_per_prompt(bot=…)` reads the bot’s model ref from Pi JSON and truncates vision prompts; if the provider returns “at most N images”, the limit is written back into that model entry (`remember_model_image_limit`) and the guard fallback is updated.
- Planned upstream: PR to pi.dev so these fields are never wiped by auto catalog edits.

## Pitfalls / non-regressions

- Do not store a second parallel LLM catalog in SQLite.
- Do not drop unknown keys when saving a model.
- Built-in providers via Pi `/login` stay outside this editor (custom OpenAI-compat only).

## Quick check

```bash
pytest tests/test_llm_models_limits.py tests/test_setup_models.py -q
```
