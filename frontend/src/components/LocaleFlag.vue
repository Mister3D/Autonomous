<template>
  <span class="locale-flag" :class="`is-${size}`" aria-hidden="true">
    <svg v-if="code === 'fr'" viewBox="0 0 24 24">
      <defs>
        <clipPath :id="clipId">
          <circle cx="12" cy="12" r="12" />
        </clipPath>
      </defs>
      <g :clip-path="`url(#${clipId})`">
        <rect width="8" height="24" fill="#0055a4" />
        <rect x="8" width="8" height="24" fill="#fff" />
        <rect x="16" width="8" height="24" fill="#ef4135" />
      </g>
      <circle cx="12" cy="12" r="11.4" fill="none" stroke="rgba(0,0,0,0.08)" stroke-width="1.2" />
    </svg>
    <svg v-else viewBox="0 0 24 24">
      <defs>
        <clipPath :id="clipId">
          <circle cx="12" cy="12" r="12" />
        </clipPath>
      </defs>
      <g :clip-path="`url(#${clipId})`">
        <rect width="24" height="24" fill="#012169" />
        <path d="M0 0 24 24M24 0 0 24" stroke="#fff" stroke-width="5" />
        <path d="M0 0 24 24M24 0 0 24" stroke="#C8102E" stroke-width="2.2" />
        <path d="M12 0v24M0 12h24" stroke="#fff" stroke-width="7" />
        <path d="M12 0v24M0 12h24" stroke="#C8102E" stroke-width="3.4" />
      </g>
      <circle cx="12" cy="12" r="11.4" fill="none" stroke="rgba(0,0,0,0.08)" stroke-width="1.2" />
    </svg>
  </span>
</template>

<script setup>
import { useId } from "vue";

defineProps({
  code: { type: String, required: true },
  size: { type: String, default: "md" },
});

const clipId = `flag-clip-${useId().replace(/:/g, "")}`;
</script>

<style scoped>
.locale-flag {
  display: inline-grid;
  place-items: center;
  border-radius: 50%;
  overflow: hidden;
  flex: none;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.06);
}

.locale-flag.is-sm {
  width: 18px;
  height: 18px;
}

.locale-flag.is-md {
  width: 22px;
  height: 22px;
}

.locale-flag svg {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
