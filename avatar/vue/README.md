# @autonomous/companion-avatar

Vue 3 component + SVG engine for companion badges.

## Usage

```vue
<script setup>
import { CompanionAvatar } from "@autonomous/companion-avatar";
</script>

<template>
  <div style="width:40px;height:40px;border-radius:50%;overflow:hidden">
    <CompanionAvatar character="chat" :color="3" state="work" />
  </div>
</template>
```

### Props

| Prop | Type | Default | Description |
|------|------|--------|-------------|
| `character` | string | — | catalogue id (`renard`, `chat`, …) |
| `color` | number | `0` | swatch index 0–17 (`0` = original drawing) |
| `state` | string | `idle` | `work` \| `notify` \| `await` \| `idle` |
| `size` | string | `sm` | CSS hint (`sm` / `lg`) |
| `trackZone` | HTMLElement | auto | hover zone for eye tracking in idle |

### States

- **work** — working (animations)
- **notify** — unread messages / attention
- **await** — waiting for a user action (jump)
- **idle** — still; on hover → eyes follow the mouse

### Picker

```vue
<CompanionAvatarPicker
  v-model:character="id"
  v-model:color="colorIndex"
/>
```

### Exports

`CompanionAvatar`, `CompanionAvatarPicker`, `CHARACTER_IDS`, `CATALOG`, `getCharacter`, `SWATCHES`, `swatchCss`, `Avatar` (engine).
