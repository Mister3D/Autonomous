<template>
  <div class="login-page">
    <form v-if="!mustChange" class="login-card" @submit.prevent="submitLogin">
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

    <form v-else class="login-card" @submit.prevent="submitChange">
      <h1 class="login-brand"><img class="login-logo" src="/logo.png" :alt="t('brand')" /></h1>
      <p class="tagline">{{ t("login.changeTitle") }}</p>
      <p class="login-hint">{{ t("login.changeHint") }}</p>
      <div class="field">
        <label for="current">{{ t("login.currentPassword") }}</label>
        <input
          id="current"
          v-model="currentPassword"
          type="password"
          autocomplete="current-password"
          autofocus
          required
        />
      </div>
      <div class="field">
        <label for="new">{{ t("login.newPassword") }}</label>
        <input
          id="new"
          v-model="newPassword"
          type="password"
          autocomplete="new-password"
          minlength="8"
          required
        />
      </div>
      <div class="field">
        <label for="confirm">{{ t("login.confirmPassword") }}</label>
        <input
          id="confirm"
          v-model="confirmPassword"
          type="password"
          autocomplete="new-password"
          minlength="8"
          required
        />
      </div>
      <p v-if="error" style="color: var(--danger)">{{ error }}</p>
      <div class="login-actions">
        <button class="btn primary" type="submit" :disabled="loading">
          {{ t("login.changeSubmit") }}
        </button>
        <LocalePicker />
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";
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
const currentPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const error = ref("");
const loading = ref(false);
const mustChange = ref(!!state.mustChangePassword);

watch(
  () => state.mustChangePassword,
  (v) => {
    mustChange.value = !!v;
  },
);

async function enterApp() {
  state.authenticated = true;
  state.mustChangePassword = false;
  mustChange.value = false;
  connectEvents();
  await refreshBots();
  router.replace(route.query.next || "/");
}

async function submitLogin() {
  loading.value = true;
  error.value = "";
  try {
    const res = await api.login(password.value);
    state.authenticated = true;
    if (res?.must_change_password) {
      state.mustChangePassword = true;
      mustChange.value = true;
      currentPassword.value = password.value;
      password.value = "";
      return;
    }
    await enterApp();
  } catch {
    error.value = t("login.error");
  } finally {
    loading.value = false;
  }
}

async function submitChange() {
  error.value = "";
  if (newPassword.value !== confirmPassword.value) {
    error.value = t("login.changeMismatch");
    return;
  }
  if (newPassword.value.length < 8) {
    error.value = t("login.changeTooShort");
    return;
  }
  loading.value = true;
  try {
    await api.changePassword(currentPassword.value, newPassword.value);
    await enterApp();
  } catch {
    error.value = t("login.changeError");
  } finally {
    loading.value = false;
  }
}
</script>
