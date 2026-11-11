<template>
  <div
    class="library"
    :class="{ 'is-drag': panelDragging }"
    @dragenter.prevent="onPanelDragEnter"
    @dragover.prevent="onPanelDragOver"
    @dragleave.prevent="onPanelDragLeave"
    @drop.prevent="onDropAt(path, $event)"
  >
    <div class="files-head">
      <nav class="files-crumb" aria-label="shared">
        <button
          type="button"
          class="crumb root"
          :class="{
            active: path === '.',
            'drop-over': dropOver === '.',
          }"
          title="~/shared"
          aria-label="~/shared"
          @click="goRoot"
          @dragenter.prevent.stop="onTargetEnter('.')"
          @dragover.prevent.stop="onTargetOver('.')"
          @dragleave.prevent.stop="onTargetLeave('.')"
          @drop.prevent.stop="onDropAt('.', $event)"
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
            :class="{
              active: i === crumbs.length - 1,
              'drop-over': dropOver === seg.path,
            }"
            :title="seg.name"
            @click="goPath(seg.path)"
            @dragenter.prevent.stop="onTargetEnter(seg.path)"
            @dragover.prevent.stop="onTargetOver(seg.path)"
            @dragleave.prevent.stop="onTargetLeave(seg.path)"
            @drop.prevent.stop="onDropAt(seg.path, $event)"
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
      <li
        v-if="path !== '.'"
        class="file-row"
        :class="{ 'drop-over': dropOver === parentPath }"
        @dragenter.prevent.stop="onTargetEnter(parentPath)"
        @dragover.prevent.stop="onTargetOver(parentPath)"
        @dragleave.prevent.stop="onTargetLeave(parentPath)"
        @drop.prevent.stop="onDropAt(parentPath, $event)"
      >
        <button class="file-name" type="button" @click="goUp">
          <span class="file-ico is-up" aria-hidden="true">
            <svg class="fi" viewBox="0 0 24 24">
              <path d="M12 18V7M8 10.5 12 6.5 16 10.5" />
            </svg>
          </span>
          <span class="file-label">..</span>
        </button>
      </li>
      <li
        v-for="e in entries"
        :key="e.path"
        class="file-row"
        :class="{
          'drop-over': dropOver === e.path,
          dragging: dragSrc === e.path,
        }"
        :draggable="true"
        @dragstart="onEntryDragStart(e, $event)"
        @dragend="onEntryDragEnd"
        @dragenter.prevent.stop="onRowDragEnter(e, $event)"
        @dragover.prevent.stop="onRowDragOver(e, $event)"
        @dragleave.prevent.stop="onTargetLeave(e.path)"
        @drop.prevent.stop="onRowDrop(e, $event)"
      >
        <button
          class="file-name"
          type="button"
          :class="{ 'tip-open': nameTip === e.path }"
          :aria-label="fileTitle(e)"
          @click="open(e)"
          @pointerenter="nameTip = e.path"
          @pointerleave="nameTip = ''"
          @focus="nameTip = e.path"
          @blur="nameTip = ''"
        >
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
          <span
            v-if="nameTip === e.path"
            class="file-row-tip"
            role="tooltip"
          >{{ e.name }}</span>
        </button>
        <span
          v-if="e.size != null"
          class="file-size"
        >{{ formatSize(e.size) }}</span>
        <div class="file-ops">
          <span
            v-if="armedDelete === e.path"
            class="action-confirm-wrap"
            @pointerenter="deleteTip = e.path"
            @pointerleave="deleteTip = ''"
            @focusin="deleteTip = e.path"
            @focusout="deleteTip = ''"
          >
            <button
              class="action-confirm file-icon-btn"
              type="button"
              :disabled="busy"
              :aria-label="t('confirm.confirmAction')"
              @click="confirmDelete(e)"
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
            <span
              v-if="deleteTip === e.path"
              class="action-confirm-tip"
              role="tooltip"
            >{{ t("confirm.confirmAction") }}</span>
          </span>
          <button
            class="file-icon-btn danger"
            type="button"
            :title="t('files.delete')"
            :aria-label="t('files.delete')"
            :disabled="busy"
            @click="armDelete(e)"
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

const INTERNAL_MIME = "application/x-autonomous-file";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();
const path = ref(".");
const entries = ref([]);
const loading = ref(false);
const uploading = ref(false);
const busy = computed(() => loading.value || uploading.value);
const panelDragging = ref(false);
const dropOver = ref("");
const dragSrc = ref("");
const error = ref("");
const fileInput = ref(null);
const mkdirOpen = ref(false);
const mkdirName = ref("");
const mkdirInput = ref(null);
const armedDelete = ref("");
const deleteTip = ref("");
/** Custom hover tip (full name) — never browser ``title``. */
const nameTip = ref("");
let dragDepth = 0;
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

const parentPath = computed(() => {
  if (path.value === "." || !path.value.includes("/")) return ".";
  return path.value.split("/").slice(0, -1).join("/") || ".";
});

