<template>
  <MenuSelect
    :model-value="model"
    :options="options"
    :placeholder="t('details.modelNone')"
    :aria-label="t('details.model')"
    allow-empty
    @update:model-value="emit('update:model', $event)"
  />
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import MenuSelect from "./MenuSelect.vue";

const props = defineProps({
  model: { type: String, default: "" },
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

async function load() {
  try {
    models.value = await api.piModels();
  } catch {
    models.value = [];
  }
}

onMounted(load);
</script>
