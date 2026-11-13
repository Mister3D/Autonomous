<template>
  <div class="settings-page">
    <div class="settings-layout">
      <aside class="settings-side">
        <header class="settings-side-head">
          <button class="icon-btn" type="button" :aria-label="t('settings.back')" @click="leave">
            <UiIcon name="chevron-left" />
          </button>
          <h1>{{ t("settings.title") }}</h1>
        </header>
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
      </aside>
      <div class="settings-main" :class="{ 'settings-main-flush': section === 'tokens' }">
      <TokenUsageChart v-if="section === 'tokens'" />
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
        :title="t('settings.deleteAllBots')"
        :hint="t('settings.deleteAllBotsHint')"
      >
        <template #icon>
          <UiIcon name="trash" :size="18" />
        </template>
        <div class="action-list settings-danger-actions">
          <div class="action-row">
            <button
              class="danger"
              type="button"
              :disabled="deleteAllBusy || !state.bots.length"
              @click="toggleDeleteAll"
            >
              {{
                deleteAllBusy
                  ? t("settings.deletingAllBots")
                  : t("settings.deleteAllBots")
              }}
            </button>
            <span
              v-if="deleteAllArmed"
              class="action-confirm-wrap"
              @pointerenter="deleteAllTip = true"
              @pointerleave="deleteAllTip = false"
              @focusin="deleteAllTip = true"
              @focusout="deleteAllTip = false"
            >
              <button
                class="action-confirm"
                type="button"
                :disabled="deleteAllBusy || !state.bots.length"
                :aria-label="t('confirm.confirmAction')"
                @click="deleteAllBots"
              >
                <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                  <path
                    d="M3.2 8.2 6.4 11.4 12.8 4.6"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>
              <span v-if="deleteAllTip" class="action-confirm-tip" role="tooltip">{{
                t("confirm.confirmAction")
              }}</span>
            </span>
          </div>
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
        <div class="update-panel">
          <div class="settings-field">
            <span>{{ t("update.remoteUrl") }}</span>
            <div class="settings-field-row">
              <input
                v-model="updateRemoteDraft"
                type="url"
                :placeholder="t('update.remoteUrlPlaceholder')"
                :disabled="updateChannelBusy || !updateGit"
                autocomplete="off"
                spellcheck="false"
              />
              <button
                class="btn"
                type="button"
                :disabled="updateChannelBusy || !updateGit || updateRemoteDraft.trim() === updateRemoteSaved"
                @click="saveUpdateRemote"
              >
                {{ t("update.remoteUrlSave") }}
              </button>
            </div>
            <small>{{ t("update.remoteUrlHint") }}</small>
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
            <div v-if="updatePreset === 'custom'" class="settings-field-row update-custom-branch">
              <input
                v-model="updateCustomBranch"
                type="text"
                :placeholder="t('update.customBranchPlaceholder')"
                :disabled="updateChannelBusy || !updateGit"
                :aria-label="t('update.customBranch')"
                autocomplete="off"
                spellcheck="false"
                @keydown.enter.prevent="saveCustomBranch"
              />
              <button
                class="btn primary"
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
          <div class="settings-field">
            <button
              class="btn"
              type="button"
              :disabled="updateChannelBusy || updateForcing || !updateGit"
              @click="forceUpdate"
            >
              {{ updateForcing ? t("update.applying") : t("update.forceApply") }}
            </button>
            <small>{{ t("update.forceHint") }}</small>
          </div>
        </div>
        <pre v-if="updateForceLog.length" class="setup-log">{{ updateForceLog.join("\n") }}</pre>
        <p v-if="!updateGit" class="hint">{{ t("update.noGit") }}</p>
        <p v-if="updateChannelError" class="vault-error">{{ updateChannelError }}</p>
        <p v-if="updateForceError" class="vault-error">{{ updateForceError }}</p>
      </UiCard>

      <UiCard
        v-if="section === 'agent'"
        :title="t('guard.title')"
        :hint="t('guard.hint')"
      >
        <template #icon>
          <UiIcon name="crosshair" :size="18" />
        </template>
        <label class="settings-field settings-inline">
          <span class="settings-inline-copy">
            <span>{{ t("guard.reviewEvery") }}</span>
            <small>{{ t("guard.reviewEveryHint") }}</small>
          </span>
          <input
            v-model.number="guard.reviewEvery"
            type="number"
            min="0"
            max="100000"
            step="1"
            @change="flushGuard"
          />
        </label>
        <label class="settings-field settings-inline">
          <span class="settings-inline-copy">
            <span>{{ t("guard.maxActions") }}</span>
            <small>{{ t("guard.maxActionsHint") }}</small>
          </span>
          <input
            v-model.number="guard.maxActions"
            type="number"
            min="1"
            max="100000"
            step="1"
            @change="flushGuard"
          />
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
        <div class="companion-instance">
          <div>
            <span class="companion-instance-label">{{ t("companion.instanceLabel") }}</span>
            <code class="companion-instance-url">{{ instanceUrl }}</code>
          </div>
          <button class="btn" type="button" @click="copyInstanceUrl">
            {{ instanceCopied ? t("companion.copied") : t("companion.copy") }}
          </button>
        </div>
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
      </UiCard>

      <UiCard
        v-if="section === 'companions'"
        class="companion-download"
        :title="t('companion.downloadTitle')"
        :hint="t('companion.downloadHint')"
      >
        <template #icon>
          <UiIcon name="harddrive" :size="18" />
        </template>
        <p v-if="buildError" class="vault-error">{{ buildError }}</p>
          <template v-if="companionBuild">
            <p class="hint">
              {{ t("companion.version") }} {{ companionBuild.version || "?" }} ·
              {{ t("companion.buildStatus") }} {{ t("companion.state_" + companionBuild.state) }}
            </p>
            <ul class="settings-list">
              <li
                v-for="(a, idx) in companionBuild.artifacts"
                :key="a.target"
                :class="{ 'companion-artifact-with-log': logUnderArtifact(idx) }"
              >
                <div class="companion-artifact-row">
                  <span>
                    <strong>{{ platformLabel(a.platform) }}</strong>
                    <small> · {{ a.target }} · {{ (a.size / 1048576).toFixed(1) }} MB</small>
                  </span>
                  <a class="btn" :href="a.url" download>{{ t("companion.download") }}</a>
                </div>
                <div v-if="logUnderArtifact(idx)" class="companion-build-panel">
                  <p v-for="n in companionNotes" :key="n" class="hint">{{ n }}</p>
                  <p v-if="companionBuild.error" class="vault-error">{{ companionBuild.error }}</p>
                  <pre
                    ref="companionLogEl"
                    class="setup-log companion-build-log"
                  >{{ companionBuild.log.join("\n") }}</pre>
                </div>
              </li>
              <li v-if="sharedBuildLog" class="companion-log-row">
                <div class="companion-build-panel">
                  <p v-for="n in companionNotes" :key="n" class="hint">{{ n }}</p>
                  <p v-if="companionBuild.error" class="vault-error">{{ companionBuild.error }}</p>
                  <pre
                    ref="companionLogEl"
                    class="setup-log companion-build-log"
                  >{{ companionBuild.log.join("\n") }}</pre>
                </div>
              </li>
            </ul>
            <div v-if="companionBuild.toolchain" class="companion-rebuild">
              <button
                class="btn"
                type="button"
                :disabled="companionBuild.state === 'building'"
                @click="rebuildCompanion"
              >
                {{ companionBuild.state === "building" ? t("setup.running") : t("companion.rebuild") }}
              </button>
            </div>
            <ul class="settings-list companion-macos-list">
              <li class="companion-macos-row">
                <div class="companion-macos-top">
                  <span>
                    <strong>macOS</strong>
                    <small> · {{ t("companion.macosMeta") }}</small>
                  </span>
                </div>
                <p class="hint">{{ t("companion.macosHint") }}</p>
                <pre class="companion-cmd">{{ t("companion.macosBuild") }}</pre>
              </li>
            </ul>
            <template v-if="companionBuild.state === 'no_toolchain'">
              <p class="hint justified">{{ t("companion.noToolchain") }}</p>
              <pre class="companion-cmd">{{ companionBuild.rustup_hint }}</pre>
            </template>
          </template>
      </UiCard>

      <UiCard
        v-if="section === 'companions'"
        :title="t('companion.mcpTitle')"
        :hint="t('companion.mcpHint')"
      >
        <template #icon>
          <UiIcon name="puzzle" :size="18" />
        </template>
        <ul class="settings-list">
          <li v-for="item in starterMcps" :key="item.id" :class="{ 'has-steps': item.steps }">
            <div class="companion-mcp-main">
              <div>
                <strong>{{ item.name }}</strong>
                <small>{{ t(item.blurb) }}</small>
              </div>
              <a class="btn" :href="item.url" target="_blank" rel="noopener noreferrer">
                {{ t("companion.mcpOpen") }}
              </a>
            </div>
            <div v-if="item.steps" class="companion-mcp-steps">
              <p class="hint">{{ t(item.steps) }}</p>
              <pre class="companion-cmd">{{ t(item.fields) }}</pre>
            </div>
          </li>
        </ul>
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
import { forgetUpdateStatus } from "../updateStatusCache";
import { setLocale } from "../i18n";
import { botPath } from "../router";
import { currentBotObj, state } from "../store";
import GroundingSettings from "./GroundingSettings.vue";
import LlmSettings from "./LlmSettings.vue";
import LocaleFlag from "./LocaleFlag.vue";
import SecretInput from "./SecretInput.vue";
import TokenUsageChart from "./TokenUsageChart.vue";
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

