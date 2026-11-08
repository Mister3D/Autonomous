<template>
  <div class="settings-page">
    <header class="settings-page-head">
      <button class="icon-btn" type="button" :aria-label="t('settings.back')" @click="leave">
        <UiIcon name="chevron-left" />
      </button>
      <h1>{{ t("settings.title") }}</h1>
    </header>
    <div class="settings-layout">
      <nav class="settings-nav" :aria-label="t('settings.title')">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          :class="{ active: section === tab.id }"
          :aria-current="section === tab.id ? 'page' : undefined"
          @click="openSection(tab.id)"
        >
          <UiIcon class="settings-nav-ico" :name="tab.icon" />
          <span>{{ t(tab.label) }}</span>
        </button>
      </nav>
      <div class="settings-main">
      <LlmSettings v-if="section === 'llm'" />
      <GroundingSettings v-if="section === 'grounding'" />
      <UiCard
        v-if="section === 'agent'"
        :title="t('lang.choose')"
        :hint="t('settings.languageHint')"
      >
        <template #icon>
          <UiIcon name="lang" :size="18" />
        </template>
        <div class="settings-field">
          <div
            class="lang-seg"
            role="radiogroup"
            :aria-label="t('lang.choose')"
          >
            <button
              v-for="code in langCodes"
              :key="code"
              type="button"
              role="radio"
              class="lang-opt"
              :class="{ active: localeCode === code }"
              :aria-checked="localeCode === code"
              @click="chooseLang(code)"
            >
              <LocaleFlag :code="code" />
              <strong>{{ code === "fr" ? t("lang.fr") : t("lang.en") }}</strong>
            </button>
          </div>
        </div>
        <div class="info-row settings-version-row">
          <span>
            <strong>{{ t("pi.version") }}</strong>
            <small>{{ loading ? "…" : status?.version || "—" }}</small>
          </span>
        </div>
      </UiCard>

      <UiCard
        v-if="section === 'agent'"
        :title="t('settings.timezone')"
        :hint="t('settings.timezoneHint')"
      >
        <template #icon>
          <UiIcon name="clock" :size="18" />
        </template>
        <div class="settings-field">
          <div class="settings-tz">
            <input
              v-model="tzQuery"
              type="text"
              :placeholder="t('settings.timezonePlaceholder')"
              autocomplete="off"
              spellcheck="false"
              role="combobox"
              aria-autocomplete="list"
              :aria-expanded="tzOpen && timezoneMatches.length > 0"
              @focus="onTzFocus"
              @input="onTzInput"
              @keydown="onTzKey"
              @blur="onTzBlur"
            />
            <ul v-if="tzOpen && timezoneMatches.length" class="tz-suggest" role="listbox">
              <li v-for="(zone, i) in timezoneMatches" :key="zone">
                <button
                  type="button"
                  :class="{ active: i === tzActive }"
                  @mousedown.prevent="pickTimezone(zone)"
                >
                  {{ zone }}
                </button>
              </li>
            </ul>
          </div>
        </div>
        <p v-if="tzError" class="vault-error">{{ tzError }}</p>
      </UiCard>

      <UiCard
        v-if="section === 'agent'"
        :title="t('settings.passwordTitle')"
        :hint="t('settings.passwordHint')"
      >
        <template #icon>
          <UiIcon name="key" :size="18" />
        </template>
        <label class="settings-field">
          <span>{{ t("settings.passwordCurrent") }}</span>
          <SecretInput
            v-model="pwCurrent"
            autocomplete="current-password"
            :disabled="pwBusy"
            required
          />
        </label>
        <label class="settings-field">
          <span>{{ t("settings.passwordNew") }}</span>
          <SecretInput
            v-model="pwNew"
            autocomplete="new-password"
            :disabled="pwBusy"
            required
          />
          <small>{{ t("settings.passwordTooShort") }}</small>
        </label>
        <label class="settings-field">
          <span>{{ t("settings.passwordConfirm") }}</span>
          <SecretInput
            v-model="pwConfirm"
            autocomplete="new-password"
            :disabled="pwBusy"
            required
          />
        </label>
        <div class="setup-toolbar">
          <UiButton
            variant="primary"
            :disabled="pwBusy || !pwCanSubmit"
            @click="submitPasswordChange"
          >
            {{ pwBusy ? t("settings.passwordBusy") : t("settings.passwordSubmit") }}
          </UiButton>
          <span v-if="pwOk" class="setup-ok">{{ pwOk }}</span>
          <span v-if="pwError" class="vault-error">{{ pwError }}</span>
        </div>
      </UiCard>

      <UiCard
        v-if="section === 'agent'"
        :title="t('update.channelTitle')"
        :hint="t('update.channelHint')"
      >
        <template #icon>
          <UiIcon name="update" :size="18" />
        </template>
        <div class="settings-field">
          <span>{{ t("update.remoteUrl") }}</span>
          <input
            v-model="updateRemoteDraft"
            type="url"
            :placeholder="t('update.remoteUrlPlaceholder')"
            :disabled="updateChannelBusy || !updateGit"
            autocomplete="off"
            spellcheck="false"
          />
          <small>{{ t("update.remoteUrlHint") }}</small>
          <small v-if="updateRemoteSaved">{{ t("update.remoteUsingCustom") }}</small>
          <small v-else-if="updateOriginUrl">
            {{ t("update.remoteUsingOrigin", { url: updateOriginUrl }) }}
          </small>
          <button
            class="btn"
            type="button"
            :disabled="updateChannelBusy || !updateGit || updateRemoteDraft.trim() === updateRemoteSaved"
            @click="saveUpdateRemote"
          >
            {{ t("update.remoteUrlSave") }}
          </button>
        </div>
        <div class="settings-field">
          <span>{{ t("update.channel") }}</span>
          <div
            class="update-channel-seg update-channel-seg-3"
            role="radiogroup"
            :aria-label="t('update.channel')"
            :aria-disabled="updateChannelBusy || !updateGit ? 'true' : undefined"
          >
            <button
              type="button"
              role="radio"
              class="update-channel-opt"
              :class="{ active: updatePreset === 'main' }"
              :aria-checked="updatePreset === 'main'"
              :disabled="updateChannelBusy || !updateGit"
              @click="pickUpdateChannel('main')"
            >
              <strong>{{ t("update.channelMain") }}</strong>
              <small>{{ t("update.channelMainHint") }}</small>
            </button>
            <button
              type="button"
              role="radio"
              class="update-channel-opt"
              :class="{ active: updatePreset === 'dev' }"
              :aria-checked="updatePreset === 'dev'"
              :disabled="updateChannelBusy || !updateGit"
              @click="pickUpdateChannel('dev')"
            >
              <strong>{{ t("update.channelDev") }}</strong>
              <small>{{ t("update.channelDevHint") }}</small>
            </button>
            <button
              type="button"
              role="radio"
              class="update-channel-opt"
              :class="{ active: updatePreset === 'custom' }"
              :aria-checked="updatePreset === 'custom'"
              :disabled="updateChannelBusy || !updateGit"
              @click="pickUpdateChannel('custom')"
            >
              <strong>{{ t("update.channelCustom") }}</strong>
              <small>{{ t("update.channelCustomHint") }}</small>
            </button>
          </div>
          <div v-if="updatePreset === 'custom'" class="update-custom-branch">
            <label>
              <span>{{ t("update.customBranch") }}</span>
              <input
                v-model="updateCustomBranch"
                type="text"
                :placeholder="t('update.customBranchPlaceholder')"
                :disabled="updateChannelBusy || !updateGit"
                autocomplete="off"
                spellcheck="false"
                @keydown.enter.prevent="saveCustomBranch"
              />
            </label>
            <button
              class="btn"
              type="button"
              :disabled="
                updateChannelBusy ||
                !updateGit ||
                !updateCustomBranch.trim() ||
                updateCustomBranch.trim() === updateChannelSaved
              "
              @click="saveCustomBranch"
            >
              {{ t("update.customBranchSave") }}
            </button>
          </div>
          <small>{{ t("update.channelHelp") }}</small>
        </div>
        <p v-if="!updateGit" class="hint">{{ t("update.noGit") }}</p>
        <p v-if="updateChannelError" class="vault-error">{{ updateChannelError }}</p>
      </UiCard>

      <UiCard
        v-if="section === 'agent'"
        :title="t('guard.title')"
        :hint="t('guard.hint')"
      >
        <template #icon>
          <UiIcon name="crosshair" :size="18" />
        </template>
        <label class="settings-field">
          <span>{{ t("guard.reviewEvery") }}</span>
          <input
            v-model.number="guard.reviewEvery"
            type="number"
            min="0"
            max="100000"
            step="1"
            @change="flushGuard"
          />
          <small>{{ t("guard.reviewEveryHint") }}</small>
        </label>
        <label class="settings-field">
          <span>{{ t("guard.maxActions") }}</span>
          <input
            v-model.number="guard.maxActions"
            type="number"
            min="1"
            max="100000"
            step="1"
            @change="flushGuard"
          />
          <small>{{ t("guard.maxActionsHint") }}</small>
        </label>
        <p v-if="guardError" class="vault-error">{{ guardError }}</p>
      </UiCard>

      <UiCard
        v-if="section === 'vault'"
        :title="t('settings.tabVault')"
        :hint="t('vault.settingsHint')"
      >
        <template #icon>
          <UiIcon name="vault" :size="18" />
        </template>
        <p v-if="vaultError" class="vault-error">{{ vaultError }}</p>
        <ul v-if="entries.length" class="settings-list">
          <li v-for="e in entries" :key="e.id">
            <div>
              <strong>{{ e.label }}</strong>
              <small>{{ e.kind }}<template v-if="e.origin"> · {{ e.origin }}</template></small>
            </div>
            <button
              class="vault-trash"
              type="button"
              :title="t('vault.delete')"
              :aria-label="t('vault.delete')"
              @click="removeEntry(e)"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path d="M5 7.5h14" />
                <path d="M9.5 7.5V5.8A1.3 1.3 0 0 1 10.8 4.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
                <path d="M8 7.5l.7 11a1.4 1.4 0 0 0 1.4 1.3h4.8a1.4 1.4 0 0 0 1.4-1.3l.7-11" />
              </svg>
            </button>
          </li>
        </ul>
        <p v-else class="hint">{{ t("vault.empty") }}</p>
      </UiCard>

      <UiCard
        v-if="section === 'memory'"
        :title="t('settings.tabMemory')"
        :hint="t('memory.settingsHint')"
      >
        <template #icon>
          <UiIcon name="memory" :size="18" />
        </template>
        <p v-if="memError" class="vault-error">{{ memError }}</p>
        <ul v-if="memEntries.length" class="settings-list">
          <li v-for="e in memEntries" :key="e.id">
            <div>
              <strong>{{ e.label }}</strong>
              <small>
                <code>{{ e.key }}</code>
                · {{ e.tier === "core" ? t("memory.tierCore") : t("memory.tierBrowse") }}
                · {{ e.value }}
              </small>
            </div>
            <button
              class="vault-trash"
              type="button"
              :title="t('memory.delete')"
              :aria-label="t('memory.delete')"
              @click="removeMemory(e)"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                <path d="M5 7.5h14" />
                <path d="M9.5 7.5V5.8A1.3 1.3 0 0 1 10.8 4.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
                <path d="M8 7.5l.7 11a1.4 1.4 0 0 0 1.4 1.3h4.8a1.4 1.4 0 0 0 1.4-1.3l.7-11" />
              </svg>
            </button>
          </li>
        </ul>
        <p v-else class="hint">{{ t("memory.empty") }}</p>
      </UiCard>

      <UiCard
        v-if="section === 'companions'"
        :title="t('settings.tabCompanions')"
        :hint="t('companion.hint')"
      >
        <template #icon>
          <UiIcon name="monitor" :size="18" />
        </template>
        <p v-if="needCompanion" class="companion-need">{{ t("companion.needOne") }}</p>
        <p class="hint justified companion-responsibility">{{ t("companion.responsibility") }}</p>
        <label class="settings-field companion-pairing-toggle">
          <span class="settings-notify">
            <span>{{ t("companion.pairingEnabled") }}</span>
            <input
              v-model="companionsEnabled"
              type="checkbox"
              role="switch"
              :aria-label="t('companion.pairingEnabled')"
              @change="flushCompanionsEnabled"
            />
          </span>
          <small>{{ t("companion.pairingEnabledHint") }}</small>
        </label>
        <p v-if="deviceError" class="vault-error">{{ deviceError }}</p>
        <ul v-if="devicePending.length" class="settings-list">
          <li v-for="p in devicePending" :key="p.id">
            <div>
              <strong class="mono">{{ p.user_code }}</strong>
              <small>{{ p.name }} · {{ platformLabel(p.platform) }} · {{ t("companion.pending") }}</small>
            </div>
            <span class="settings-row-side">
              <button class="btn primary" type="button" @click="approveDevice(p)">
                {{ t("companion.approve") }}
              </button>
              <button class="btn" type="button" @click="denyDevice(p)">
                {{ t("companion.deny") }}
              </button>
            </span>
          </li>
        </ul>
        <ul v-if="deviceRows.length" class="settings-list">
          <li v-for="d in deviceRows" :key="d.id">
            <div class="settings-identity">
              <strong>{{ d.name }}</strong>
              <span v-if="d.platform" class="settings-platform">{{ platformLabel(d.platform) }}</span>
            </div>
            <span class="settings-row-side">
              <label class="settings-notify">
                <span>{{ t("companion.notify") }}</span>
                <input
                  type="checkbox"
                  role="switch"
                  :checked="!!d.notify"
                  :aria-label="t('companion.notify')"
                  @change="onDeviceNotify(d, $event)"
                />
              </label>
              <span class="settings-status" :class="{ off: !d.online }">
                {{ d.online ? t("companion.online") : t("companion.offline") }}
              </span>
              <button
                class="settings-orb companion-revoke"
                type="button"
                :title="t('companion.revoke')"
                :aria-label="t('companion.revoke')"
                @click="revokeDevice(d)"
              >
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <path d="M5 7.5h14" />
                  <path d="M9.5 7.5V5.8A1.3 1.3 0 0 1 10.8 4.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
                  <path d="M8 7.5l.7 11a1.4 1.4 0 0 0 1.4 1.3h4.8a1.4 1.4 0 0 0 1.4-1.3l.7-11" />
                </svg>
              </button>
            </span>
          </li>
        </ul>
        <div v-if="deviceRows.length" class="companion-notify-actions">
          <button class="btn" type="button" :disabled="notifyTesting" @click="testNotify">
            {{ t("companion.testNotify") }}
          </button>
          <p v-if="notifyNote" class="hint">{{ notifyNote }}</p>
        </div>
        <p v-else-if="devicesReady && !devicePending.length" class="hint">{{ t("companion.empty") }}</p>
        <div class="companion-download">
          <h4>{{ t("companion.downloadTitle") }}</h4>
          <p class="hint justified">{{ t("companion.downloadHint") }}</p>
          <p v-if="buildError" class="vault-error">{{ buildError }}</p>
          <template v-if="companionBuild">
            <p class="hint">
              {{ t("companion.version") }} {{ companionBuild.version || "?" }} ·
              {{ t("companion.buildStatus") }} {{ t("companion.state_" + companionBuild.state) }}
            </p>
            <ul v-if="companionBuild.artifacts.length" class="settings-list">
              <li v-for="a in companionBuild.artifacts" :key="a.target">
                <span>
                  <strong>{{ platformLabel(a.platform) }}</strong>
                  <small> · {{ a.target }} · {{ (a.size / 1048576).toFixed(1) }} MB</small>
                </span>
                <a class="btn" :href="a.url" download>{{ t("companion.download") }}</a>
              </li>
            </ul>
            <template v-if="companionBuild.state === 'no_toolchain'">
              <p class="hint justified">{{ t("companion.noToolchain") }}</p>
              <pre class="companion-cmd">{{ companionBuild.rustup_hint }}</pre>
            </template>
            <p v-for="n in companionBuild.notes" :key="n" class="hint">{{ n }}</p>
            <p v-if="companionBuild.error" class="vault-error">{{ companionBuild.error }}</p>
            <pre
              v-if="companionBuild.log?.length"
              ref="companionLogEl"
              class="setup-log companion-build-log"
            >{{ companionBuild.log.join("\n") }}</pre>
            <button
              v-if="companionBuild.toolchain"
              class="btn"
              type="button"
              :disabled="companionBuild.state === 'building'"
              @click="rebuildCompanion"
            >
              {{ companionBuild.state === "building" ? t("setup.running") : t("companion.rebuild") }}
            </button>
          </template>
        </div>
      </UiCard>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";
