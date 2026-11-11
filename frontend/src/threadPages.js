/** Latest chat page first; older pages only when the reader scrolls up. */

import { api } from "./api";
import {
  isOptimisticMessageId,
  preferLiveStreamingMessage,
  state,
} from "./store";

export const THREAD_PAGE = 80;

const latestSeq = new Map();

function pageState(name) {
  if (!state.threadPages[name]) {
    state.threadPages[name] = {
      before: null,
      hasMore: false,
      boot: false,
      paged: false,
      older: false,
    };
  }
  return state.threadPages[name];
}

function mergeMessages(name, incoming) {
  const local = state.messages[name] || [];
  const byId = new Map();
  for (const m of local) {
    if (m?.id) byId.set(m.id, m);
  }
  for (const m of incoming || []) {
    if (!m?.id) continue;
    const prev = byId.get(m.id);
    byId.set(m.id, prev ? preferLiveStreamingMessage(prev, m) : m);
  }
  for (const m of local) {
    if (!m?.id || !isOptimisticMessageId(m.id)) continue;
    const echoed = (incoming || []).some(
      (r) =>
        r.role === m.role &&
        String(r.content || "") === String(m.content || ""),
    );
    if (echoed) byId.delete(m.id);
  }
  state.messages[name] = [...byId.values()].sort((a, b) =>
    String(a.created_at || "").localeCompare(String(b.created_at || "")),
  );
}

export function threadBooting(name) {
  return !!state.threadPages[name]?.boot;
}

export function threadHasMore(name) {
  return !!state.threadPages[name]?.hasMore;
}

/** Newest page. Keeps older rows already pulled in by scrolling up. */
export async function loadLatestMessages(name) {
  if (!name) return;
  const seq = (latestSeq.get(name) || 0) + 1;
  latestSeq.set(name, seq);
  const page = pageState(name);
  if (!(state.messages[name] || []).length) page.boot = true;
  try {
    const remote = await api.listMessagePage(name, { limit: THREAD_PAGE });
    if (latestSeq.get(name) !== seq) return;
    mergeMessages(name, remote);
    if (!page.paged) {
      page.hasMore = remote.length >= THREAD_PAGE;
      page.before = remote[0]?.created_at || null;
    }
    const last = [...remote].reverse().find((m) => !m?.meta?.hidden_prompt);
    if (last) {
      state.previews[name] = String(last.content || "")
        .replace(/\s+/g, " ")
        .trim();
    }
  } catch {
    /* ChatPane stays on what it already has. */
  } finally {
    if (latestSeq.get(name) === seq) page.boot = false;
  }
}

/** One older page. Returns false when nothing new was added. */
export async function loadOlderMessages(name) {
  const page = state.threadPages[name];
  if (!name || !page?.hasMore || page.older || !page.before) return false;
  page.older = true;
  page.paged = true;
  try {
    const remote = await api.listMessagePage(name, {
      before: page.before,
      limit: THREAD_PAGE,
    });
    if (!remote.length) {
      page.hasMore = false;
      return false;
    }
    const known = new Set((state.messages[name] || []).map((m) => m.id));
    const fresh = remote.filter((m) => m?.id && !known.has(m.id));
    if (!fresh.length) {
      page.hasMore = false;
      return false;
    }
    mergeMessages(name, fresh);
    page.before = remote[0]?.created_at || page.before;
    page.hasMore = remote.length >= THREAD_PAGE;
    return true;
  } catch {
    return false;
  } finally {
    page.older = false;
  }
}

/** Search jump: walk older pages until this id is in memory, or history ends. */
export async function ensureMessageLoaded(name, messageId) {
  if (!name || !messageId) return false;
  await loadLatestMessages(name);
  for (let i = 0; i < 50; i++) {
    if ((state.messages[name] || []).some((m) => m.id === messageId)) return true;
    const more = await loadOlderMessages(name);
    if (!more) return false;
  }
  return false;
}
