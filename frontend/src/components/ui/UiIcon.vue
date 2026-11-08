<template>
  <svg
    class="ui-icon"
    viewBox="0 0 24 24"
    :width="size"
    :height="size"
    fill="none"
    stroke="currentColor"
    :stroke-width="stroke"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- Navigation / chrome -->
    <template v-if="name === 'search'">
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16.5 20 20.5" />
    </template>
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>
    <template v-else-if="name === 'chevron-left'">
      <path d="M15 6 9 12l6 6" />
    </template>
    <template v-else-if="name === 'chevron-right'">
      <path d="M9 6l6 6-6 6" />
    </template>
    <template v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M5.8 5.8l1.6 1.6M16.6 16.6l1.6 1.6M5.8 18.2l1.6-1.6M16.6 7.4l1.6-1.6" />
    </template>
    <template v-else-if="name === 'save'">
      <path d="M5.5 4.5h10.2L18.5 7.3V19a.8.8 0 0 1-.8.8H6.3a.8.8 0 0 1-.8-.8V5.3a.8.8 0 0 1 .8-.8Z" />
      <path d="M8 4.5v4.2h7.2V4.5M8 19v-5.2h8" />
    </template>
    <template v-else-if="name === 'play'">
      <path d="M9 7.5v9l8-4.5-8-4.5Z" fill="currentColor" stroke="none" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M19 12a7 7 0 1 1-1.8-4.7" />
      <path d="M19 5v4.2h-4.2" />
    </template>
    <template v-else-if="name === 'globe'">
      <circle cx="12" cy="12" r="7.5" />
      <path d="M4.5 12h15M12 4.5c2.2 2.4 2.2 12.6 0 15M12 4.5c-2.2 2.4-2.2 12.6 0 15" />
    </template>
    <template v-else-if="name === 'link'">
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 17.2 8.8 19.4a3.2 3.2 0 0 1-4.5-4.5L6.5 13" />
      <path d="M13 6.8l2.2-2.2a3.2 3.2 0 0 1 4.5 4.5L17.5 11" />
    </template>
    <template v-else-if="name === 'memory'">
      <path d="M6.5 7h11M6.5 12h11M6.5 17h7" />
    </template>
    <template v-else-if="name === 'users'">
      <circle cx="9" cy="9" r="2.6" />
      <circle cx="16" cy="10" r="2.2" />
      <path d="M4.2 17.5c.6-2.2 2.3-3.4 4.8-3.4s4.2 1.2 4.8 3.4" />
      <path d="M13.2 14.4c1.1-.6 2.4-.7 3.8-.2 1.3.5 2.1 1.5 2.5 3.3" />
    </template>
    <template v-else-if="name === 'moon'">
      <path d="M18.5 13.2A6.8 6.8 0 0 1 10.8 5.5 6.8 6.8 0 1 0 18.5 13.2Z" />
    </template>
    <template v-else-if="name === 'cpu'">
      <rect x="7" y="7" width="10" height="10" rx="1.6" />
      <path d="M10 3.5v3.5M14 3.5v3.5M10 17v3.5M14 17v3.5M3.5 10H7M3.5 14H7M17 10h3.5M17 14h3.5" />
    </template>
    <template v-else-if="name === 'crosshair'">
      <circle cx="12" cy="12" r="6" />
      <path d="M12 3v5M12 16v5M3 12h5M16 12h5" />
    </template>
    <template v-else-if="name === 'vault'">
      <rect x="6" y="10.2" width="12" height="8.3" rx="1.6" />
      <path d="M9 10.2V8.2a3 3 0 0 1 6 0v2" />
    </template>
    <template v-else-if="name === 'monitor'">
      <rect x="4" y="5" width="16" height="11" rx="1.8" />
      <path d="M9 19.5h6M12 16v3.5" />
    </template>
    <template v-else-if="name === 'spark'">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    </template>
    <template v-else-if="name === 'terminal'">
      <rect x="4.5" y="5" width="15" height="14" rx="2" />
      <path d="M8 10.2 10.2 12 8 13.8M12.2 14.2h3.6" />
    </template>
    <template v-else-if="name === 'settings'">
      <!-- Roue crantée -->
      <circle cx="12" cy="12" r="3" />
      <path
        d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"
      />
    </template>
    <template v-else-if="name === 'trash'">
      <path d="M5 7.5h14" />
      <path d="M9.5 7.5V5.8a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v1.7" />
      <path d="M7.2 7.5 8 18.2a1.2 1.2 0 0 0 1.2 1.1h5.6a1.2 1.2 0 0 0 1.2-1.1L16.8 7.5" />
      <path d="M10.2 11v5.2M13.8 11v5.2" />
    </template>
    <template v-else-if="name === 'logout'">
      <path d="M10 5.5H7.2A2.2 2.2 0 0 0 5 7.7v8.6A2.2 2.2 0 0 0 7.2 18.5H10" />
      <path d="M14 8.2 17.8 12 14 15.8M8.5 12H17.5" />
    </template>
    <template v-else-if="name === 'lang'">
      <circle cx="12" cy="12" r="8" />
      <path d="M4 12h16M12 4c2.5 2.8 2.5 13.2 0 16M12 4c-2.5 2.8-2.5 13.2 0 16" />
    </template>
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="7.5" />
      <path d="M12 8v4.2l2.8 1.6" />
    </template>
    <template v-else-if="name === 'key'">
      <circle cx="8.5" cy="12" r="3.2" />
      <path d="M11.2 12H19v2.2h-2.2V16H14.6v-2.2H11.8" />
    </template>
    <template v-else-if="name === 'update'">
      <path d="M12 5v3.2M12 15.8V19" />
      <path d="M7.2 7.2a6.8 6.8 0 1 0 9.6 0" />
    </template>
    <template v-else-if="name === 'puzzle'">
      <!-- CC0 — SVG Repo « puzzle-piece-02 » https://www.svgrepo.com/svg/471806/puzzle-piece-02 -->
      <path
        d="M12 2 15.6 5.6C18-.7 24.7 6 18.4 8.4L22 12l-3.6 3.6C16 9.3 9.3 16 15.6 18.4L12 22l-3.6-3.6C6 24.7-.7 18 5.6 15.6L2 12l3.6-3.6C8 14.7 14.7 8 8.4 5.6L12 2Z"
      />
    </template>
    <template v-else-if="name === 'database'">
      <ellipse cx="12" cy="6.5" rx="6.5" ry="2.6" />
      <path d="M5.5 6.5v11c0 1.4 2.9 2.6 6.5 2.6s6.5-1.2 6.5-2.6v-11" />
      <path d="M5.5 12c0 1.4 2.9 2.6 6.5 2.6s6.5-1.2 6.5-2.6" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="7" />
    </template>
  </svg>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 18 },
  stroke: { type: [Number, String], default: 1.7 },
});
</script>
