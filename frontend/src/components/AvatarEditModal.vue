<template>
  <UiModal
    panel-class="avatar-edit-modal"
    :aria-label="t('avatar.editTitle')"
    @close="close"
  >
    <h2>{{ t("avatar.editTitle") }}</h2>
    <CompanionAvatarPicker
      v-model:character="character"
      v-model:color="color"
      :character-label="t('avatar.character')"
      :color-label="t('avatar.color')"
    />
    <p v-if="error" class="avatar-edit-error">{{ error }}</p>
    <div class="avatar-edit-actions">
      <UiButton variant="ghost" type="button" @click="close">
        {{ t("avatar.cancel") }}
      </UiButton>
      <UiButton variant="primary" type="button" :disabled="busy" @click="save">
        {{ busy ? t("avatar.saving") : t("avatar.save") }}
      </UiButton>
    </div>
  </UiModal>
</template>

<script setup>
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { CompanionAvatarPicker, CHARACTER_IDS } from "@companion-avatar";
import { api } from "../api";
import UiButton from "./ui/UiButton.vue";
import UiModal from "./ui/UiModal.vue";

const props = defineProps({
  bot: { type: Object, required: true },
});

const emit = defineEmits(["close"]);
const { t } = useI18n();

function initialCharacter() {
  const a = (props.bot.avatar || "").trim();
  if (a && CHARACTER_IDS.includes(a)) return a;
  return CHARACTER_IDS[0] || "renard";
}

const character = ref(initialCharacter());
const color = ref(Math.max(0, Math.min(17, Number(props.bot.avatar_color) || 0)));
const busy = ref(false);
const error = ref("");

function close() {
  emit("close");
}

async function save() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.patchBot(props.bot.name, {
      avatar: character.value,
      avatar_color: color.value,
    });
    close();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