function formatSize(n) {
  const bytes = Number(n);
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fileTitle(e) {
  const name = String(e?.name || "");
  if (e?.size == null) return name;
  const size = formatSize(e.size);
  return size ? `${name} — ${size}` : name;
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

/** Debounce live refreshes (SSE bursts) so the list does not thrash. */
function scheduleReload() {
  clearTimeout(reloadTimer);
  reloadTimer = window.setTimeout(() => {
    load({ quiet: true });
  }, 250);
}

function download(e) {
  const url = api.downloadUrl(props.bot.name, e.path);
  const a = document.createElement("a");
  a.href = url;
  a.download = e.name || "";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function clearTips() {
  armedDelete.value = "";
  deleteTip.value = "";
  nameTip.value = "";
}

function open(e) {
  clearTips();
  if (e.is_dir) {
    path.value = e.path;
    load();
    return;
  }
  download(e);
}

function goRoot() {
  path.value = ".";
  clearTips();
  load();
}

function goPath(p) {
  path.value = p || ".";
  clearTips();
  load();
}

function goUp() {
  path.value = parentPath.value;
  clearTips();
  load();
}

function armDelete(e) {
  armedDelete.value = armedDelete.value === e.path ? "" : e.path;
  deleteTip.value = "";
}

async function confirmDelete(e) {
  if (armedDelete.value !== e.path) return;
  error.value = "";
  uploading.value = true;
  try {
    await api.deleteFile(props.bot.name, e.path);
    armedDelete.value = "";
    deleteTip.value = "";
    await load();
  } catch (err) {
    error.value = err.message || String(err);
  } finally {
    uploading.value = false;
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
  if (files.length) await uploadFiles(path.value, files);
}

function onPanelDragEnter() {
  dragDepth += 1;
  panelDragging.value = true;
}

function onPanelDragOver() {
  panelDragging.value = true;
}

function onPanelDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) {
    panelDragging.value = false;
    dropOver.value = "";
  }
}

function onTargetEnter(target) {
  dropOver.value = target;
  panelDragging.value = true;
}

function onTargetOver(target) {
  dropOver.value = target;
  panelDragging.value = true;
}

function onTargetLeave(target) {
  if (dropOver.value === target) dropOver.value = "";
}

function onEntryDragStart(e, ev) {
  dragSrc.value = e.path;
  armedDelete.value = "";
  try {
    ev.dataTransfer.setData(INTERNAL_MIME, e.path);
    ev.dataTransfer.setData("text/plain", e.path);
    ev.dataTransfer.effectAllowed = "move";
  } catch {
    /* some browsers reject custom types until drop */
  }
}

function onEntryDragEnd() {
  dragSrc.value = "";
  dropOver.value = "";
  panelDragging.value = false;
  dragDepth = 0;
}

function parentOf(p) {
  if (!p || p === ".") return ".";
  if (!p.includes("/")) return ".";
  return p.split("/").slice(0, -1).join("/") || ".";
}

function isInvalidMove(src, destDir) {
  if (!src) return true;
  if (src === destDir) return true;
  if (parentOf(src) === (destDir || ".")) return true;
  if (destDir && destDir !== "." && (destDir === src || destDir.startsWith(`${src}/`))) {
    return true;
  }
  return false;
}

function readDropPayload(ev) {
  // Snapshot before any await — DataTransfer is cleared after the drop handler yields.
  const files = [...(ev?.dataTransfer?.files || [])].filter(
    (f) => f && (f.size > 0 || String(f.name || "").trim())
  );
  let internal = "";
  try {
    internal = ev?.dataTransfer?.getData(INTERNAL_MIME) || "";
  } catch {
    internal = "";
  }
  if (!internal && dragSrc.value && !files.length) internal = dragSrc.value;
  return { files, internal };
}

function onRowDragEnter(e, _ev) {
  onTargetEnter(e.is_dir ? e.path : path.value);
}

function onRowDragOver(e, _ev) {
  onTargetOver(e.is_dir ? e.path : path.value);
}

function onRowDrop(e, ev) {
  // OS files on a file row → upload into the current folder (not swallowed).
  // Internal drag onto a folder → move; onto a file → ignore.
  const { files, internal } = readDropPayload(ev);
  if (internal) {
    if (e.is_dir) return onDropAt(e.path, ev, { files, internal });
    dragSrc.value = "";
    dropOver.value = "";
    panelDragging.value = false;
    return;
  }
  if (files.length) {
    return onDropAt(e.is_dir ? e.path : path.value, ev, { files, internal: "" });
  }
}

async function onDropAt(destDir, ev, prefetched = null) {
  dragDepth = 0;
  panelDragging.value = false;
  dropOver.value = "";
  const dest = destDir || ".";
  const { files, internal } = prefetched || readDropPayload(ev);
  dragSrc.value = "";
  if (internal) {
    if (isInvalidMove(internal, dest)) return;
    error.value = "";
    uploading.value = true;
    try {
      await api.moveFile(props.bot.name, internal, dest);
      await load();
    } catch (err) {
      error.value = err.message || String(err);
    } finally {
      uploading.value = false;
    }
    return;
  }
  if (files.length) await uploadFiles(dest, files);
}

async function uploadFiles(destDir, files) {
  uploading.value = true;
  error.value = "";
  try {
    for (const file of files) {
      await api.uploadFile(props.bot.name, destDir || ".", file);
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
    clearTips();
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
});

onUnmounted(() => {
  clearTimeout(reloadTimer);
  loadGen += 1;
});
</script>