const SECTIONS = ["agent", "llm", "grounding", "tokens", "vault", "memory", "companions"];
const DEFAULT_TZ = "Europe/Paris";
const tabs = [
  { id: "agent", label: "settings.tabAgent", icon: "terminal" },
  { id: "llm", label: "settings.tabLlm", icon: "spark" },
  { id: "grounding", label: "settings.tabGrounding", icon: "crosshair" },
  { id: "tokens", label: "settings.tabTokens", icon: "chart" },
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
const deleteAllArmed = ref(false);
const deleteAllTip = ref(false);
const deleteAllBusy = ref(false);
const updateChannel = ref("main");
const updateForcing = ref(false);
const updateForceError = ref("");
const updateForceLog = ref([]);
let updateForceJobId = "";
const updateChannelBusy = ref(false);
const updateChannelError = ref("");
const updateGit = ref(true);
const updateCustomBranch = ref("");
const updateRemoteDraft = ref("");
const updateRemoteSaved = ref("");
const updateOriginUrl = ref("");
const updateChoice = ref("");
let updateChannelSaved = "main";

const updatePreset = computed(() => {
  if (updateChoice.value === "custom") return "custom";
  const ch = updateChannel.value;
  if (ch === "main" || ch === "dev") return ch;
  if (ch) return "custom";
  return updateChoice.value || "main";
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

function toggleDeleteAll() {
  if (deleteAllBusy.value || !state.bots.length) return;
  deleteAllArmed.value = !deleteAllArmed.value;
  deleteAllTip.value = false;
}

async function deleteAllBots() {
  if (deleteAllBusy.value || !deleteAllArmed.value) return;
  const names = state.bots.map((b) => b.name);
  if (!names.length) {
    deleteAllArmed.value = false;
    return;
  }
  deleteAllBusy.value = true;
  try {
    for (const name of names) {
      await api.deleteBot(name);
      delete state.messages[name];
      delete state.threadPages[name];
      delete state.previews[name];
    }
    state.currentBot = null;
    deleteAllArmed.value = false;
    router.replace("/");
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    deleteAllBusy.value = false;
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
const companionsEnabled = ref(false);
const instanceCopied = ref(false);
const instanceUrl = computed(() => String(window.location.origin || "").replace(/\/+$/, ""));
const starterMcps = [
  {
    id: "windows",
    name: "Windows-MCP",
    url: "https://github.com/CursorTouch/Windows-MCP",
    blurb: "companion.mcpWindows",
    steps: "companion.mcpWindowsSteps",
    fields: "companion.mcpWindowsFields",
  },
  {
    id: "filesystem",
    name: "Filesystem",
    url: "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
    blurb: "companion.mcpFilesystem",
  },
  {
    id: "git",
    name: "Git",
    url: "https://github.com/modelcontextprotocol/servers/tree/main/src/git",
    blurb: "companion.mcpGit",
  },
  {
    id: "playwright",
    name: "Playwright",
    url: "https://github.com/microsoft/playwright-mcp",
    blurb: "companion.mcpPlaywright",
  },
];
let instanceCopyTimer = 0;
const companionNotes = computed(() =>
  (companionBuild.value?.notes || []).filter((n) => !/^macOS is not built/i.test(String(n || ""))),
);
const hasBuildLog = computed(() => (companionBuild.value?.log || []).length > 0);
/** Log partagé après Linux+Windows (ou pendant un build sans artefact encore). */
const sharedBuildLog = computed(() => hasBuildLog.value && (companionBuild.value?.artifacts || []).length !== 1);
function logUnderArtifact(idx) {
  if (!hasBuildLog.value || sharedBuildLog.value) return false;
  return idx === (companionBuild.value?.artifacts || []).length - 1;
}
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
    companionsEnabled.value = s["companions.enabled"] === true;
  } catch {
    companionsEnabled.value = false;
  }
}

async function copyInstanceUrl() {
  const text = instanceUrl.value;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  instanceCopied.value = true;
  if (instanceCopyTimer) clearTimeout(instanceCopyTimer);
  instanceCopyTimer = window.setTimeout(() => {
    instanceCopied.value = false;
  }, 1600);
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

function updateNetworkDrop(err) {
  const msg = String(err?.message || err || "").toLowerCase();
  return (
    err?.name === "TypeError" ||
    msg.includes("networkerror") ||
    msg.includes("failed to fetch") ||
    msg.includes("load failed") ||
    msg.includes("network request failed")
  );
}

function reloadAfterForcedUpdate() {
  forgetUpdateStatus();
  updateForceError.value = "";
  updateForcing.value = true;
  const note = t("update.restarting");
  if (!updateForceLog.value.includes(note)) {
    updateForceLog.value = [...updateForceLog.value, note];
  }
  const started = Date.now();
  const tick = async () => {
    if (Date.now() - started > 90000) {
      window.location.reload();
      return;
    }
    try {
      const res = await fetch("/api/v1/health", { credentials: "include", cache: "no-store" });
      if (res.ok || res.status === 401 || res.status === 403) {
        window.location.reload();
        return;
      }
    } catch {
      /* still restarting */
    }
    setTimeout(tick, 1500);
  };
  setTimeout(tick, 2000);
}

async function pollForcedUpdate() {
  if (!updateForceJobId) return;
  try {
    const job = await api.getJob(updateForceJobId);
    updateForceLog.value = job.log || [];
    if (job.state === "pending" || job.state === "running") {
      setTimeout(pollForcedUpdate, 1200);
      return;
    }
    if (job.state === "failed") {
      updateForcing.value = false;
      updateForceError.value = job.error || t("update.failed");
      return;
    }
    reloadAfterForcedUpdate();
  } catch (e) {
    if (updateForcing.value || updateNetworkDrop(e)) {
      reloadAfterForcedUpdate();
      return;
    }
    setTimeout(pollForcedUpdate, 2000);
  }
}

async function forceUpdate() {
  if (updateForcing.value || updateChannelBusy.value || !updateGit.value) return;
  updateForceError.value = "";
  updateForceLog.value = [];
  updateForcing.value = true;
  try {
    const job = await api.applyUpdate(true);
    updateForceJobId = job.id;
    updateForceLog.value = job.log || [];
    pollForcedUpdate();
  } catch (e) {
    if (updateNetworkDrop(e)) {
      reloadAfterForcedUpdate();
      return;
    }
    updateForceError.value = e.message || String(e);
    updateForcing.value = false;
  }
}

async function loadUpdateChannel() {
  updateChannelError.value = "";
  try {
    const st = await api.updateStatus(false);
    const ch = String(st.channel || "main").trim() || "main";
    updateChannel.value = ch;
    updateChannelSaved = ch;
    updateChoice.value = "";
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
    forgetUpdateStatus();
    updateChannelSaved = branch;
    updateChoice.value = "";
    if (branch !== "main" && branch !== "dev") {
      updateCustomBranch.value = branch;
    }
  } catch (e) {
    const msg = e.message || String(e);
    updateChannelError.value = /not available on /i.test(msg)
      ? t("update.unknownBranch", { branch })
      : msg;
    updateChannel.value = updateChannelSaved;
    if (branch !== "main" && branch !== "dev") {
      updateChoice.value = "custom";
      updateCustomBranch.value = branch;
    }
  } finally {
    updateChannelBusy.value = false;
  }
}

async function pickUpdateChannel(next) {
  if (next === "custom") {
    updateChoice.value = "custom";
    if (
      !updateCustomBranch.value.trim() &&
      updateChannelSaved !== "main" &&
      updateChannelSaved !== "dev"
    ) {
      updateCustomBranch.value = updateChannelSaved;
    }
    return;
  }
  updateChoice.value = "";
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
    forgetUpdateStatus();
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
