# avatar — animated companions

Each character lives in `characters/<id>/`:

| File | Role |
|---------|------|
| `<id>.svg` | Web SVG (`data-part` layers, ready to animate) |
| `<id>.vectorcraft` | Vectorcraft source (ready characters) |
| `meta.json` | Title, `ready`, colouring / rig |

**Ready** characters (animations + tint): the 12 listed in `vue/catalog.js`.  
Not-yet-ready Vectorcraft sources live in `pending/` (not duplicated under `characters/`).

## Reusable Vue package

`vue/` → `@autonomous/companion-avatar`

```vue
<CompanionAvatar character="renard" :color="0" state="idle" />
```

States: `work` | `notify` | `await` | `idle`  
On `idle`, hovering makes the eyes follow (tracking mode).

Regenerate the Vue catalog from ready characters:

```bash
python3 avatar/tools/sync_characters.py
```
