<template>
  <MenuSelect
    :model-value="model"
    :options="options"
    :placeholder="t('details.modelNone')"
    :aria-label="t('details.model')"
    :field="field"
    @update:model-value="onPick"
  />
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import MenuSelect from "./MenuSelect.vue";

const props = defineProps({
  model: { type: String, default: "" },
  field: { type: Boolean, default: false },
});
const emit = defineEmits(["update:model"]);

const { t } = useI18n();
const models = ref([]);

const options = computed(() =>
  models.value.map((m) => ({
    value: m.ref,
    label: m.label || m.id,
    meta: m.provider || "",
  })),
);

function onPick(value) {
  const next = String(value || "").trim();
  if (!next) return;
  emit("update:model", next);
}

async function load() {
  try {
    models.value = await api.piModels();
  } catch {
    models.value = [];
  }
}

onMounted(load);
</script>