import { setLocale } from "../i18n";
import { botPath } from "../router";
import { currentBotObj, state } from "../store";
import GroundingSettings from "./GroundingSettings.vue";
import LlmSettings from "./LlmSettings.vue";
import LocaleFlag from "./LocaleFlag.vue";
import SecretInput from "./SecretInput.vue";
import UiButton from "./ui/UiButton.vue";
import UiCard from "./ui/UiCard.vue";
import UiIcon from "./ui/UiIcon.vue";

function platformLabel(raw) {
  const key = String(raw || "").trim().toLowerCase();
  if (key === "windows") return "Windows";
  if (key === "linux") return "Linux";
  if (key === "macos" || key === "darwin" || key === "mac") return "macOS";
  if (!key) return "";
  return key.charAt(0).toUpperCase() + key.slice(1);
}

const SECTIONS = ["agent", "llm", "grounding", "vault", "memory", "companions"];
const DEFAULT_TZ = "Europe/Paris";
const tabs = [
  { id: "agent", label: "settings.tabAgent", icon: "terminal" },
  { id: "llm", label: "settings.tabLlm", icon: "spark" },
  { id: "grounding", label: "settings.tabGrounding", icon: "crosshair" },
  { id: "vault", label: "settings.tabVault", icon: "vault" },
  { id: "memory", label: "settings.tabMemory", icon: "memory" },
  { id: "companions", label: "settings.tabCompanions", icon: "monitor" },
];

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const langCodes = ["fr", "en"];
const localeCode = computed(() => (locale.value === "fr" ? "fr" : "en"));

