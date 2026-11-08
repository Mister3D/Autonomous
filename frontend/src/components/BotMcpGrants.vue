<template>
  <div class="mcp-grants">
    <div class="mcp-grants-head">
      <span class="ui-toggle-main">
        <UiIconBadge size="sm">
          <UiIcon name="puzzle" :size="16" :stroke="1.9" />
        </UiIconBadge>
        <span class="ui-toggle-copy">
          <strong>{{ t("details.mcp") }}</strong>
          <small>{{ t("details.mcpHint") }}</small>
        </span>
      </span>
      <button
        class="settings-orb mcp-add"
        type="button"
        :aria-label="t('details.mcpAdd')"
        :title="t('details.mcpAdd')"
        @click="startPick"
      >
        <UiIcon name="plus" :size="14" />
      </button>
    </div>
    <p v-if="error && !open" class="mcp-grants-error">{{ error }}</p>
    <ul v-if="grants.length" class="mcp-grant-list">
      <li v-for="grant in grants" :key="grant.id">
        <span>
          <strong>{{ grant.device_name }} · {{ grant.server }}</strong>
          <small v-if="!grant.available">{{ t("details.mcpMissing") }}</small>
          <small v-else-if="!grant.online">{{ t("details.mcpOffline") }}</small>
        </span>
        <button class="btn danger-ghost" type="button" @click="remove(grant)">
          {{ t("details.mcpRemove") }}
        </button>
      </li>
    </ul>

    <Teleport to="body">
      <div v-if="open" class="modal-backdrop" @click.self="cancel">
        <div
          class="modal mcp-grant-modal"
          role="dialog"
          aria-modal="true"
          :aria-label="t('details.mcpDialog')"
        >
          <h2>{{ t("details.mcpDialog") }}</h2>
          <p class="field-hint">{{ t("details.mcpPickCompanion") }}</p>
          <p v-if="!companions.length" class="hint">{{ t("details.mcpNone") }}</p>
          <div v-else class="mcp-choice" role="listbox" :aria-label="t('details.mcpPickCompanion')">
            <button
              v-for="device in companions"
              :key="device.device_id"
              type="button"
              :class="{ active: device.device_id === chosenId }"
              @click="chooseCompanion(device)"
            >
              <strong>{{ device.device_name }}</strong>
              <small :class="{ on: device.online }">
                {{ device.online ? t("companion.online") : t("companion.offline") }}
              </small>
            </button>
          </div>
          <template v-if="chosenId">
            <p class="field-hint">{{ t("details.mcpPickServer") }}</p>
            <div class="mcp-choice" role="listbox" :aria-label="t('details.mcpPickServer')">
              <button
                v-for="server in serversForChosen"
                :key="server.server"
                type="button"
                :disabled="already(server)"
                :class="{ active: picked && picked.server === server.server && picked.device_id === server.device_id }"
                @click="picked = server"
              >
                <strong>{{ server.server }}</strong>
              </button>
            </div>
          </template>
          <p v-if="error" class="mcp-grants-error">{{ error }}</p>
          <div class="mcp-dialog-actions">
            <button class="btn ghost" type="button" @click="cancel">{{ t("details.mcpCancel") }}</button>
            <button class="btn primary" type="button" :disabled="!canAdd" @click="grant(picked)">
              {{ t("details.mcpAdd") }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import UiIcon from "./ui/UiIcon.vue";
import UiIconBadge from "./ui/UiIconBadge.vue";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();

const grants = ref([]);
const servers = ref([]);
const error = ref("");
const open = ref(false);
const chosenId = ref("");
const picked = ref(null);

const companions = computed(() => {
  const seen = new Map();
  for (const server of servers.value) {
    if (!seen.has(server.device_id)) {
      seen.set(server.device_id, {
        device_id: server.device_id,
        device_name: server.device_name,
        online: !!server.online,
      });
    }
  }
  return [...seen.values()];
});

const serversForChosen = computed(() =>
  servers.value.filter((server) => server.device_id === chosenId.value)
);

const canAdd = computed(
  () => picked.value && !already(picked.value)
);

function already(server) {
  return grants.value.some(
    (grant) => grant.device_id === server.device_id && grant.server === server.server
  );
}

async function load() {
  error.value = "";
  try {
    const data = await api.listBotMcp(props.bot.name);
    grants.value = data.grants || [];
    servers.value = data.servers || [];
  } catch (e) {
    error.value = e.message;
  }
}

function startPick() {
  error.value = "";
  chosenId.value = "";
  picked.value = null;
  open.value = true;
}

function chooseCompanion(device) {
  if (chosenId.value !== device.device_id) {
    chosenId.value = device.device_id;
    picked.value = null;
  }
}

function cancel() {
  open.value = false;
  chosenId.value = "";
  picked.value = null;
  error.value = "";
}

function onKey(ev) {
  if (ev.key === "Escape" && open.value) cancel();
}

async function grant(server) {
  if (!server || already(server)) return;
  error.value = "";
  try {
    const row = await api.grantBotMcp(props.bot.name, {
      device_id: server.device_id,
      server: server.server,
    });
    grants.value = [...grants.value.filter((g) => g.id !== row.id), row].sort((a, b) =>
      `${a.device_name} ${a.server}`.localeCompare(`${b.device_name} ${b.server}`)
    );
    cancel();
  } catch (e) {
    error.value = e.message;
  }
}

async function remove(grant) {
  error.value = "";
  try {
    await api.revokeBotMcp(props.bot.name, grant.id);
    grants.value = grants.value.filter((row) => row.id !== grant.id);
  } catch (e) {
    error.value = e.message;
  }
}

watch(() => props.bot.name, () => {
  cancel();
  load();
}, { immediate: true });
document.addEventListener("keydown", onKey);
onUnmounted(() => document.removeEventListener("keydown", onKey));
</script>
