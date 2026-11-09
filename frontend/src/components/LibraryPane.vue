<template>
  <div
    class="library"
    :class="{ 'is-drag': dragging }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <div class="files-head">
      <nav class="files-crumb" aria-label="shared">
        <button
          type="button"
          class="crumb root"
          :class="{ active: path === '.' }"
          title="~/shared"
          aria-label="~/shared"
          @click="goRoot"
        >
          <svg class="fi" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3.5 9.5V7.2A1.7 1.7 0 0 1 5.2 5.5h4.1l1.6 1.7h7.9A1.7 1.7 0 0 1 20.5 9v1" />
            <path d="M3.5 10.2h17l-1.2 7.3a1.7 1.7 0 0 1-1.7 1.4H6.4a1.7 1.7 0 0 1-1.7-1.4L3.5 10.2Z" />
          </svg>
        </button>
        <template v-for="(seg, i) in crumbs" :key="seg.path">
          <span class="crumb-sep" aria-hidden="true">/</span>
          <button
            type="button"
            class="crumb"
            :class="{ active: i === crumbs.length - 1 }"
            @click="goPath(seg.path)"
          >
            {{ seg.name }}
          </button>
        </template>
      </nav>
      <div class="files-actions">
        <button
          class="btn file-action icon-only"
          type="button"
          :disabled="busy"
          :title="t('files.mkdir')"
          :aria-label="t('files.mkdir')"
          @click="startMkdir"
        >
          <svg class="fi" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3.5 9.2V7.1A1.6 1.6 0 0 1 5.1 5.5h4l1.5 1.6h8.3A1.6 1.6 0 0 1 20.5 8.7v1" />
            <path d="M3.5 10h17l-1.1 7.2a1.6 1.6 0 0 1-1.6 1.3H6.2a1.6 1.6 0 0 1-1.6-1.3L3.5 10Z" />
            <path d="M12 12.2v5M9.5 14.7h5" />
          </svg>
        </button>
        <button
          class="btn file-action icon-only"
          type="button"
          :disabled="busy"
          :title="uploading ? t('files.uploading') : t('files.upload')"
          :aria-label="uploading ? t('files.uploading') : t('files.upload')"
          @click="pickFiles"
        >
          <svg class="fi" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 15.5V5.5M8.5 9 12 5.5 15.5 9" />
            <path d="M5 16.5v1.3A1.7 1.7 0 0 0 6.7 19.5h10.6a1.7 1.7 0 0 0 1.7-1.7v-1.3" />
          </svg>
        </button>
        <input
          ref="fileInput"
          type="file"
          multiple
          hidden
          @change="onFileInput"
        />
      </div>
    </div>

    <form v-if="mkdirOpen" class="mkdir-form" @submit.prevent="submitMkdir">
      <svg class="fi mkdir-ico" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3.5 9.2V7.1A1.6 1.6 0 0 1 5.1 5.5h4l1.5 1.6h8.3A1.6 1.6 0 0 1 20.5 8.7v1" />
        <path d="M3.5 10h17l-1.1 7.2a1.6 1.6 0 0 1-1.6 1.3H6.2a1.6 1.6 0 0 1-1.6-1.3L3.5 10Z" />
      </svg>
      <input
        ref="mkdirInput"
        v-model="mkdirName"
        type="text"
        :placeholder="t('files.mkdirPrompt')"
        autocomplete="off"
        spellcheck="false"
        :disabled="uploading"
        @keydown.esc.prevent="cancelMkdir"
      />
      <button class="btn primary" type="submit" :disabled="uploading || !mkdirName.trim()">
        {{ t("ok") }}
      </button>
      <button class="btn" type="button" :disabled="uploading" @click="cancelMkdir">
        {{ t("files.cancel") }}
      </button>
    </form>

    <p class="files-hint">{{ t("files.sharedHint") }}</p>
    <p v-if="error" class="files-error">{{ error }}</p>

    <div v-if="loading" class="hint">…</div>
    <div v-else-if="!entries.length" class="hint files-empty">
      <svg class="fi empty-ico" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3.5 9.5V7.2A1.7 1.7 0 0 1 5.2 5.5h4.1l1.6 1.7h7.9A1.7 1.7 0 0 1 20.5 9v1" />
        <path d="M3.5 10.2h17l-1.2 7.3a1.7 1.7 0 0 1-1.7 1.4H6.4a1.7 1.7 0 0 1-1.7-1.4L3.5 10.2Z" />
      </svg>
      <span>{{ t("files.empty") }}</span>
    </div>
    <ul v-else class="file-list">
      <li v-if="path !== '.'" class="file-row">
        <button class="file-name" type="button" @click="goUp">
          <span class="file-ico is-up" aria-hidden="true">
            <svg class="fi" viewBox="0 0 24 24">
              <path d="M12 18V7M8 10.5 12 6.5 16 10.5" />
            </svg>
          </span>
          <span class="file-label">..</span>
        </button>
      </li>
      <li v-for="e in entries" :key="e.path" class="file-row">
        <button class="file-name" type="button" :title="e.name" @click="open(e)">
          <span class="file-ico" :class="e.is_dir ? 'is-dir' : 'is-file'" aria-hidden="true">
            <svg v-if="e.is_dir" class="fi" viewBox="0 0 24 24">
              <path d="M3.5 9.5V7.2A1.7 1.7 0 0 1 5.2 5.5h4.1l1.6 1.7h7.9A1.7 1.7 0 0 1 20.5 9v1" />
              <path d="M3.5 10.2h17l-1.2 7.3a1.7 1.7 0 0 1-1.7 1.4H6.4a1.7 1.7 0 0 1-1.7-1.4L3.5 10.2Z" />
            </svg>
            <svg v-else class="fi" viewBox="0 0 24 24">
              <path d="M7 3.5h6.2L17.5 8v12.5a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" />
              <path d="M13 3.5V8h4.5" />
            </svg>
          </span>
          <span class="file-label">{{ e.name }}</span>
          <span v-if="!e.is_dir && e.size != null" class="file-size">{{ formatSize(e.size) }}</span>
        </button>
        <div class="file-ops">
          <a
            v-if="!e.is_dir"
            class="file-icon-btn"
            :href="api.downloadUrl(bot.name, e.path)"
            target="_blank"
            rel="noopener"
            :title="t('files.download')"
            :aria-label="t('files.download')"
          >
            <svg class="fi" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 5v10M8.5 11.5 12 15l3.5-3.5" />
              <path d="M5 17.5v1.3A1.7 1.7 0 0 0 6.7 20.5h10.6a1.7 1.7 0 0 0 1.7-1.7v-1.3" />
            </svg>
          </a>
          <button
            class="file-icon-btn danger"
            type="button"
            :title="t('files.delete')"
            :aria-label="t('files.delete')"
            @click="remove(e)"
          >
            <svg class="fi" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 7.5h14" />
              <path d="M9.5 7.5V5.8A1.3 1.3 0 0 1 10.8 4.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
              <path d="M8 7.5l.7 11a1.4 1.4 0 0 0 1.4 1.3h4.8a1.4 1.4 0 0 0 1.4-1.3l.7-11" />
            </svg>
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { state } from "../store";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();
const path = ref(".");
const entries = ref([]);
const loading = ref(false);
const uploading = ref(false);
const busy = computed(() => loading.value || uploading.value);
const dragging = ref(false);
const error = ref("");
const fileInput = ref(null);
const mkdirOpen = ref(false);
const mkdirName = ref("");
const mkdirInput = ref(null);
let dragDepth = 0;
let pollTimer = 0;
let reloadTimer = 0;
let loadGen = 0;