function chooseLang(code) {
  setLocale(code);
}
const needCompanion = computed(() => route.query.besoin === "connexion");
const section = computed(() => {
  const raw = String(route.params.section || "agent");
  return SECTIONS.includes(raw) ? raw : "agent";
});

function openSection(id) {
  router.replace({ name: "settings", params: { section: id } });
}

function leave() {
  const back = sessionStorage.getItem("autonomous.settingsReturn") || "";
  if (back.startsWith("/") && !back.startsWith("/settings")) {
    router.push(back);
    return;
  }
  const bot = currentBotObj();
  if (bot?.name) router.push(botPath(bot.name, state.tab || "discussion"));
  else router.push("/");
}

watch(
  () => route.params.section,
  (raw) => {
    if (raw && !SECTIONS.includes(String(raw))) {
      router.replace({ name: "settings", params: { section: "agent" } });
    }
  },
  { immediate: true },
);
const status = ref(null);
const loading = ref(true);
const entries = ref([]);
const vaultError = ref("");
const devicePending = ref([]);
const deviceRows = ref([]);
const deviceError = ref("");
const notifyNote = ref("");
const notifyTesting = ref(false);
const devicesReady = ref(false);
let deviceTimer = 0;
const memEntries = ref([]);
const memError = ref("");
const guardError = ref("");
const guardReady = ref(false);
let guardTimer = 0;
let guardSaveGen = 0;
let guardLast = "";
const ALL_ZONES =
  typeof Intl !== "undefined" && typeof Intl.supportedValuesOf === "function"
    ? Intl.supportedValuesOf("timeZone")
    : ["UTC", "Europe/Paris"];
