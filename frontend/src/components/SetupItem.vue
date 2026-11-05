<template>
  <li class="setup-item" :class="`is-${check.status}`">
    <span class="setup-dot" :title="t(`setup.status.${check.status}`)" aria-hidden="true">
      {{ icon }}
    </span>
    <div class="setup-body">
      <p class="setup-name">
        <strong>{{ t(check.label) }}</strong>
        <small class="setup-state">{{ t(`setup.status.${check.status}`) }}</small>
      </p>
      <p class="hint">{{ t(`${check.label}.help`) }}</p>
      <p v-if="check.details" class="setup-details"><code>{{ check.details }}</code></p>
      <p v-if="check.action?.type === 'command' && check.action.command" class="setup-details">
        {{ t("setup.runCommand") }} <code class="setup-cmd">{{ check.action.command }}</code>
      </p>
      <pre v-if="log && log.log?.length" ref="pre" class="setup-log">{{ log.log.join("\n") }}</pre>
      <p v-if="log?.state === 'failed'" class="vault-error">{{ log.error || t("setup.jobFailed") }}</p>
    </div>
    <div class="setup-actions">
      <router-link
        v-if="check.action?.type === 'link' || check.action?.to"
        class="btn"
        :to="check.action.to"
      >{{ t("setup.configure") }}</router-link>
      <button
        v-if="check.action?.type === 'job'"
        class="btn"
        :class="{ primary: check.status !== 'ok' }"
        type="button"
        :disabled="running"
        @click="$emit('job', check.action.job)"
      >
        {{ running ? t("setup.running") : check.action.rebuild || check.status === "ok" ? t("setup.rebuild") : t(`setup.job.${check.action.job}`) }}
      </button>
    </div>
  </li>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps({
  check: { type: Object, required: true },
  log: { type: Object, default: null },
});
defineEmits(["job"]);
const { t } = useI18n();
const pre = ref(null);

const running = computed(
  () => props.check.status === "running" || props.log?.state === "running" || props.log?.state === "pending",
);
const icon = computed(() => ({ ok: "✓", missing: "•", error: "!", optional: "○", running: "…" })[props.check.status] || "•");

watch(
  () => props.log?.log?.length,
  async () => {
    await nextTick();
    if (pre.value) pre.value.scrollTop = pre.value.scrollHeight;
  },
);
</script>
