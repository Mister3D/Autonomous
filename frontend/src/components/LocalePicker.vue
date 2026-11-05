<template>
  <div class="locale-picker" :class="{ open }" ref="root">
    <button
      class="locale-pill"
      type="button"
      :aria-label="t('lang.choose')"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="open = !open"
    >
      <LocaleFlag :code="current" />
      <span class="locale-label">{{ labelOf(current) }}</span>
      <svg class="locale-caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        <path d="M2.5 4.2 6 7.8 9.5 4.2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <ul v-if="open" class="locale-menu" role="listbox" :aria-activedescendant="`locale-${current}`">
      <li v-for="code in codes" :key="code">
        <button
          :id="`locale-${code}`"
          type="button"
          role="option"
          :aria-selected="code === current"
          :class="{ active: code === current }"
          @click="choose(code)"
        >
          <LocaleFlag :code="code" />
          <span>{{ labelOf(code) }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { setLocale } from "../i18n";
import LocaleFlag from "./LocaleFlag.vue";

const { t, locale } = useI18n();
const open = ref(false);
const root = ref(null);
const codes = ["fr", "en"];

const current = computed(() => (locale.value === "fr" ? "fr" : "en"));

function labelOf(code) {
  return code === "fr" ? t("lang.fr") : t("lang.en");
}

function choose(code) {
  setLocale(code);
  open.value = false;
}

function onDoc(ev) {
  if (!root.value?.contains(ev.target)) open.value = false;
}

function onKey(ev) {
  if (ev.key === "Escape") open.value = false;
}

onMounted(() => {
  document.addEventListener("pointerdown", onDoc);
  document.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  document.removeEventListener("pointerdown", onDoc);
  document.removeEventListener("keydown", onKey);
});
</script>