const timezone = ref("");
const tzQuery = ref("");
const tzOpen = ref(false);
const tzActive = ref(0);
const tzDirty = ref(false);
const tzError = ref("");
const pwCurrent = ref("");
const pwNew = ref("");
const pwConfirm = ref("");
const pwBusy = ref(false);
const pwError = ref("");
const pwOk = ref("");
const updateChannel = ref("main");
const updateChannelBusy = ref(false);
const updateChannelError = ref("");
const updateGit = ref(true);
const updateCustomBranch = ref("");
const updateRemoteDraft = ref("");
const updateRemoteSaved = ref("");
const updateOriginUrl = ref("");
let updateChannelSaved = "main";

const updatePreset = computed(() => {
  const ch = updateChannel.value;
  if (ch === "main" || ch === "dev") return ch;
  return "custom";
});

const pwCanSubmit = computed(
  () =>
    !!pwCurrent.value &&
    pwNew.value.length >= 8 &&
    pwNew.value === pwConfirm.value &&
    pwNew.value !== pwCurrent.value,
);

async function submitPasswordChange() {
  pwError.value = "";
  pwOk.value = "";
  if (pwNew.value !== pwConfirm.value) {
    pwError.value = t("settings.passwordMismatch");
    return;
  }
  if (pwNew.value.length < 8) {
    pwError.value = t("settings.passwordTooShort");
    return;
  }
  pwBusy.value = true;
  try {
    await api.changePassword(pwCurrent.value, pwNew.value);
    pwCurrent.value = "";
    pwNew.value = "";
    pwConfirm.value = "";
    pwOk.value = t("settings.passwordOk");
  } catch (e) {
    pwError.value = e.message || t("login.changeError");
  } finally {
    pwBusy.value = false;
  }
}

