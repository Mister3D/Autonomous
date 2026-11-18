<template>
  <div class="modal-backdrop" @click.self="state.createOpen = false">
    <form class="modal create-bot-modal" @submit.prevent="submit">
      <h2>{{ t("create.title") }}</h2>
      <div class="create-bot-grid">
        <div class="create-bot-fields">
          <div class="field">
            <label>{{ t("create.name") }}</label>
            <input
              v-model="name"
              autocomplete="off"
              required
              maxlength="64"
              :placeholder="t('create.namePlaceholder')"
            />
            <p class="field-hint">
              {{ t("create.nameHint") }}
              <span v-if="slugPreview" class="field-hint-slug">{{
                t("create.slugPreview", { slug: slugPreview })
              }}</span>
            </p>
          </div>
          <div class="field">
            <label>{{ t("create.model") }}</label>
            <ModelPicker field :model="model" @update:model="(v) => (model = v)" />
          </div>
          <div class="create-bot-options">
            <label class="create-check">
              <input v-model="internet" type="checkbox" />
              <span>{{ t("create.internet") }}</span>
            </label>
            <div class="create-check-group">
              <label class="create-check">
                <input v-model="memoryAccess" type="checkbox" />
                <span>{{ t("create.memoryAccess") }}</span>
              </label>
              <p class="field-hint">{{ t("create.memoryAccessHint") }}</p>
            </div>
            <div class="create-check-group">
              <label class="create-check" :class="{ muted: managerTaken }">
                <input v-model="isManager" type="checkbox" :disabled="managerTaken" />
                <span>{{ t("create.isManager") }}</span>
              </label>
              <p class="field-hint">
                <template v-if="managerTaken">
                  {{ t("create.isManagerTaken", { name: managerTaken.label || managerTaken.name }) }}
                </template>
                <template v-else>{{ t("create.isManagerHint") }}</template>
              </p>
            </div>
          </div>
        </div>
        <div class="create-avatar-block">
          <CompanionAvatarPicker
            v-model:character="avatar"
            v-model:color="avatarColor"
            :character-label="t('avatar.character')"
            :color-label="t('avatar.color')"
          />
        </div>
      </div>
      <p v-if="!ready" class="create-bot-error">
        {{ t("setup.createBlocked") }}
        <router-link to="/" @click="state.createOpen = false">{{ t("setup.open") }}</router-link>
      </p>
      <p v-if="error" class="create-bot-error">{{ error }}</p>
      <div class="create-bot-actions">
        <button class="btn ghost" type="button" @click="state.createOpen = false">
          {{ t("create.cancel") }}
        </button>
        <button
          class="btn primary"
          type="submit"
          :disabled="busy || !name.trim() || !model.trim() || !ready"
        >
          {{ t("create.submit") }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { CompanionAvatarPicker, CHARACTER_IDS } from "@companion-avatar";
import { api } from "../api";
import { state, setupReady } from "../store";
import ModelPicker from "./ModelPicker.vue";

const { t } = useI18n();
const router = useRouter();
const name = ref("");
const model = ref("");
const internet = ref(true);
const memoryAccess = ref(true);
const isManager = ref(false);
const busy = ref(false);
const error = ref("");
const ready = computed(() => setupReady());

/** At most one Manager in the household. */
const managerTaken = computed(() => state.bots.find((b) => b.is_manager) || null);

function defaultAvatar() {
  const used = new Set(state.bots.map((b) => b.avatar).filter(Boolean));
  for (const id of CHARACTER_IDS) {
    if (!used.has(id)) return id;
  }
  return CHARACTER_IDS[0] || "renard";
}

const avatar = ref(defaultAvatar());
const avatarColor = ref(0);

onMounted(async () => {
  try {
    const settings = await api.settings();
    const picked = String(settings?.["bots.default_model"] || "").trim();
    if (picked) model.value = picked;
  } catch {
    /* leave the picker empty when settings cannot be read */
  }
});

/** Aperçu du slug technique (l’API le finalise / déduplique). */
function slugifyBotName(raw) {
  return String(raw || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^[-_]+/, "")
    .replace(/-+/g, "-")
    .slice(0, 32)
    .replace(/[-_]+$/, "");
}

const slugPreview = computed(() => slugifyBotName(name.value));

async function submit() {
  busy.value = true;
  error.value = "";
  const display = name.value.trim();
  if (!display) {
    error.value = t("create.nameInvalid");
    busy.value = false;
    return;
  }
  if (!slugifyBotName(display)) {
    error.value = t("create.nameInvalid");
    busy.value = false;
    return;
  }
  if (!model.value.trim()) {
    error.value = t("create.modelRequired");
    busy.value = false;
    return;
  }
  try {
    const bot = await api.createBot({
      name: display,
      internet: internet.value,
      memory_access: memoryAccess.value,
      is_manager: isManager.value,
      model: model.value.trim(),
      avatar: avatar.value,
      avatar_color: avatarColor.value,
    });
    state.currentBot = bot.name;
    state.tab = "discussion";
    state.createOpen = false;
    router.replace(`/b/${encodeURIComponent(bot.name)}/discussion`);
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
