<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <h1 class="login-brand"><img class="login-logo" src="/logo.png" :alt="t('brand')" /></h1>
      <p class="tagline">{{ t("tagline") }}</p>
      <div class="field">
        <label for="password">{{ t("login.password") }}</label>
        <input
          id="password"
          v-model="password"
          type="password"
          autocomplete="current-password"
          autofocus
          required
        />
      </div>
      <p v-if="error" style="color: var(--danger)">{{ error }}</p>
      <div class="login-actions">
        <button class="btn primary" type="submit" :disabled="loading">
          {{ t("login.submit") }}
        </button>
        <LocalePicker />
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter, useRoute } from "vue-router";
import { api } from "../api";
import { state } from "../store";
import { connectEvents, refreshBots } from "../sync";
import LocalePicker from "../components/LocalePicker.vue";

const { t } = useI18n();
const router = useRouter();
const route = useRoute();
const password = ref("");
const error = ref("");
const loading = ref(false);

async function submit() {
  loading.value = true;
  error.value = "";
  try {
    await api.login(password.value);
    state.authenticated = true;
    connectEvents();
    await refreshBots();
    router.replace(route.query.next || "/");
  } catch {
    error.value = t("login.error");
  } finally {
    loading.value = false;
  }
}
</script>