function tzScore(zone, q) {
  const full = zone.toLowerCase();
  const city = zone.split("/").pop().toLowerCase().replace(/_/g, " ");
  const cityCompact = city.replace(/ /g, "");
  const qCompact = q.replace(/[\s_]/g, "");
  if (city === q || full === q) return 0;
  if (city.startsWith(q) || cityCompact.startsWith(qCompact)) return 1;
  if (full.startsWith(q)) return 2;
  if (city.includes(q) || cityCompact.includes(qCompact)) return 3;
  if (full.includes(q)) return 4;
  return 9;
}

const timezoneMatches = computed(() => {
  const q = tzQuery.value.trim().toLowerCase();
  if (!q) return [];
  return ALL_ZONES
    .map((zone) => ({ zone, score: tzScore(zone, q) }))
    .filter((row) => row.score < 9)
    .sort((a, b) => a.score - b.score || a.zone.localeCompare(b.zone))
    .slice(0, 8)
    .map((row) => row.zone);
});

watch(timezoneMatches, () => {
  tzActive.value = 0;
});
const guard = reactive({
  reviewEvery: 100,
  maxActions: 1000,
  groundingLoops: 2,
});
watch(
  () => [guard.reviewEvery, guard.maxActions, guard.groundingLoops],
  () => {
    if (!guardReady.value) return;
    window.clearTimeout(guardTimer);
    guardTimer = window.setTimeout(saveGuard, 350);
  },
);
async function loadTimezone() {
  const s = await api.settings();
  const stored = String(s.timezone || "").trim();
  const current = stored || DEFAULT_TZ;
  timezone.value = current;
  if (!tzDirty.value) tzQuery.value = current;
  if (!stored) {
    await api.putSettings({ timezone: DEFAULT_TZ });
    state.userTimezone = DEFAULT_TZ;
  }
}

