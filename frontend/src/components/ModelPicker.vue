<template>
  <div class="model-picker" :class="{ open }" ref="root">
    <button
      class="model-trigger"
      type="button"
      :aria-label="t('details.model')"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="open = !open"
    >
      <span class="model-trigger-copy">
        <span class="model-trigger-label">{{ currentLabel }}</span>
        <span v-if="currentProvider" class="model-trigger-meta">{{ currentProvider }}</span>
      </span>
      <svg class="model-caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        <path d="M2.5 4.2 6 7.8 9.5 4.2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <ul v-if="open" class="model-menu" role="listbox">
      <li>
        <button
          type="button"
          role="option"
          :aria-selected="!model"
          :class="{ active: !model }"
          @click="choose('')"
        >
          <span class="model-option-label">{{ t("details.modelNone") }}</span>
        </button>
      </li>
      <li v-for="m in models" :key="m.ref">
        <button
          type="button"
          role="option"
          :aria-selected="m.ref === model"
          :class="{ active: m.ref === model }"
          :title="m.ref"
          @click="choose(m.ref)"
        >
          <span class="model-option-copy">
            <span class="model-option-label">{{ m.label || m.id }}</span>
            <span class="model-option-meta">{{ m.provider }}</span>
          </span>
          <svg
            v-if="m.ref === model"
            class="model-check"
            viewBox="0 0 16 16"
            width="14"
            height="14"
            aria-hidden="true"
          >
            <path
              d="M3.2 8.2 6.4 11.4 12.8 4.6"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";

const props = defineProps({
  model: { type: String, default: "" },
});
const emit = defineEmits(["update:model"]);

const { t } = useI18n();
const open = ref(false);
const root = ref(null);
const models = ref([]);

const current = computed(() => models.value.find((m) => m.ref === props.model) || null);
const currentLabel = computed(() => current.value?.label || current.value?.id || t("details.modelNone"));
const currentProvider = computed(() => current.value?.provider || "");

watch(
  () => props.model,
  () => {
    /* keep picker in sync when bot.model changes externally */
  }
);

async function load() {
  try {
    models.value = await api.piModels();
  } catch {
    models.value = [];
  }
}

function choose(ref) {
  emit("update:model", ref);
  open.value = false;
}

function onDoc(ev) {
  if (!root.value?.contains(ev.target)) open.value = false;
}

function onKey(ev) {
  if (ev.key === "Escape") open.value = false;
}

onMounted(() => {
  load();
  document.addEventListener("pointerdown", onDoc);
  document.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  document.removeEventListener("pointerdown", onDoc);
  document.removeEventListener("keydown", onKey);
});
</script>
