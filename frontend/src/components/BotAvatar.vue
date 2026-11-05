<template>
  <!--
    Pastille bot : CompanionAvatar (avatar/vue).
    sm = liste (40px), lg = fiche (96px) — dimensions inchangées.
  -->
  <span
    class="bot-avatar"
    :class="[`is-${size}`, bot.status, { 'is-editable': editable, 'tip-open': tipOpen }]"
    :data-bot="bot.name"
    :title="nativeTitle"
    :role="editable ? 'button' : undefined"
    :tabindex="editable || size === 'lg' ? 0 : undefined"
    @click="onEditClick"
    @keydown.enter.prevent="onEditClick"
    @keydown.space.prevent="onEditClick"
    @pointerenter="onTipEnter"
    @pointerleave="onTipLeave"
    @focus="onTipEnter"
    @blur="onTipLeave"
  >
    <CompanionAvatar
      class="avatar-stage"
      :character="characterId"
      :color="colorIndex"
      :state="avatarState"
      :size="size"
    />
    <!-- Point rouge = non-lus ou attente d’action utilisateur (waiting). -->
    <span
      v-if="size !== 'lg' && (hasUnread || bot.status === 'waiting')"
      class="avatar-pip unread"
      :class="{ 'is-md': size === 'md' }"
    />
    <span
      v-if="size === 'lg' && tipOpen"
      class="bot-avatar-tip"
      role="tooltip"
    >
      {{ statusLabel }}
    </span>
  </span>
</template>

<script setup>
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { CompanionAvatar, CHARACTER_IDS } from "@companion-avatar";
import { state } from "../store";

const props = defineProps({
  bot: { type: Object, required: true },
  size: { type: String, default: "sm" },
  /** Force unread notify (sinon lit state.unread) */
  unread: { type: Boolean, default: undefined },
  /** Clic → émet edit (picker animal / couleur) */
  editable: { type: Boolean, default: false },
  editTitle: { type: String, default: "" },
});

const emit = defineEmits(["edit"]);
const { t } = useI18n();
const tipOpen = ref(false);

const statusLabel = computed(() => t(`status.${props.bot.status || "idle"}`));

/** Pas de title navigateur sur lg (infobulle custom). */
const nativeTitle = computed(() => {
  if (props.size === "lg") return undefined;
  if (props.editable) return props.editTitle;
  return props.bot.label || props.bot.name;
});

function onTipEnter() {
  if (props.size === "lg") tipOpen.value = true;
}

function onTipLeave() {
  tipOpen.value = false;
}

function pickCharacter(seed) {
  const ids = CHARACTER_IDS;
  if (!ids.length) return "renard";
  const s = String(seed || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return ids[h % ids.length];
}

const characterId = computed(() => {
  const a = (props.bot.avatar || "").trim();
  if (a && CHARACTER_IDS.includes(a)) return a;
  return pickCharacter(props.bot.name || props.bot.id);
});

const colorIndex = computed(() => {
  const n = props.bot.avatar_color;
  if (n == null || n === "") return 0;
  return Math.max(0, Math.min(17, Number(n) || 0));
});

const hasUnread = computed(() => {
  if (props.unread !== undefined) return !!props.unread;
  return !!state.unread[props.bot.name];
});

/** Priorité : work > await > notify > idle */
const avatarState = computed(() => {
  const st = props.bot.status || "idle";
  if (st === "busy") return "work";
  if (st === "waiting") return "await";
  if (hasUnread.value) return "notify";
  return "idle";
});

function onEditClick() {
  if (!props.editable) return;
  emit("edit");
}
</script>