function onTzFocus(ev) {
  tzOpen.value = true;
  tzDirty.value = true;
  ev.target.select();
}

function onTzInput() {
  tzDirty.value = true;
  tzOpen.value = true;
}

function onTzKey(ev) {
  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    tzOpen.value = true;
    const last = Math.max(timezoneMatches.value.length - 1, 0);
    tzActive.value = Math.min(tzActive.value + 1, last);
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    tzActive.value = Math.max(tzActive.value - 1, 0);
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    const zone = timezoneMatches.value[tzActive.value];
    if (zone) pickTimezone(zone);
  } else if (ev.key === "Escape") {
    tzOpen.value = false;
    tzQuery.value = timezone.value;
  }
}

function onTzBlur() {
  tzOpen.value = false;
  const only = timezoneMatches.value.length === 1 ? timezoneMatches.value[0] : "";
  const q = tzQuery.value.trim().toLowerCase();
  const exact = ALL_ZONES.find((zone) => zone.toLowerCase() === q);
  if (only) pickTimezone(only);
  else if (exact) pickTimezone(exact);
  else tzQuery.value = timezone.value;
}

async function pickTimezone(zone) {
  if (!zone) return;
  tzOpen.value = false;
  tzQuery.value = zone;
  tzError.value = "";
  if (zone === timezone.value) return;
  const prev = timezone.value;
  timezone.value = zone;
  try {
    await api.putSettings({ timezone: zone });
    state.userTimezone = zone;
  } catch (e) {
    timezone.value = prev;
    tzQuery.value = prev;
    tzError.value = e.message;
  }
}

function guardBody() {
  const values = [guard.reviewEvery, guard.maxActions, guard.groundingLoops];
  if (values.some((n) => typeof n !== "number" || !Number.isFinite(n))) return null;
  return {
    "guard.review_every": Math.max(0, Math.min(100000, Math.round(guard.reviewEvery))),
    "guard.max_actions": Math.max(1, Math.min(100000, Math.round(guard.maxActions))),
    "grounding.max_loops": Math.max(1, Math.min(8, Math.round(guard.groundingLoops))),
  };
}

function applyGuardBody(body) {
  guard.reviewEvery = body["guard.review_every"];
  guard.maxActions = body["guard.max_actions"];
  guard.groundingLoops = body["grounding.max_loops"];
}

async function loadGuard() {
  guardReady.value = false;
  const s = await api.settings();
  const rev = s["guard.review_every"];
  const maxA = s["guard.max_actions"];
  const loops = s["grounding.max_loops"];
  if (rev != null) guard.reviewEvery = Number(rev);
  if (maxA != null) guard.maxActions = Number(maxA);
  if (loops != null) guard.groundingLoops = Number(loops);
  guardLast = JSON.stringify(guardBody());
  guardReady.value = true;
}