const crumbs = computed(() => {
  if (!path.value || path.value === ".") return [];
  const parts = path.value.split("/").filter(Boolean);
  const out = [];
  let acc = "";
  for (const name of parts) {
    acc = acc ? `${acc}/${name}` : name;
    out.push({ name, path: acc });
  }
  return out;
});

function formatSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function load({ quiet = false } = {}) {
  const gen = ++loadGen;
  if (!quiet) {
    loading.value = true;
    error.value = "";
  }
  try {
    const next = await api.listFiles(props.bot.name, path.value);
    if (gen !== loadGen) return;
    entries.value = next;
  } catch (e) {
    if (gen !== loadGen) return;
    if (!quiet) {
      entries.value = [];
      error.value = e.message || String(e);
    }
  } finally {
    if (!quiet && gen === loadGen) loading.value = false;
  }
}

/** Debounce live refreshes (SSE bursts / polling) so the list does not thrash. */
function scheduleReload() {
  clearTimeout(reloadTimer);
  reloadTimer = window.setTimeout(() => {
    load({ quiet: true });
  }, 250);
}

function open(e) {
  if (e.is_dir) {
    path.value = e.path;
    load();
  }
}

function goRoot() {
  path.value = ".";
  load();
}

function goPath(p) {
  path.value = p || ".";
  load();
}

function goUp() {
  if (path.value === "." || !path.value.includes("/")) path.value = ".";
  else path.value = path.value.split("/").slice(0, -1).join("/") || ".";
  load();
}

async function remove(e) {
  error.value = "";
  try {
    await api.deleteFile(props.bot.name, e.path);
    await load();
  } catch (err) {
    error.value = err.message || String(err);
  }
}

async function startMkdir() {
  mkdirOpen.value = true;
  mkdirName.value = "";
  await nextTick();
  mkdirInput.value?.focus();
}

function cancelMkdir() {
  mkdirOpen.value = false;
  mkdirName.value = "";
}

async function submitMkdir() {
  const name = mkdirName.value.trim();
  if (!name) return;
  uploading.value = true;
  error.value = "";
  try {
    await api.mkdir(props.bot.name, path.value, name);
    cancelMkdir();
    await load();
  } catch (err) {
    error.value = err.message || String(err);
  } finally {
    uploading.value = false;
  }
}

function pickFiles() {
  fileInput.value?.click();
}

async function onFileInput(ev) {
  const files = [...(ev.target.files || [])];
  ev.target.value = "";
  if (files.length) await uploadFiles(files);
}

function onDragEnter() {
  dragDepth += 1;
  dragging.value = true;
}

function onDragOver() {
  dragging.value = true;
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dragging.value = false;
}

async function onDrop(ev) {
  dragDepth = 0;
  dragging.value = false;
  const files = [...(ev.dataTransfer?.files || [])];
  if (files.length) await uploadFiles(files);
}

async function uploadFiles(files) {
  uploading.value = true;
  error.value = "";
  try {
    for (const file of files) {
      await api.uploadFile(props.bot.name, path.value, file);
    }
    await load();
  } catch (err) {
    error.value = err.message || String(err);
  } finally {
    uploading.value = false;
  }
}

watch(
  () => props.bot.name,
  () => {
    path.value = ".";
    cancelMkdir();
    load();
  }
);

watch(
  () => state.filesFeed,
  (feed) => {
    if (!feed || feed.bot !== props.bot.name) return;
    scheduleReload();
  }
);

onMounted(() => {
  load();
  // Shell / VM writes bypass files_* — poll gently while the tab is open.
  pollTimer = window.setInterval(() => {
    if (document.hidden) return;
    load({ quiet: true });
  }, 4000);
});

onUnmounted(() => {
  clearInterval(pollTimer);
  clearTimeout(reloadTimer);
  loadGen += 1;
});
</script>
