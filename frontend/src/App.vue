<template>
  <router-view />
  <div class="toast-stack" aria-live="polite">
    <button
      v-for="n in state.notifications"
      :key="n.id"
      type="button"
      class="toast"
      :title="t('notify.dismissHint')"
      @click="dismissNotification(n.id)"
    >
      {{ n.text }}
    </button>
  </div>
</template>

<script setup>
import { useI18n } from "vue-i18n";
import { state, dismissNotification } from "./store";

const { t } = useI18n();
</script>