async function saveGuard() {
  const body = guardBody();
  if (!body) return;
  const key = JSON.stringify(body);
  if (key === guardLast) return;
  const gen = ++guardSaveGen;
  guardError.value = "";
  try {
    await api.putSettings(body);
    if (gen !== guardSaveGen) return;
    guardLast = key;
    if (key !== JSON.stringify(guardBody())) applyGuardBody(body);
  } catch (e) {
    if (gen !== guardSaveGen) return;
    guardError.value = e.message;
  }
}

function flushGuard() {
  window.clearTimeout(guardTimer);
  const body = guardBody();
  if (!body) {
    if (guardLast) applyGuardBody(JSON.parse(guardLast));
    return;
  }
  saveGuard();
}

async function loadVault() {
  entries.value = await api.vaultEntries();
}

async function removeEntry(e) {
  if (!confirm(t("vault.confirmDelete", { label: e.label }))) return;
  try {
    await api.deleteVaultEntry(e.id);
    await loadVault();
  } catch (err) {
    vaultError.value = err.message;
  }
}

async function loadMemory() {
  memEntries.value = await api.memoryEntries();
}

async function removeMemory(e) {
  if (!confirm(t("memory.confirmDelete", { label: e.label || e.key }))) return;
  try {
    await api.deleteMemoryEntry(e.key);
    await loadMemory();
  } catch (err) {
    memError.value = err.message;
  }
}

const companionBuild = ref(null);
const companionLogEl = ref(null);
const buildError = ref("");
const companionsEnabled = ref(true);
let companionBuildTimer = 0;

watch(
  () => companionBuild.value?.log?.length,
  async () => {
    await nextTick();
    if (companionLogEl.value) companionLogEl.value.scrollTop = companionLogEl.value.scrollHeight;
  },
);

async function loadCompanionsEnabled() {
  try {
    const s = await api.settings();
    companionsEnabled.value = s["companions.enabled"] !== false;
  } catch {
    companionsEnabled.value = true;
  }
}

async function flushCompanionsEnabled() {
  deviceError.value = "";
  try {
    await api.putSettings({ "companions.enabled": !!companionsEnabled.value });
  } catch (err) {
    deviceError.value = err.message;
    companionsEnabled.value = !companionsEnabled.value;
  }
}

function scheduleCompanionBuildPoll() {
  clearTimeout(companionBuildTimer);
  const building = companionBuild.value?.state === "building";
  if (section.value !== "companions" && !building) return;
  companionBuildTimer = window.setTimeout(async () => {
    if (section.value === "companions" || companionBuild.value?.state === "building") {
      await loadCompanionBuild();
    }
    scheduleCompanionBuildPoll();
  }, building ? 1200 : 4000);
}

async function loadCompanionBuild() {
  try {
    companionBuild.value = await api.companionBuild();
    buildError.value = "";
  } catch (e) {
    buildError.value = e.message;
  }
}

async function rebuildCompanion() {
  buildError.value = "";
  try {
    companionBuild.value = await api.rebuildCompanion();
    scheduleCompanionBuildPoll();
  } catch (e) {
    buildError.value = e.message;
  }
}

async function loadDevices() {
  const data = await api.listDevices();
  devicePending.value = data.pending || [];
  deviceRows.value = data.devices || [];
  devicesReady.value = true;
}

async function approveDevice(row) {
  deviceError.value = "";
  try {
    await api.approveDevice(row.id);
    await loadDevices();
  } catch (err) {
    deviceError.value = err.message;
  }
}

async function denyDevice(row) {
  deviceError.value = "";
  try {
    await api.denyDevice(row.id);
    await loadDevices();
  } catch (err) {
    deviceError.value = err.message;
  }
}

async function onDeviceNotify(row, ev) {
  const next = ev.target.checked;
  const previous = !!row.notify;
  notifyNote.value = "";
  deviceError.value = "";
  row.notify = next;
  try {
    await api.patchDevice(row.id, { notify: next });
  } catch (err) {
    row.notify = previous;
    ev.target.checked = previous;
    deviceError.value = err.message;
  }
}

async function testNotify() {
  deviceError.value = "";
  notifyNote.value = "";
  notifyTesting.value = true;
  try {
    await api.notifyDevices({
      title: t("companion.testNotifyTitle"),
      body: t("companion.testNotifyBody"),
    });
    notifyNote.value = t("companion.testNotifyOk");
  } catch (err) {
    deviceError.value = err.message;
  } finally {
    notifyTesting.value = false;
  }
}

async function revokeDevice(row) {
  if (!confirm(t("companion.confirmRevoke", { name: row.name }))) return;
  deviceError.value = "";
  try {
    await api.revokeDevice(row.id);
    await loadDevices();
  } catch (err) {
    deviceError.value = err.message;
  }
}

async function loadUpdateChannel() {
  updateChannelError.value = "";
  try {
    const st = await api.updateStatus(false);
    const ch = String(st.channel || "main").trim() || "main";
    updateChannel.value = ch;
    updateChannelSaved = ch;
    updateCustomBranch.value = ch === "main" || ch === "dev" ? "" : ch;
    updateRemoteSaved.value = String(st.remote_url || "").trim();
    updateRemoteDraft.value = updateRemoteSaved.value;
    updateOriginUrl.value = String(st.origin_url || "").trim();
    updateGit.value = st.git !== false && st.code !== "no_git";
  } catch (e) {
    updateChannelError.value = e.message || String(e);
    updateGit.value = false;
  }
}

async function applyUpdateBranch(want) {
  const branch = String(want || "").trim();
  if (!branch || updateChannelBusy.value || !updateGit.value) return;
  if (branch === updateChannelSaved) {
    updateChannel.value = branch;
    return;
  }
  updateChannelError.value = "";
  if (branch !== "main") {
    if (!confirm(t("update.confirmDev"))) return;
  }
  updateChannel.value = branch;
  updateChannelBusy.value = true;
  try {
    await api.setUpdateChannel({
      channel: branch,
      confirm_dev: branch !== "main",
    });
    updateChannelSaved = branch;
    if (branch !== "main" && branch !== "dev") {
      updateCustomBranch.value = branch;
    }
  } catch (e) {
    updateChannelError.value = e.message || String(e);
    updateChannel.value = updateChannelSaved;
  } finally {
    updateChannelBusy.value = false;
  }
}

async function pickUpdateChannel(next) {
  if (next === "custom") {
    updateChannel.value =
      updateCustomBranch.value.trim() ||
      (updateChannelSaved !== "main" && updateChannelSaved !== "dev"
        ? updateChannelSaved
        : "");
    if (!updateCustomBranch.value.trim() && updateChannel.value) {
      updateCustomBranch.value = updateChannel.value;
    }
    return;
  }
  await applyUpdateBranch(next === "dev" ? "dev" : "main");
}

async function saveCustomBranch() {
  await applyUpdateBranch(updateCustomBranch.value.trim());
}

async function saveUpdateRemote() {
  if (updateChannelBusy.value || !updateGit.value) return;
  const next = updateRemoteDraft.value.trim();
  if (next === updateRemoteSaved.value) return;
  updateChannelError.value = "";
  updateChannelBusy.value = true;
  try {
    const st = await api.setUpdateChannel({ remote_url: next });
    updateRemoteSaved.value = String(st.remote_url || "").trim();
    updateRemoteDraft.value = updateRemoteSaved.value;
    updateOriginUrl.value = String(st.origin_url || updateOriginUrl.value || "").trim();
  } catch (e) {
    updateChannelError.value = e.message || String(e);
  } finally {
    updateChannelBusy.value = false;
  }
}

onUnmounted(() => {
  window.clearTimeout(guardTimer);
  window.clearTimeout(companionBuildTimer);
  window.clearInterval(deviceTimer);
});

onMounted(async () => {
  loadTimezone().catch((e) => {
    tzError.value = e.message;
  });
  loadUpdateChannel().catch((e) => {
    updateChannelError.value = e.message;
  });
  try {
    status.value = await api.piStatus();
  } catch (e) {
    status.value = { ready: false, reason: "error", doc_url: "https://pi.dev/docs/latest/models" };
  } finally {
    loading.value = false;
  }
  try {
    await loadGuard();
  } catch (e) {
    guardError.value = e.message;
  }
  try {
    await loadVault();
  } catch (e) {
    vaultError.value = e.message;
  }
  try {
    await loadMemory();
  } catch (e) {
    memError.value = e.message;
  }
  try {
    await loadDevices();
  } catch (e) {
    deviceError.value = e.message;
  }
  loadCompanionsEnabled().catch(() => {});
  await loadCompanionBuild();
  scheduleCompanionBuildPoll();
  deviceTimer = window.setInterval(() => {
    loadDevices().catch((e) => {
      deviceError.value = e.message;
    });
  }, 3000);
});

watch(
  () => section.value,
  (id) => {
    if (id === "companions") {
      loadCompanionBuild().then(() => scheduleCompanionBuildPoll());
    }
  },
);
</script>
