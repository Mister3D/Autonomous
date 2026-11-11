<template>
  <div
    class="chat-pane"
    :class="{ 'drag-over': dragDepth > 0 }"
    @click="onChatClick"
    @dragenter.prevent="onDragEnter"
    @dragleave.prevent="onDragLeave"
    @dragover.prevent="onDragOver"
    @drop.prevent="onDrop"
  >
    <div v-if="dragDepth > 0" class="chat-drop-overlay" aria-hidden="true">
      <span>{{ t("chat.dropFiles") }}</span>
    </div>
    <div
      v-if="lightboxSrc"
      class="img-lightbox"
      role="dialog"
      :aria-label="t('chat.imageLightbox')"
      @click="closeLightbox"
      @keydown.esc.prevent="closeLightbox"
    >
      <button type="button" class="img-lightbox-close" :aria-label="t('chat.closeLightbox')" @click="closeLightbox">
        ×
      </button>
      <img :src="lightboxSrc" :alt="lightboxAlt" @click.stop />
    </div>
    <input
      ref="fileInput"
      type="file"
      class="chat-file-input"
      multiple
      @change="onFilePicked"
    />
    <div
      v-if="tokenStats.visible"
      class="chat-token-usage"
      :class="{ 'tip-open': tokenTipOpen }"
      tabindex="0"
      @pointerenter="tokenTipOpen = true"
      @pointerleave="tokenTipOpen = false"
      @focus="tokenTipOpen = true"
      @blur="tokenTipOpen = false"
    >
      <span class="tok in">↑ {{ tokenStats.inLabel }}</span>
      <span class="tok sep" aria-hidden="true">·</span>
      <span class="tok out">↓ {{ tokenStats.outLabel }}</span>
      <span v-if="tokenTipOpen" class="chat-token-tip" role="tooltip">
        {{ tokenStats.tip }}
      </span>
    </div>
    <div class="chat-surface">
    <div
      class="messages"
      :class="{ 'messages-placing': !threadPlaced }"
      ref="scroller"
      @scroll.passive="onMessagesScroll"
    >
      <p v-if="historyBooting && !hasHistory" class="empty">{{ t("chat.loading") }}</p>
      <p v-else-if="showEmpty" class="empty">{{ t("chat.empty") }}</p>
      <template v-for="item in thread" :key="item.id">
        <div v-if="item.kind === 'day'" class="day-sep">{{ item.label }}</div>
        <div v-else-if="item.kind === 'new'" class="new-sep">
          <span>{{ t("chat.new") }}</span>
        </div>
        <template v-else-if="item.kind === 'live'">
          <article v-if="deskCreating" class="msg assistant thinking" aria-live="polite">
            <div class="thinking-row waiting">
              <span class="thinking-label">{{ t("desk.creating") }}</span>
            </div>
          </article>
          <article v-else-if="waitingHuman" class="msg assistant thinking" aria-live="polite">
            <div class="thinking-row waiting">
              <span class="thinking-label">{{ t("chat.waitingHuman") }}</span>
            </div>
          </article>
          <article v-else-if="showAgentOrb" class="msg assistant thinking" aria-live="polite">
            <div class="thinking-row">
              <WorkingOrb state="working" :size="22" :label="t('chat.working')" />
              <span class="thinking-label">{{ t("chat.working") }}</span>
              <button
                type="button"
                class="agent-stop-btn"
                :aria-label="t('chat.stop')"
                :title="t('chat.stopHint')"
                @click="stop"
              >
                {{ t("chat.stop") }}
              </button>
            </div>
          </article>
        </template>
        <article v-else-if="item.kind === 'tools'" class="msg tool" :data-msg-id="item.id">
          <ToolGroup :entries="item.entries" :sealed="item.sealed" :bot="bot.name" />
        </article>
        <article v-else-if="item.kind === 'notice'" class="msg notice" :data-msg-id="item.message.id">
          <div class="notice-card" :class="item.message.meta?.status">
            <div class="notice-dir">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M6 9.5a6 6 0 0 1 12 0c0 4 1.4 5.2 1.8 5.6H4.2C4.6 14.7 6 13.5 6 9.5Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linejoin="round"
                />
                <path
                  d="M10 18.2a2 2 0 0 0 4 0"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linecap="round"
                />
              </svg>
              <span>{{ t("chat.notifyLabel") }}</span>
            </div>
            <p v-if="notifyTitle(item.message)" class="notice-title">{{ notifyTitle(item.message) }}</p>
            <p v-if="notifyBody(item.message)" class="notice-body">{{ notifyBody(item.message) }}</p>
            <p v-if="item.message.meta?.status === 'error'" class="notice-error">
              {{ t("chat.notifyFailed") }}
            </p>
          </div>
        </article>
        <article v-else-if="item.kind === 'guard'" class="msg guard" :data-msg-id="item.id">
          <div class="guard-card" :class="item.tone">
            <span class="guard-ico" aria-hidden="true">{{ item.icon }}</span>
            <span class="guard-title">{{ item.text }}</span>
            <time
              v-if="item.time"
              class="guard-time"
              :datetime="item.iso"
            >{{ item.time }}</time>
          </div>
        </article>
        <article v-else-if="item.kind === 'secret_leak'" class="msg secret-leak" :data-msg-id="item.id">
          <div class="secret-leak-card">
            <span class="secret-leak-ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="5" y="11" width="14" height="10" rx="2" />
                <path d="M8 11V8a4 4 0 0 1 8 0v3" />
              </svg>
            </span>
            <span class="secret-leak-title">{{ item.text }}</span>
            <time
              v-if="item.time"
              class="secret-leak-time"
              :datetime="item.iso"
            >{{ item.time }}</time>
          </div>
        </article>
        <article v-else-if="item.kind === 'agent_error'" class="msg agent-error" :data-msg-id="item.id">
          <div class="agent-error-card">
            <span class="agent-error-ico" aria-hidden="true">⚠️</span>
            <span class="agent-error-title">{{ item.text }}</span>
            <time
              v-if="item.time"
              class="agent-error-time"
              :datetime="item.iso"
            >{{ item.time }}</time>
          </div>
        </article>
        <article v-else-if="item.kind === 'vault'" class="msg vault" :data-msg-id="item.message.id">
          <VaultRequestCard :message="item.message" />
        </article>
        <article v-else-if="item.kind === 'memory'" class="msg memory" :data-msg-id="item.message.id">
          <MemoryProposalCard :message="item.message" />
        </article>
        <article v-else-if="item.kind === 'approval'" class="msg approval" :data-msg-id="item.message.id">
          <ApprovalCard :message="item.message" />
        </article>
        <article v-else-if="item.kind === 'bot_delete'" class="msg bot-delete" :data-msg-id="item.message.id">
          <BotDeleteCard :message="item.message" :bot-name="bot.name" />
        </article>
        <article v-else-if="item.kind === 'clarify'" class="msg clarify" :data-msg-id="item.message.id">
          <ClarifyCard :message="item.message" />
        </article>
        <article v-else-if="item.kind === 'desk'" class="msg desk-req" :data-msg-id="item.message.id">
          <DeskRequestCard :message="item.message" />
        </article>
        <article v-else-if="item.kind === 'resume'" class="msg agent-resume" :data-msg-id="item.message.id">
          <AgentResumeCard :message="item.message" />
        </article>
        <article v-else-if="item.kind === 'screenshot'" class="msg screenshot" :data-msg-id="item.message.id">
          <figure class="shot-card">
            <img
              :src="item.message.meta?.url"
              :alt="item.message.content || t('chat.screenshot')"
              loading="lazy"
            />
            <figcaption v-if="item.message.content">{{ item.message.content }}</figcaption>
          </figure>
        </article>
        <article
          v-else
          class="msg"
          :class="[
            item.message.role,
            {
              'msg-flash': flashMsgId === item.message.id,
              event: isEventTrigger(item.message),
              botmail: !!botmailDirection(item.message),
              sent: botmailDirection(item.message) === 'sent',
              received: botmailDirection(item.message) === 'received',
            },
          ]"
          :data-msg-id="item.message.id"
          :data-queued="item.message.meta?.queued ? '1' : undefined"
        >
          <p v-if="sourceOf(item.message)" class="msg-source">
            {{ t("chat.from") }}
            <span class="src-pip" :style="{ background: avatarColor(sourceOf(item.message)) }" />
            {{ sourceOf(item.message) }}
          </p>
          <div class="msg-row" :class="[item.message.role, { event: isEventTrigger(item.message) }]">
            <div
              v-if="item.message.role === 'user' && item.message.meta?.queued"
              class="msg-time msg-queued-meta"
            >
              <span class="msg-queued-label">{{ t("chat.queued") }}</span>
              <button
                type="button"
                class="msg-queued-cancel"
                :title="t('chat.queuedCancel')"
                :aria-label="t('chat.queuedCancel')"
                @click.stop="cancelQueued(item.message)"
              >
                {{ t("chat.queuedCancel") }}
              </button>
            </div>
            <time
              v-else-if="item.message.role === 'user' && msgStamp(item.message).time"
              class="msg-time"
              :datetime="item.message.created_at"
            >
              <span v-if="msgStamp(item.message).date" class="msg-time-date">{{
                msgStamp(item.message).date
              }}</span>
              <span class="msg-time-clock">{{ msgStamp(item.message).time }}</span>
            </time>
            <div class="msg-stack" :class="[item.message.role, { event: isEventTrigger(item.message) }]">
              <div
                v-if="thumbAtts(item.message).length"
                class="bubble-atts images"
                :class="{ many: thumbAtts(item.message).length > 1 }"
              >
                <a
                  v-for="(att, i) in thumbAtts(item.message)"
                  :key="`${item.id}-thumb-${i}`"
                  class="bubble-thumb"
                  :href="thumbHref(att)"
                  :download="isFileAtt(att) ? fileAttName(att) : undefined"
                  target="_blank"
                  rel="noopener"
                  @click.stop
                >
                  <img
                    :src="thumbSrc(att)"
                    :alt="isFileAtt(att) ? fileAttName(att) : t('chat.pastedImage')"
                    loading="lazy"
                  />
                </a>
              </div>
              <div
                v-if="docAtts(item.message).length"
                class="bubble-atts files"
              >
                <a
                  v-for="(att, i) in docAtts(item.message)"
                  :key="`${item.id}-file-${i}`"
                  class="bubble-file"
                  :class="fileKindClass(att)"
                  :href="fileAttUrl(att)"
                  :download="fileAttName(att)"
                  target="_blank"
                  rel="noopener"
                  @click.stop
                >
                  <span class="bubble-file-ico" aria-hidden="true" v-html="fileKindIcon(att)" />
                  <span class="bubble-file-meta">
                    <span class="bubble-file-name">{{ fileAttName(att) }}</span>
                    <span class="bubble-file-kind">{{ fileKindLabel(att) }}</span>
                  </span>
                </a>
              </div>
              <div
                v-if="showBubbleShell(item.message)"
                class="bubble"
                :class="[
                  item.message.role,
                  {
                    streaming: item.message.meta?.streaming,
                    queued: item.message.meta?.queued,
                    'secret-scrubbed': item.message.meta?.secret_scrubbed,
                    event: isEventTrigger(item.message),
                    botmail: !!botmailDirection(item.message),
                    sent: botmailDirection(item.message) === 'sent',
                    received: botmailDirection(item.message) === 'received',
                    'botmail-open':
                      !!botmailDirection(item.message) &&
                      isBotmailExpanded(item.message),
                    'botmail-collapsible':
                      !!botmailDirection(item.message) &&
                      botmailCollapsible(item.message),
                  },
                ]"
                :title="bubbleTitle(item.message)"
                :aria-expanded="
                  botmailCollapsible(item.message)
                    ? isBotmailExpanded(item.message)
                    : undefined
                "
                @click="onMessageBubbleClick(item.message, $event)"
              >
                <div
                  v-if="botmailDirection(item.message)"
                  class="botmail-dir"
                  :class="botmailDirection(item.message)"
                >
                  <svg
                    v-if="botmailDirection(item.message) === 'sent'"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <path
                      d="M3.8 11.2 20.2 4.2 13.2 20.6 10.8 13.4 3.8 11.2Z"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.7"
                      stroke-linejoin="round"
                    />
                    <path
                      d="M10.8 13.4 20.2 4.2"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.7"
                    />
                  </svg>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                    <path
                      d="M4 8.2 12 13.2 20 8.2"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.7"
                      stroke-linejoin="round"
                    />
                    <path
                      d="M4 7.6h16v9.6a1.6 1.6 0 0 1-1.6 1.6H5.6A1.6 1.6 0 0 1 4 17.2V7.6Z"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.7"
                    />
                  </svg>
                  <span>{{ botmailLead(item.message) }}</span>
                  <a
                    v-if="botmailPeer(item.message)"
                    class="bot-mention"
                    :href="mentionHref(botmailPeer(item.message).bot, botmailPeer(item.message).msgId || null)"
                    :data-bot="botmailPeer(item.message).bot"
                    :data-msg="botmailPeer(item.message).msgId || undefined"
                    :style="{ color: avatarColor(botmailPeer(item.message).bot) }"
                  >@{{ botmailPeer(item.message).bot }}</a>
                </div>
                <div
                  v-if="botmailAttachments(item.message).length"
                  class="botmail-files"
                >
                  <a
                    v-for="(att, ai) in botmailAttachments(item.message)"
                    :key="`${item.id}-mail-file-${ai}`"
                    class="botmail-file"
                    :href="botmailAttUrl(att)"
                    :download="att.name || undefined"
                    target="_blank"
                    rel="noopener"
                    @click.stop
                  >
                    <span class="botmail-file-name">{{ att.name || t("chat.mailFile") }}</span>
                    <span v-if="att.size" class="botmail-file-size">{{
                      formatBytes(att.size)
                    }}</span>
                  </a>
                </div>
                <div
                  v-if="isEventTrigger(item.message)"
                  class="event-trigger"
                  :class="item.message.meta?.kind"
                >
                  <span class="event-trigger-label">
                    {{
                      item.message.meta?.kind === "webhook"
                        ? t("chat.webhookLabel")
                        : t("chat.scheduleLabel")
                    }}
                    <template v-if="item.message.meta?.name">
                      ·
                      <button
                        type="button"
                        class="event-trigger-name"
                        :title="t('events.showInstruction')"
                        @click.stop="openEventInstruction(item.message)"
                      >
                        {{ item.message.meta.name }}
                      </button>
                    </template>
                  </span>
                  <button
                    v-if="item.message.meta?.anchor_message_id"
                    type="button"
                    class="event-anchor"
                    @click.stop="scrollToMessage(item.message.meta.anchor_message_id)"
                  >
                    {{ t("chat.eventAnchor") }}
                  </button>
                </div>
                <div
                  v-else-if="botmailDirection(item.message) && showBubbleText(item.message)"
                  class="botmail-body"
                  :class="{
                    collapsed:
                      botmailCollapsible(item.message) &&
                      !isBotmailExpanded(item.message),
                    expanded: isBotmailExpanded(item.message),
                  }"
                >
                  <span
                    class="botmail-body-html"
                    v-html="renderBotmail(item.message)"
                  />
                  <span
                    v-if="botmailCollapsible(item.message)"
                    class="botmail-fold"
                    aria-hidden="true"
                  >{{
                    isBotmailExpanded(item.message) ? "▴" : "▾"
                  }}</span>
                </div>
                <span
                  v-else-if="showBubbleText(item.message)"
                  v-html="render(item.message)"
                />
              </div>
              <div
                v-if="reactionsOf(item.message).length"
                class="msg-reactions"
                :class="item.message.role"
              >
                <span
                  v-for="emo in reactionsOf(item.message)"
                  :key="emo"
                  class="msg-reaction"
                >{{ emo }}</span>
              </div>
              <div
                v-if="showQueuedActions(item.message)"
                class="msg-queued-actions"
              >
                <button
                  v-if="isFirstQueued(item.message)"
                  type="button"
                  class="msg-queued-action send"
                  :disabled="sendingQueuedNow"
                  :title="t('chat.queuedSendNowHint')"
                  :aria-label="t('chat.queuedSendNow')"
                  @click.stop="sendQueuedNow"
                >
                  {{ t("chat.queuedSendNow") }}
                </button>
                <button
                  v-if="canEditQueued(item.message)"
                  type="button"
                  class="msg-queued-action edit"
                  :title="t('chat.queuedEditHint')"
                  :aria-label="t('chat.queuedEdit')"
                  @click.stop="editQueued(item.message)"
                >
                  {{ t("chat.queuedEdit") }}
                </button>
              </div>
            </div>
            <time
              v-if="item.message.role === 'assistant' && msgStamp(item.message).time"
              class="msg-time"
              :datetime="item.message.created_at"
            >
              <span v-if="msgStamp(item.message).date" class="msg-time-date">{{
                msgStamp(item.message).date
              }}</span>
              <span class="msg-time-clock">{{ msgStamp(item.message).time }}</span>
            </time>
          </div>
        </article>
      </template>
      <template v-if="!hasQueued">
        <article v-if="deskCreating" class="msg assistant thinking" aria-live="polite">
          <div class="thinking-row waiting">
            <span class="thinking-label">{{ t("desk.creating") }}</span>
          </div>
        </article>
        <article v-else-if="waitingHuman" class="msg assistant thinking" aria-live="polite">
          <div class="thinking-row waiting">
            <span class="thinking-label">{{ t("chat.waitingHuman") }}</span>
          </div>
        </article>
        <article v-else-if="showAgentOrb" class="msg assistant thinking" aria-live="polite">
          <div class="thinking-row">
            <WorkingOrb state="working" :size="22" :label="t('chat.working')" />
            <span class="thinking-label">{{ t("chat.working") }}</span>
            <button
              type="button"
              class="agent-stop-btn"
              :aria-label="t('chat.stop')"
              :title="t('chat.stopHint')"
              @click="stop"
            >
              {{ t("chat.stop") }}
            </button>
          </div>
        </article>
      </template>
      <div class="messages-tail" aria-hidden="true" />
    </div>
    <button
      v-if="!stickToBottom && thread.length"
      type="button"
      class="chat-jump-bottom"
      :aria-label="t('chat.jumpBottom')"
      :title="t('chat.jumpBottom')"
      @click="scrollMessagesToBottom(true, true)"
    >
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path
          d="M6 9.5 12 15.5 18 9.5"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
    <p v-if="secretRefuseHint" class="composer-secret-refuse" role="alert">
      {{ secretRefuseHint }}
    </p>
    <div v-if="showRetryBar" class="composer-retry" role="status">
      <p class="composer-retry-hint">{{ retryHint }}</p>
      <button
        type="button"
        class="composer-retry-btn"
        :disabled="retrying || waitingHuman"
        @click="retryPending"
      >
        {{ retrying ? t("chat.retrying") : t("chat.retry") }}
      </button>
      <p v-if="retryFeedback" class="composer-retry-feedback">{{ retryFeedback }}</p>
    </div>
    <form class="composer" @submit.prevent="send">
      <button
        class="icon-btn"
        type="button"
        :aria-label="t('chat.attachFile')"
        :title="t('chat.attachFile')"
        :disabled="uploading"
        @click="openFilePicker"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      <div class="composer-main">
        <div v-if="pending.length" class="composer-atts">
          <div
            v-for="item in pending"
            :key="item.id"
            class="composer-att"
            :class="item.kind"
          >
            <img
              v-if="item.kind === 'image'"
              :src="item.preview"
              :alt="t('chat.pastedImage')"
            />
            <div v-else class="composer-att-file" :title="item.name">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path
                  d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linejoin="round"
                />
                <path
                  d="M14 3v5h5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linejoin="round"
                />
              </svg>
              <span>{{ item.name }}</span>
            </div>
            <button
              type="button"
              class="composer-att-rm"
              :aria-label="t('chat.removeAttachment')"
              @click="removePending(item.id)"
            >
              ×
            </button>
          </div>
        </div>
        <div class="composer-input">
          <div
            ref="mirror"
            class="composer-mirror"
            aria-hidden="true"
            v-html="composerHighlight"
          />
          <textarea
            ref="composer"
            v-model="text"
            rows="1"
            :placeholder="composerPlaceholder"
            @keydown="onComposerKey"
            @paste="onPaste"
            @input="onComposerInput"
            @click="syncMentionQuery"
            @keyup="syncMentionQuery"
            @scroll="syncMirrorScroll"
            @blur="onComposerBlur"
          />
          <ul
            v-if="mentionOpen"
            class="mention-menu"
            role="listbox"
            :aria-label="t('chat.mentionList')"
          >
            <li v-if="!mentionMatches.length" class="mention-empty">
              {{ t("chat.mentionNone") }}
            </li>
            <li
              v-for="(b, i) in mentionMatches"
              :key="b.name"
              role="option"
              :aria-selected="i === mentionIndex"
              :class="{ active: i === mentionIndex }"
              @mousedown.prevent="pickMention(b)"
            >
              <span class="mention-pip" :style="{ background: avatarColor(b.name) }" />
              <span class="mention-name" :style="{ color: avatarColor(b.name) }">
                @{{ b.label || b.name }}
              </span>
              <span v-if="b.label && b.label !== b.name" class="mention-label">
                {{ b.name }}
              </span>
            </li>
          </ul>
        </div>
      </div>
      <button
        v-if="deskCreating || waitingHuman"
        class="send-btn working waiting"
        type="button"
        :aria-label="t('chat.stop')"
        :title="deskCreating ? t('desk.creating') : t('chat.waitingHumanHint')"
        @click="stop"
      >
        <span class="send-wait-dot" aria-hidden="true" />
      </button>
      <button
        v-else
        class="send-btn"
        :class="{ queue: busy }"
        type="submit"
        :aria-label="t('chat.send')"
        :title="t('chat.send')"
        :disabled="!canSend"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
          <path d="M3.2 11.1 19.6 4.4c.8-.3 1.5.5 1.1 1.3L13.2 20.4c-.3.8-1.5.7-1.7-.2l-1.8-6.4-6.4-1.8c-.8-.2-.9-1.4-.1-1.7Z" />
        </svg>
      </button>
    </form>
    </div>
    <EventInstructionModal
      :open="!!eventInstructionModal"
      :name="eventInstructionModal?.name || ''"
      :instruction="eventInstructionModal?.instruction || ''"
      :kind="eventInstructionModal?.kind || 'webhook'"
      :show-payload="!!eventInstructionModal?.showPayload"
      :payload="eventInstructionModal?.payload || ''"
      @close="eventInstructionModal = null"
    />
  </div>
</template>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api } from "../api";
import { state } from "../store";
import { loadOlderMessages, threadBooting, threadHasMore } from "../threadPages";
import { avatarColor } from "../avatarColor";
import {
  colorizeMentionsInHtml,
  composerHighlightHtml,
  filterMentionBots,
  mentionDeepLink,
  mentionHref,
  mentionQueryAt,
} from "../mentions";
import { formatMsgStamp, formatMsgTime } from "../timeFormat";
import { uid } from "../uid";
import ToolGroup from "./ToolGroup.vue";
import VaultRequestCard from "./VaultRequestCard.vue";
import MemoryProposalCard from "./MemoryProposalCard.vue";
import ApprovalCard from "./ApprovalCard.vue";
import BotDeleteCard from "./BotDeleteCard.vue";
import ClarifyCard from "./ClarifyCard.vue";
import DeskRequestCard from "./DeskRequestCard.vue";
import AgentResumeCard from "./AgentResumeCard.vue";
import EventInstructionModal from "./EventInstructionModal.vue";
import WorkingOrb from "./WorkingOrb.vue";
import {
  getComposerDraft,
  setComposerDraft,
  clearComposerDraft,
  getComposerPending,
  setComposerPending,
  clearComposerPending,
} from "../composerDrafts.js";

/** Pasted vision images (LLM often caps at 2/prompt; extras deferred server-side). */
const MAX_PENDING_IMAGES = 2;

const props = defineProps({ bot: { type: Object, required: true } });
const { t, locale } = useI18n();
const router = useRouter();
const text = ref(getComposerDraft(props.bot?.name));
const pending = ref(getComposerPending(props.bot?.name).slice());
const scroller = ref(null);
const composer = ref(null);
const compactComposerPh = ref(
  typeof window !== "undefined" && window.matchMedia("(max-width: 720px)").matches
);
const secretRefuseHint = ref("");
const mirror = ref(null);
const fileInput = ref(null);
const dragDepth = ref(0);
const uploading = ref(false);
const mentionOpen = ref(false);
const mentionIndex = ref(0);
const mentionQuery = ref(null);
/** After Escape, keep the menu closed for this @ token (keyup would reopen it). */
let mentionDismissedStart = null;
const flashMsgId = ref("");
const tokenTipOpen = ref(false);
/** Auto-follow new messages only while the user stays near the bottom. */
const stickToBottom = ref(true);
/** Hidden until the first jump, so opening a thread does not fly through history. */
const threadPlaced = ref(false);
const NEAR_BOTTOM_PX = 100;
let flashTimer = null;

function formatTokenCount(n) {
  const v = Math.max(0, Number(n) || 0);
  if (v >= 1_000_000) {
    return `${(v / 1_000_000).toLocaleString(locale.value, {
      maximumFractionDigits: 1,
    })}M`;
  }
  if (v >= 10_000) {
    return `${Math.round(v / 1000).toLocaleString(locale.value)}k`;
  }
  if (v >= 1000) {
    return `${(v / 1000).toLocaleString(locale.value, {
      maximumFractionDigits: 1,
    })}k`;
  }
  return v.toLocaleString(locale.value);
}

/** Live bot row from store (token counters update via bot.updated). */
const liveBot = computed(() => {
  const name = props.bot?.name;
  const fromStore = (state.bots || []).find((b) => b.name === name);
  return fromStore || props.bot;
});

const tokenStats = computed(() => {
  const tin = Number(liveBot.value?.tokens_in) || 0;
  const tout = Number(liveBot.value?.tokens_out) || 0;
  const visible = tin > 0 || tout > 0;
  return {
    visible,
    inLabel: formatTokenCount(tin),
    outLabel: formatTokenCount(tout),
    tip: t("chat.tokenUsageTip", {
      in: tin.toLocaleString(locale.value),
      out: tout.toLocaleString(locale.value),
    }),
  };
});

/** LLM actively generating / tool-running (not paused on user approval). */
const busy = computed(() => props.bot.status === "busy");
/** VM boot in progress — not an agent run yet. */
const deskCreating = computed(() => props.bot.desk?.state === "creating");
/** Agent mid-run but blocked on vault/desk user approval. */
const waitingHuman = computed(
  () => props.bot.status === "waiting" && !deskCreating.value
);
const runLocked = computed(
  () => busy.value || waitingHuman.value || deskCreating.value
);
const canSend = computed(
  () => !uploading.value && (!!text.value.trim() || pending.value.length > 0)
);

/** True only before the first streaming token (retry-bar logic). */
const waitingForReply = computed(() => {
  if (!busy.value || waitingHuman.value) return false;
  const msgs = state.messages[props.bot.name] || [];
  return !msgs.some((m) => m.role === "assistant" && m.meta?.streaming);
});
/** Left-side orb for the whole run, including tools and streaming text. */
const showAgentOrb = computed(() => busy.value && !waitingHuman.value);

const otherBots = computed(() =>
  (state.bots || []).filter((b) => b.name && b.name !== props.bot.name)
);

const mentionMatches = computed(() => {
  if (!mentionQuery.value) return [];
  return filterMentionBots(
    otherBots.value,
    mentionQuery.value.query,
    props.bot.name
  ).slice(0, 8);
});

const composerHighlight = computed(() =>
  composerHighlightHtml(text.value, state.bots || [])
);

const composerPlaceholder = computed(() => {
  if (runLocked.value) return t("chat.placeholderQueue");
  if (compactComposerPh.value) return t("chat.placeholderToMobile");
  return t("chat.placeholderTo", { name: props.bot.label || props.bot.name });
});

function autosize() {
  const el = composer.value;
  if (!el) return;
  el.style.height = "auto";
  const max = 160;
  const min = 32; /* match .composer .icon-btn */
  el.style.height = `${Math.min(Math.max(el.scrollHeight, min), max)}px`;
  syncMirrorScroll();
}

function syncMirrorScroll() {
  const el = composer.value;
  const m = mirror.value;
  if (!el || !m) return;
  m.scrollTop = el.scrollTop;
}

function syncMentionQuery() {
  const el = composer.value;
  if (!el) {
    mentionDismissedStart = null;
    closeMentions();
    return;
  }
  const q = mentionQueryAt(text.value, el.selectionStart ?? text.value.length);
  if (!q) {
    mentionDismissedStart = null;
    closeMentions();
    return;
  }
  // Escape closed this @ — ignore keyup/click until the user starts a new @.
  if (mentionDismissedStart !== null && q.start === mentionDismissedStart) {
    return;
  }
  mentionDismissedStart = null;
  const prev = mentionQuery.value;
  const sameQuery =
    prev &&
    prev.start === q.start &&
    String(prev.query || "").toLowerCase() === String(q.query || "").toLowerCase();
  mentionQuery.value = q;
  mentionOpen.value = true;
  // ArrowUp/Down also fire keyup → keep the highlighted row unless the filter changed.
  if (!sameQuery) mentionIndex.value = 0;
  else if (mentionIndex.value >= mentionMatches.value.length) {
    mentionIndex.value = Math.max(0, mentionMatches.value.length - 1);
  }
}

function closeMentions() {
  mentionOpen.value = false;
  mentionQuery.value = null;
  mentionIndex.value = 0;
}

function onComposerInput() {
  autosize();
  syncMentionQuery();
}

function onComposerBlur() {
  // Laisse le mousedown du menu s’exécuter avant la fermeture.
  setTimeout(() => closeMentions(), 120);
}

function pickMention(bot) {
  const el = composer.value;
  const q = mentionQuery.value;
  if (!el || !bot?.name || !q) return;
  const before = text.value.slice(0, q.start);
  const after = text.value.slice(el.selectionStart ?? q.end);
  const insert = `@${bot.name} `;
  text.value = `${before}${insert}${after}`;
  closeMentions();
  nextTick(() => {
    const pos = before.length + insert.length;
    el.focus();
    el.setSelectionRange(pos, pos);
    autosize();
  });
}

function onComposerKey(e) {
  if (mentionOpen.value) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      const el = composer.value;
      const q =
        mentionQuery.value ||
        (el
          ? mentionQueryAt(text.value, el.selectionStart ?? text.value.length)
          : null);
      mentionDismissedStart = q?.start ?? null;
      closeMentions();
      return;
    }
    if (mentionMatches.value.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        mentionIndex.value = (mentionIndex.value + 1) % mentionMatches.value.length;
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        const n = mentionMatches.value.length;
        mentionIndex.value = (mentionIndex.value - 1 + n) % n;
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pickMention(mentionMatches.value[mentionIndex.value]);
        return;
      }
    }
  }
  if (e.key !== "Enter" || e.isComposing) return;
  if (e.shiftKey) return;
  e.preventDefault();
  send();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

function isImageAtt(att) {
  return typeof att === "string";
}

function isFileAtt(att) {
  return att && typeof att === "object" && (att.type === "file" || att.path);
}

function imageAtts(message) {
  return (message?.attachments || []).filter(isImageAtt);
}

function fileAtts(message) {
  return (message?.attachments || []).filter(isFileAtt);
}

const _IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "webp", "gif", "bmp", "svg"]);

function isImageFileAtt(att) {
  return isFileAtt(att) && _IMAGE_EXTS.has(fileExt(att));
}

/** Pasted images + uploaded image files → thumbnail grid. */
function thumbAtts(message) {
  return (message?.attachments || []).filter(
    (a) => isImageAtt(a) || isImageFileAtt(a)
  );
}

/** Non-image file cards (PDF, etc.). */
function docAtts(message) {
  return fileAtts(message).filter((a) => !isImageFileAtt(a));
}

function imageAttUrl(att) {
  return typeof att === "string" ? att : "";
}

function fileAttName(att) {
  return att?.name || String(att?.path || "").split("/").pop() || t("chat.file");
}

function fileAttUrl(att) {
  return att?.url || api.downloadUrl(props.bot.name, att?.path || "");
}

function thumbSrc(att) {
  return isFileAtt(att) ? fileAttUrl(att) : imageAttUrl(att);
}

function thumbHref(att) {
  return isFileAtt(att) ? fileAttUrl(att) : imageAttUrl(att);
}

function fileExt(att) {
  const name = fileAttName(att);
  const i = name.lastIndexOf(".");
  if (i <= 0 || i === name.length - 1) return "";
  return name.slice(i + 1).toLowerCase();
}

function fileKindLabel(att) {
  const ext = fileExt(att);
  if (!ext) return t("chat.file");
  return ext.toUpperCase();
}

function fileKindClass(att) {
  const ext = fileExt(att);
  if (ext === "pdf") return "kind-pdf";
  if (["doc", "docx", "odt", "rtf"].includes(ext)) return "kind-doc";
  if (["xls", "xlsx", "csv", "ods"].includes(ext)) return "kind-sheet";
  if (["ppt", "pptx", "odp"].includes(ext)) return "kind-slides";
  if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) return "kind-zip";
  if (["txt", "md", "json", "xml", "yml", "yaml", "log"].includes(ext)) return "kind-text";
  return "kind-generic";
}

/** Compact type icon (PDF red mark, else generic doc). */
function fileKindIcon(att) {
  if (fileExt(att) === "pdf") {
    return (
      '<svg class="file-type-svg pdf" viewBox="0 0 40 40" width="36" height="36" aria-hidden="true">' +
      '<rect x="4" y="2" width="24" height="32" rx="3" fill="#fff" stroke="#e5e5ea" stroke-width="1.2"/>' +
      '<path d="M20 2v8h8" fill="none" stroke="#e5e5ea" stroke-width="1.2"/>' +
      '<rect x="2" y="22" width="28" height="12" rx="2" fill="#e5252a"/>' +
      '<text x="16" y="31" text-anchor="middle" fill="#fff" font-size="7.5" font-weight="700" font-family="system-ui,sans-serif">PDF</text>' +
      "</svg>"
    );
  }
  const label = fileKindLabel(att).slice(0, 4);
  return (
    '<svg class="file-type-svg" viewBox="0 0 40 40" width="36" height="36" aria-hidden="true">' +
    '<rect x="4" y="2" width="24" height="32" rx="3" fill="#fff" stroke="#d8d8de" stroke-width="1.2"/>' +
    '<path d="M20 2v8h8" fill="none" stroke="#d8d8de" stroke-width="1.2"/>' +
    `<text x="16" y="26" text-anchor="middle" fill="#6b6b72" font-size="6.5" font-weight="700" font-family="system-ui,sans-serif">${label}</text>` +
    "</svg>"
  );
}

function reactionsOf(message) {
  const raw = message?.meta?.reactions;
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => String(item || "").trim()).filter(Boolean);
}

function showBubbleShell(message) {
  if (message?.meta?.queued) return true;
  if (isEventTrigger(message)) return true;
  if (message?.meta?.streaming) return true;
  return showBubbleText(message);
}

async function cancelQueued(message) {
  const bot = props.bot.name;
  const id = message?.id;
  if (!bot || !id || !message?.meta?.queued) return false;
  const list = state.messages[bot] || [];
  const idx = list.findIndex((m) => m.id === id);
  const snapshot = idx >= 0 ? list[idx] : null;
  state.messages[bot] = list.filter((m) => m.id !== id);
  if (String(id).startsWith("tmp-")) return true;
  try {
    await api.deleteQueuedMessage(bot, id);
    return true;
  } catch (e) {
    if (snapshot) {
      const cur = state.messages[bot] || [];
      if (!cur.some((m) => m.id === id)) {
        const next = cur.slice();
        next.splice(Math.min(idx, next.length), 0, snapshot);
        state.messages[bot] = next;
      }
    }
    alert(e.message || String(e));
    return false;
  }
}

const sendingQueuedNow = ref(false);

function compareQueued(a, b) {
  const oa = Number(a?.meta?.queue_ord);
  const ob = Number(b?.meta?.queue_ord);
  const aOrd = Number.isFinite(oa);
  const bOrd = Number.isFinite(ob);
  if (aOrd && bOrd && oa !== ob) return oa - ob;
  if (aOrd && !bOrd) return -1;
  if (!aOrd && bOrd) return 1;
  const byTime = String(a.created_at || "").localeCompare(String(b.created_at || ""));
  if (byTime) return byTime;
  return String(a.id || "").localeCompare(String(b.id || ""));
}

const firstQueuedId = computed(() => {
  const list = (state.messages[props.bot.name] || [])
    .filter((m) => m?.meta?.queued && !m?.meta?.hidden_prompt)
    .slice()
    .sort(compareQueued);
  return list[0]?.id ?? null;
});

function isFirstQueued(message) {
  const id = message?.id;
  return id != null && id === firstQueuedId.value;
}

function canEditQueued(message) {
  if (message?.role !== "user" || !message?.meta?.queued) return false;
  if (isEventTrigger(message) || botmailDirection(message)) return false;
  return true;
}

function showQueuedActions(message) {
  return isFirstQueued(message) || canEditQueued(message);
}

async function sendQueuedNow() {
  if (sendingQueuedNow.value) return;
  sendingQueuedNow.value = true;
  try {
    await stop();
  } finally {
    sendingQueuedNow.value = false;
  }
}

async function editQueued(message) {
  if (!canEditQueued(message)) return;
  const content = String(message?.content || "");
  const removed = await cancelQueued(message);
  if (!removed) return;
  text.value = content;
  await nextTick();
  autosize();
  const el = composer.value;
  el?.focus();
  if (el && typeof el.setSelectionRange === "function") {
    const end = el.value.length;
    el.setSelectionRange(end, end);
  }
}

function pendingImageCount() {
  return pending.value.filter((p) => p.kind === "image").length;
}

/** Paste → image data-URL (vision). */
async function addPendingImages(files) {
  for (const file of files) {
    if (!file?.type?.startsWith("image/")) continue;
    if (pendingImageCount() >= MAX_PENDING_IMAGES) {
      alert(t("chat.tooManyImages", { count: MAX_PENDING_IMAGES }));
      break;
    }
    try {
      const dataUrl = await fileToDataUrl(file);
      if (!dataUrl.startsWith("data:image/")) continue;
      pending.value.push({
        id: uid(),
        kind: "image",
        preview: URL.createObjectURL(file),
        dataUrl,
        name: file.name || "image",
      });
    } catch (err) {
      alert(err.message || String(err));
    }
  }
}

/** Picker / drop → ~/files/upload/<uuid>/<name>. */
async function addPendingUploads(fileList) {
  const files = [...(fileList || [])].filter(Boolean);
  if (!files.length) return;
  uploading.value = true;
  try {
    for (const file of files) {
      try {
        const saved = await api.uploadChatFile(props.bot.name, file);
        pending.value.push({
          id: uid(),
          kind: "file",
          name: saved.name || file.name,
          path: saved.path,
          url: saved.url,
          size: saved.size,
        });
      } catch (err) {
        alert(err.message || String(err));
      }
    }
  } finally {
    uploading.value = false;
  }
}

function openFilePicker() {
  if (uploading.value) return;
  fileInput.value?.click();
}

async function onFilePicked(e) {
  const input = e?.target;
  const files = input?.files;
  if (files?.length) await addPendingUploads(files);
  if (input) input.value = "";
}

function onDragEnter(e) {
  if (!e.dataTransfer?.types?.includes("Files")) return;
  dragDepth.value += 1;
}

function onDragLeave() {
  dragDepth.value = Math.max(0, dragDepth.value - 1);
}

function onDragOver(e) {
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
}

async function onDrop(e) {
  dragDepth.value = 0;
  const files = e.dataTransfer?.files;
  if (files?.length) await addPendingUploads(files);
}

async function onPaste(e) {
  const items = e.clipboardData?.items;
  if (!items?.length) return;
  const files = [];
  for (const item of items) {
    if (item.kind === "file" && item.type.startsWith("image/")) {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  if (!files.length) return;
  e.preventDefault();
  await addPendingImages(files);
}

function removePending(id) {
  const i = pending.value.findIndex((p) => p.id === id);
  if (i < 0) return;
  const [gone] = pending.value.splice(i, 1);
  if (gone?.preview) URL.revokeObjectURL(gone.preview);
}

function clearPending() {
  for (const p of pending.value) {
    if (p.preview) URL.revokeObjectURL(p.preview);
  }
  pending.value = [];
}

function showBubbleText(m) {
  const c = (m.content || "").trim();
  if (!c) return false;
  if (
    m.attachments?.length &&
    /^\((image|\d+ images|fichier|\d+ fichiers|\d+ pièces jointes)\)$/i.test(c)
  ) {
    return false;
  }
  return true;
}

const COPY_ICON =
  '<svg class="code-copy-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">' +
  '<rect x="8" y="8" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
  '<path d="M6 16V6a2 2 0 0 1 2-2h10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' +
  "</svg>";
const CHECK_ICON =
  '<svg class="code-copy-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">' +
  '<path d="M5 12.5 10 17.5 19 7.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
  "</svg>";

/** Wrap marked `<pre>` blocks so each gets a one-click copy control. */
function wrapCodeBlocks(html) {
  return String(html || "").replace(/<pre(\b[^>]*)>([\s\S]*?)<\/pre>/gi, (_m, attrs, inner) => {
    const label = t("chat.copyCode");
    return (
      `<div class="code-block">` +
      `<button type="button" class="code-copy" aria-label="${label}" title="${label}">${COPY_ICON}</button>` +
      `<pre${attrs}>${inner}</pre>` +
      `</div>`
    );
  });
}

/** Scroll shell around markdown tables (wide lab panels, etc.). */
function wrapTables(html) {
  return String(html || "").replace(/<table(\b[^>]*)>([\s\S]*?)<\/table>/gi, (_m, attrs, inner) => {
    return `<div class="md-table-wrap"><table${attrs}>${inner}</table></div>`;
  });
}

/** Map relative workspace image paths to authenticated /files/raw URLs. */
function rewriteWorkspaceImages(content, botName) {
  if (!content || !botName) return content || "";
  return String(content).replace(
    /!\[([^\]]*)\]\(([^)\s]+)\)/g,
    (full, alt, url) => {
      const raw = String(url || "").trim();
      if (!raw) return full;
      if (raw.includes(`/api/v1/bots/${botName}/files/raw`)) return full;
      if (/^https?:\/\//i.test(raw) || raw.startsWith("data:")) return full;
      // Local-ish path: renard.svg, files/x.png, shared/x.png, ./foo.jpg
      const path = raw
        .replace(/^\/+/, "")
        .replace(/^\.\//, "")
        .replace(/^~\/files\//, "")
        .replace(/^files\//, "")
        .replace(/^~\/shared\//, "")
        .replace(/^shared\//, "");
      if (!path || path.includes("..")) return full;
      const src = `/api/v1/bots/${encodeURIComponent(botName)}/files/raw?path=${encodeURIComponent(path)}`;
      return `![${alt}](${src})`;
    },
  );
}

/** Escape raw HTML so marked/DOMPurify cannot swallow the rest of the message.
 *  E.g. user text « … et <script setup>. » must not open a real <script> tag.
 *  Only angle brackets — leave & alone so markdown URLs with query strings stay intact. */
function escapeRawHtml(text) {
  return String(text || "")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function render(messageOrContent) {
  const message =
    messageOrContent && typeof messageOrContent === "object"
      ? messageOrContent
      : null;
  const botName = message?.bot || props.bot?.name || "";
  let raw = message ? message.content : messageOrContent;
  if (message && botmailDirection(message) === "received") {
    raw = String(raw || "").replace(
      /^@[a-zA-Z0-9_-]+\s+m['’]a envoyé un message\s*:\s*/i,
      "",
    );
  }
  // Escape before markdown so tags in prose (Vue <script setup>, generics, …)
  // stay visible. marked still builds <p>/<strong>/images from markdown syntax.
  const content = rewriteWorkspaceImages(escapeRawHtml(raw), botName);
  const md = marked.parse(content || "", { breaks: true, gfm: true });
  const withMentions = colorizeMentionsInHtml(String(md), state.bots || [], {
    message,
  });
  const withCopy = wrapCodeBlocks(withMentions);
  const withTables = wrapTables(withCopy);
  return DOMPurify.sanitize(withTables, {
    ADD_ATTR: [
      "style",
      "data-bot",
      "data-msg",
      "href",
      "src",
      "alt",
      "loading",
      "target",
      "rel",
      "type",
      "aria-label",
      "title",
      "aria-hidden",
      "focusable",
      "viewBox",
      "width",
      "height",
      "fill",
      "stroke",
      "stroke-width",
      "stroke-linecap",
      "stroke-linejoin",
      "rx",
      "x",
      "y",
      "d",
      "class",
    ],
    ADD_TAGS: ["a", "button", "svg", "path", "rect", "img"],
  });
}

async function copyCodeBlock(btn) {
  const pre = btn.closest(".code-block")?.querySelector("pre");
  const text = pre?.innerText ?? pre?.textContent ?? "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(ta);
    }
  }
  const prev = btn.getAttribute("aria-label") || t("chat.copyCode");
  btn.classList.add("copied");
  btn.setAttribute("aria-label", t("chat.copied"));
  btn.setAttribute("title", t("chat.copied"));
  btn.innerHTML = CHECK_ICON;
  if (btn._copyTimer) clearTimeout(btn._copyTimer);
  btn._copyTimer = setTimeout(() => {
    btn.classList.remove("copied");
    btn.setAttribute("aria-label", prev);
    btn.setAttribute("title", prev);
    btn.innerHTML = COPY_ICON;
    btn._copyTimer = null;
  }, 1600);
}

function scrollToMessage(msgId) {
  if (!msgId) return;
  const tryScroll = (attempt = 0) => {
    const root = scroller.value;
    const el = root?.querySelector?.(`[data-msg-id="${CSS.escape(msgId)}"]`);
    if (!el) {
      if (attempt < 12) setTimeout(() => tryScroll(attempt + 1), 80);
      return;
    }
    el.scrollIntoView({ behavior: "auto", block: "center" });
    threadPlaced.value = true;
    flashMsgId.value = msgId;
    if (flashTimer) clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      if (flashMsgId.value === msgId) flashMsgId.value = "";
    }, 2200);
  };
  nextTick(() => tryScroll());
}

const lightboxSrc = ref("");
const lightboxAlt = ref("");

function openLightbox(src, alt = "") {
  if (!src) return;
  lightboxSrc.value = src;
  lightboxAlt.value = alt || "";
}

function closeLightbox() {
  lightboxSrc.value = "";
  lightboxAlt.value = "";
}

function onChatClick(e) {
  const copyBtn = e.target?.closest?.(".code-copy");
  if (copyBtn) {
    e.preventDefault();
    e.stopPropagation();
    copyCodeBlock(copyBtn);
    return;
  }
  const thumb = e.target?.closest?.(
    ".bubble img, .shot-card img, a.bubble-thumb, .bubble-thumb img",
  );
  if (thumb) {
    const img = thumb.tagName === "IMG" ? thumb : thumb.querySelector("img");
    const src =
      img?.currentSrc ||
      img?.getAttribute("src") ||
      thumb.getAttribute("href") ||
      "";
    if (src) {
      e.preventDefault();
      e.stopPropagation();
      openLightbox(src, img?.getAttribute("alt") || "");
      return;
    }
  }
  const el = e.target?.closest?.(".bot-mention[data-bot]");
  if (!el) return;
  const name = el.getAttribute("data-bot");
  const msgId = el.getAttribute("data-msg") || "";
  if (!name) return;
  e.preventDefault();
  e.stopPropagation();
  state.tab = "discussion";
  if (name === props.bot.name) {
    if (msgId) scrollToMessage(msgId);
    return;
  }
  state.currentBot = name;
  router.push(mentionHref(name, msgId || null));
}

const HIDDEN_TOOL_CARDS = new Set([
  "bot_list",
  "bot_tell",
  "bot_ask",
  "bot_delegate",
  "schedule_list",
  "schedule_create",
  "schedule_update",
  "schedule_delete",
  "webhook_list",
  "webhook_create",
  "webhook_update",
  "webhook_delete",
  // Mémoire : carte dédiée MemoryProposalCard, pas une ligne d’outil.
  "memory_propose",
  "memory_list",
  "memory_get",
  "memory_search",
  "ask_approval",
  "ask_clarify",
  "report_user_secret",
  "chat_search",
  "react",
]);

function isEventTrigger(m) {
  const kind = m?.meta?.kind;
  return kind === "schedule" || kind === "webhook";
}

const eventInstructionModal = ref(null);

/** Standing instruction for a fire card (meta, or stripped content for older msgs). */
function eventCarrierInstruction(m) {
  const meta = m?.meta || {};
  const fromMeta = String(meta.instruction || "").trim();
  if (fromMeta) return fromMeta;
  let text = String(m?.content || "").trim();
  text = text.replace(/^La tâche planifiée « [^»]* » dit ceci :\s*/i, "");
  text = text.replace(/^Webhook déclenché avec une charge\.\s*/i, "");
  text = text.replace(/^Webhook déclenché\.\s*/i, "");
  text = text.replace(/\n+Contexte ancré : message \S+\s*$/i, "");
  text = text.replace(/\n+Payload\s*:\s*[\s\S]*$/i, "");
  return text.trim();
}

function eventPayloadText(m) {
  const meta = m?.meta || {};
  if (meta.payload != null && meta.payload !== "") {
    const formatted = formatPayload(meta.payload).trim();
    if (formatted && formatted !== "{}") return formatted;
  }
  for (const blob of [meta.agent_prompt, m?.content]) {
    const text = String(blob || "");
    const match = text.match(/(?:^|\n)Payload\s*:\s*\n?([\s\S]*)$/i);
    if (match && match[1].trim()) return match[1].trim();
  }
  return "";
}

function openEventInstruction(m) {
  if (!isEventTrigger(m)) return;
  const meta = m?.meta || {};
  const kind = meta.kind === "schedule" ? "schedule" : "webhook";
  eventInstructionModal.value = {
    name: String(meta.name || "").trim() || "—",
    instruction: eventCarrierInstruction(m),
    kind,
    showPayload: kind === "webhook",
    payload: eventPayloadText(m),
  };
}

function bubbleTitle(m) {
  if (isEventTrigger(m)) {
    return m?.meta?.kind === "webhook"
      ? t("chat.readPayload")
      : t("events.showInstruction");
  }
  if (botmailCollapsible(m)) {
    return isBotmailExpanded(m) ? t("chat.mailCollapse") : t("chat.mailExpand");
  }
  return undefined;
}

function onMessageBubbleClick(m, ev) {
  if (isEventTrigger(m)) {
    const target = ev?.target;
    if (target && typeof target.closest === "function") {
      if (target.closest("a, button, input, textarea, summary, pre, code")) return;
    }
    openEventInstruction(m);
    return;
  }
  onBotmailBubbleClick(m, ev);
}

function isNotify(m) {
  return m?.role === "event" && m?.meta?.kind === "tool" && m?.meta?.tool_name === "notify_user";
}

function notifyTitle(m) {
  return String(m?.meta?.args?.title || "").trim();
}

function notifyBody(m) {
  return String(m?.meta?.args?.message || m?.meta?.args?.body || "").trim();
}

/** L'agent répète souvent la notification dans sa bulle : la carte jaune suffit. */
function isNotifyAck(m) {
  if (m?.role !== "assistant") return false;
  const text = String(m?.content || "")
    .replace(/^\s*✅\s*/, "")
    .trim();
  return /^(notification envoyée|notification sent)\b/i.test(text);
}

const BOTMAIL_RECEIVED = new Set(["tell", "ask", "ask_answered"]);

/** Carte bleue inter-bots : « sent » (réponse partie) ou « received ». */
function botmailDirection(m) {
  const meta = m?.meta || {};
  if (meta.kind !== "botmail") return "";
  if (meta.direction === "sent" || meta.mail_kind === "outgoing") return "sent";
  if (
    meta.direction === "received" ||
    (m?.role === "system" && BOTMAIL_RECEIVED.has(meta.mail_kind))
  ) {
    return "received";
  }
  return "";
}

function botmailPeer(m) {
  const dir = botmailDirection(m);
  const meta = m?.meta || {};
  const name = dir === "sent" ? meta.to_bot : dir === "received" ? meta.from_bot : "";
  if (!name) return null;
  const deep = mentionDeepLink(m, name);
  return { bot: deep?.bot || name, msgId: deep?.msgId || "" };
}

function botmailLead(m) {
  const dir = botmailDirection(m);
  const peer = botmailPeer(m);
  if (dir === "sent") return peer ? t("chat.mailSentTo") : t("chat.mailSent");
  if (dir === "received") return peer ? t("chat.mailReceivedFrom") : t("chat.mailReceived");
  return "";
}

/** Expanded botmail cards (click toggles). Keys = message id. */
const botmailExpanded = reactive({});

function botmailPlainBody(m) {
  let raw = String(m?.content || "").trim();
  if (botmailDirection(m) === "received") {
    raw = raw.replace(
      /^@[a-zA-Z0-9_-]+\s+m['’]a envoyé un message\s*:\s*/i,
      "",
    );
  }
  return raw.trim();
}

/** First sentence (period must be followed by space/end — keeps Vue.js / paths intact). */
function botmailFirstSentence(text) {
  const flat = String(text || "").replace(/\s+/g, " ").trim();
  if (!flat) return "";
  const m = flat.match(/^(.+?(?:[.!?…](?=\s|$)))/);
  if (m) return m[1].trim();
  const line = String(text || "").split(/\n/, 1)[0].trim();
  if (line.length <= 160) return line;
  return `${line.slice(0, 157).trimEnd()}…`;
}

function botmailCollapsible(m) {
  if (!botmailDirection(m)) return false;
  const full = botmailPlainBody(m);
  if (!full) return false;
  const first = botmailFirstSentence(full);
  if (!first) return false;
  return full.slice(first.length).replace(/^\s+/, "").length > 0;
}

function isBotmailExpanded(m) {
  return !!(m?.id && botmailExpanded[m.id]);
}

function renderBotmail(m) {
  if (!botmailCollapsible(m) || isBotmailExpanded(m)) return render(m);
  return render(botmailFirstSentence(botmailPlainBody(m)));
}

function onBotmailBubbleClick(m, ev) {
  if (!botmailCollapsible(m)) return;
  const t = ev?.target;
  if (t && typeof t.closest === "function") {
    if (t.closest("a, button, input, textarea, summary, pre, code")) return;
  }
  const id = m?.id;
  if (!id) return;
  botmailExpanded[id] = !botmailExpanded[id];
}

function botmailAttachments(m) {
  const list = m?.meta?.attachments;
  return Array.isArray(list) ? list.filter((a) => a && (a.name || a.path)) : [];
}

function botmailAttUrl(att) {
  if (att?.url) return att.url;
  const path = att?.path || "";
  if (!path) return "#";
  return api.downloadUrl(props.bot.name, path);
}

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(v < 10 * 1024 ? 1 : 0)} KB`;
  return `${(v / (1024 * 1024)).toFixed(v < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function formatPayload(payload) {
  if (payload == null) return "";
  if (typeof payload === "string") return payload;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function isHiddenTool(m) {
  return (
    m?.role === "event" &&
    m?.meta?.kind === "tool" &&
    HIDDEN_TOOL_CARDS.has(String(m?.meta?.tool_name || ""))
  );
}

function isTool(m) {
  if (!(m?.role === "event" && m?.meta?.kind === "tool")) return false;
  // Inter-bot mail / memory: dedicated cards, not tool rows (incl. old messages).
  return !isHiddenTool(m);
}

function isVault(m) {
  return m?.role === "event" && m?.meta?.kind === "vault_request";
}

function isMemoryProposal(m) {
  return m?.role === "event" && m?.meta?.kind === "memory_proposal";
}

function isApproval(m) {
  return m?.role === "event" && m?.meta?.kind === "approval_request";
}

function isBotDelete(m) {
  return m?.role === "event" && m?.meta?.kind === "bot_delete_request";
}

function isClarify(m) {
  return m?.role === "event" && m?.meta?.kind === "clarify_request";
}

function isDeskReq(m) {
  return m?.role === "event" && m?.meta?.kind === "desk_request";
}

const GUARD_TOKEN_RE = /^\s*GUARD\s*:\s*(CONTINUE|STOP)\b[\s.:!,;-]*/i;
function isGuardPrefix(text) {
  const norm = String(text || "").toUpperCase().replace(/\s+/g, "");
  if (norm.length < 2) return false;
  return "GUARD:CONTINUE".startsWith(norm) || "GUARD:STOP".startsWith(norm);
}

/** Garde-fou : revue lancée par le système (carte, pas une bulle). */
function isGuardSystem(m) {
  return m?.role === "system" && m?.meta?.kind === "guard";
}

function isSecretLeak(m) {
  if (m?.role !== "system") return false;
  const kind = m?.meta?.kind;
  if (kind === "secret_leak" || kind === "secret_provider_alert") return true;
  // Fallback for older messages / meta manquant.
  return /divulguer un secret|disclose a secret|fournisseur LLM|LLM provider/i.test(
    String(m?.content || ""),
  );
}

/** Hard agent failures posted as `⚠️ …` assistant bubbles — show as centered red cards. */
function isAgentError(m) {
  if (m?.role !== "assistant") return false;
  if (m?.meta?.streaming) return false;
  const raw = String(m?.content || "").trim();
  if (!raw) return false;
  if (m?.meta?.error) return /^\s*⚠️/.test(raw) || raw === String(m.meta.error).trim();
  return /^\s*⚠️\s+\S/.test(raw);
}

function agentErrorItem(m) {
  const stamp = msgStamp(m);
  let text = String(m?.content || "").trim();
  text = text.replace(/^\s*⚠️\s*/, "").trim() || text;
  return {
    kind: "agent_error",
    id: `agent-error-${m.id}`,
    text,
    time: stamp.time,
    iso: m.created_at || "",
  };
}

/** Réponse de l'agent à la revue : « GUARD:CONTINUE » / « GUARD:STOP » (+ suite éventuelle). */
function guardReply(m) {
  if (m?.role !== "assistant") return null;
  const text = String(m?.content || "");
  const hit = text.match(GUARD_TOKEN_RE);
  if (hit) {
    return {
      verdict: hit[1].toUpperCase(),
      rest: text.slice(hit[0].length),
    };
  }
  // Pendant le streaming : ne jamais flasher « GUARD:CONT… » en bulle.
  if (m?.meta?.streaming && isGuardPrefix(text)) {
    return { verdict: "CONTINUE", rest: "" };
  }
  return null;
}

function secretLeakItem(m) {
  const d = parseDate(m.created_at);
  const time = d ? formatMsgTime(m.created_at, locale.value) : "";
  return {
    kind: "secret_leak",
    id: `secret-leak-${m.id}`,
    time,
    iso: m.created_at || "",
    text: String(m.content || "").trim() || t("chat.secretLeak"),
  };
}

function guardItem(m) {
  const d = parseDate(m.created_at);
  const time = d ? formatMsgTime(m.created_at, locale.value) : "";
  const base = { kind: "guard", id: `guard-${m.id}`, time, iso: m.created_at || "" };
  if (isGuardSystem(m)) {
    const meta = m.meta || {};
    if (meta.review) {
      return {
        ...base,
        icon: "🧭",
        tone: "review",
        text: t("chat.guardReview", { count: meta.action_count ?? "?" }),
      };
    }
    if (meta.guard_continue) {
      return {
        ...base,
        icon: "🧭",
        tone: "continue",
        text: t("chat.guardContinue"),
      };
    }
    // Legacy "tools blocked" notices — hide (review card is enough).
    if (meta.guard_blocked) {
      return null;
    }
    const raw = String(m.content || "").replace(/^[^\p{L}\p{N}]+/u, "").trim();
    return {
      ...base,
      icon: meta.guard_stop ? "⏹" : "⚠️",
      tone: "stop",
      text: raw || t("chat.guardStop"),
    };
  }
  const reply = guardReply(m);
  return {
    ...base,
    icon: "🧭",
    tone: reply.verdict === "STOP" ? "stop" : "continue",
    text: reply.verdict === "STOP" ? t("chat.guardStop") : t("chat.guardContinue"),
  };
}

function isResume(m) {
  return m?.role === "event" && m?.meta?.kind === "agent_interrupted";
}

function isScreenshot(m) {
  return m?.role === "event" && m?.meta?.kind === "screenshot";
}

function isGrounding(m) {
  return m?.role === "event" && m?.meta?.kind === "grounding";
}

function isGroundingShot(m) {
  return isScreenshot(m) && !!m?.meta?.grounding;
}

function isActivity(m) {
  // Fold vm_screenshot cards into the tool group so they don't split the run
  // (standalone screenshot between tools). Workspace images use markdown, not this.
  return isTool(m) || isGrounding(m) || isScreenshot(m);
}

function parseDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function msgStamp(m) {
  return formatMsgStamp(m?.created_at, locale.value);
}

function dayKey(d) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function formatDay(d) {
  const time = d.toLocaleTimeString(locale.value, { hour: "numeric", minute: "2-digit" });
  const start = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const diff = start(new Date()) - start(d);
  if (diff === 0) return t("chat.today", { time });
  if (diff === 86400000) return t("chat.yesterday", { time });
  const date = d.toLocaleDateString(locale.value, { day: "numeric", month: "short" });
  return `${date} ${time}`;
}

function sourceOf(m) {
  const meta = m.meta || {};
  for (const key of ["source", "from", "channel", "via"]) {
    const value = meta[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

const thread = computed(() => {
  const all = (state.messages[props.bot.name] || []).filter(
    (m) => !m?.meta?.hidden_prompt
  );
  const queued = all
    .filter((m) => m?.meta?.queued)
    .slice()
    .sort(compareQueued);
  const msgs = all.filter((m) => !m?.meta?.queued);
  const items = [];
  let lastKey = "";
  const todayKey = dayKey(new Date());
  const hasOlder = msgs.some((m) => {
    const d = parseDate(m.created_at);
    return d && dayKey(d) !== todayKey;
  });
  let markedNew = false;
  let activityBuf = [];
  let awaitNotifyAck = false;

  function flushActivity() {
    if (!activityBuf.length) return;
    items.push({
      kind: "tools",
      id: `tools-${activityBuf[0].id}`,
      entries: activityBuf.slice(),
    });
    activityBuf = [];
  }

  for (const m of msgs) {
    const d = parseDate(m.created_at);
    if (d) {
      const key = dayKey(d);
      if (key !== lastKey) {
        flushActivity();
        if (!markedNew && key === todayKey && hasOlder) {
          items.push({ kind: "new", id: `new-${key}` });
          markedNew = true;
        }
        items.push({ kind: "day", id: `day-${key}`, label: formatDay(d) });
        lastKey = key;
      }
    }
    if (isNotify(m)) {
      flushActivity();
      items.push({ kind: "notice", id: m.id, message: m });
      awaitNotifyAck = m?.meta?.status !== "error";
      continue;
    }
    if (awaitNotifyAck && isNotifyAck(m)) {
      awaitNotifyAck = false;
      continue;
    }
    if (isHiddenTool(m)) {
      continue;
    }
    // Whitespace-only assistant turns leave a timestamp with no bubble — skip.
    if (
      m?.role === "assistant" &&
      !(m.content || "").trim() &&
      !m?.meta?.streaming &&
      !(m.attachments && m.attachments.length)
    ) {
      continue;
    }
    if (isActivity(m)) {
      activityBuf.push(m);
      continue;
    }
    flushActivity();
    awaitNotifyAck = false;
    if (isVault(m)) {
      items.push({ kind: "vault", id: m.id, message: m });
      continue;
    }
    if (isMemoryProposal(m)) {
      items.push({ kind: "memory", id: m.id, message: m });
      continue;
    }
    if (isApproval(m)) {
      items.push({ kind: "approval", id: m.id, message: m });
      continue;
    }
    if (isBotDelete(m)) {
      items.push({ kind: "bot_delete", id: m.id, message: m });
      continue;
    }
    if (isClarify(m)) {
      items.push({ kind: "clarify", id: m.id, message: m });
      continue;
    }
    if (isDeskReq(m)) {
      items.push({ kind: "desk", id: m.id, message: m });
      continue;
    }
    if (isResume(m)) {
      items.push({ kind: "resume", id: m.id, message: m });
      continue;
    }
    if (isSecretLeak(m)) {
      items.push(secretLeakItem(m));
      continue;
    }
    if (isAgentError(m)) {
      items.push(agentErrorItem(m));
      continue;
    }
    if (isGuardSystem(m)) {
      const g = guardItem(m);
      if (g) items.push(g);
      continue;
    }
    const reply = guardReply(m);
    if (reply) {
      items.push(guardItem(m));
      if (reply.rest.trim()) {
        // Texte après le jeton : bulle normale juste sous la carte.
        items.push({
          kind: "msg",
          id: `${m.id}-rest`,
          message: { ...m, content: reply.rest.trimStart() },
        });
      }
      continue;
    }
    items.push({ kind: "msg", id: m.id, message: m });
  }
  flushActivity();
  // Guard cards must not seal tool groups (that collapsed the live panel and
  // jumped the thread). Walking backwards: only the last tools group stays
  // live; earlier ones seal. Stay unsealed between tools of the active group
  // (do not toggle on !running — that flashed the live line every call).
  let laterContent = false;
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.kind === "day" || it.kind === "new" || it.kind === "guard") continue;
    if (it.kind === "tools") {
      it.sealed = laterContent;
      laterContent = true;
    } else {
      laterContent = true;
    }
  }
  if (queued.length) {
    items.push({ kind: "live", id: "live-slot" });
    for (const m of queued) {
      items.push({ kind: "msg", id: m.id, message: m });
    }
  }
  return items;
});

const hasQueued = computed(() =>
  (state.messages[props.bot.name] || []).some(
    (m) => m?.meta?.queued && !m?.meta?.hidden_prompt
  )
);

const hasPendingResume = computed(() =>
  (state.messages[props.bot.name] || []).some(
    (m) =>
      m?.role === "event" &&
      m?.meta?.kind === "agent_interrupted" &&
      m?.meta?.state === "pending"
  )
);

function lastUserIndex(all, { includeOptimistic = true } = {}) {
  for (let i = all.length - 1; i >= 0; i--) {
    const m = all[i];
    if (m?.role !== "user" || m?.meta?.hidden_prompt || m?.meta?.queued) continue;
    if (!includeOptimistic && String(m?.id || "").startsWith("tmp-")) continue;
    return i;
  }
  return -1;
}

const hasRunningTools = computed(() =>
  (state.messages[props.bot.name] || []).some(
    (m) => m?.meta?.kind === "tool" && m?.meta?.status === "running"
  )
);

/**
 * Idle bot: last turn ended on a real failure bubble (⚠️ / abort / stop).
 * "User message, no assistant yet" is the normal post-send gap — never a retry.
 */
const lastTurnFailed = computed(() => {
  const all = state.messages[props.bot.name] || [];
  const lastUser = lastUserIndex(all, { includeOptimistic: false });
  if (lastUser < 0) return false;
  let sawFailure = false;
  for (let i = lastUser + 1; i < all.length; i++) {
    const m = all[i];
    if (m?.role === "user") break;
    if (m?.role !== "assistant") continue;
    const meta = m.meta || {};
    const text = String(m.content || "").trim();
    if (meta.streaming) return false;
    if (meta.aborted || meta.error) {
      sawFailure = true;
      continue;
    }
    if (!text || text.startsWith("⚠️") || /^⏹\s*Stopped\.?$/i.test(text)) {
      sawFailure = true;
      continue;
    }
    return false;
  }
  return sawFailure;
});

/**
 * Busy run with an error/abort bubble. Silence is not stuck: a thinking model
 * can sit for minutes with no visible token. The Working orb covers that.
 */
const stuckBusy = computed(() => {
  if (!busy.value || waitingHuman.value || hasRunningTools.value) return false;
  const all = state.messages[props.bot.name] || [];
  const lastUser = lastUserIndex(all, { includeOptimistic: false });
  if (lastUser < 0) return false;
  for (let i = all.length - 1; i > lastUser; i--) {
    const m = all[i];
    if (m?.role !== "assistant") continue;
    const meta = m.meta || {};
    const text = String(m.content || "").trim();
    if (meta.aborted || meta.error || text.startsWith("⚠️")) return true;
    return false;
  }
  return false;
});

/** Live work even if bot.status briefly lags behind SSE (streaming / tools / orb). */
const agentLive = computed(
  () =>
    busy.value ||
    waitingForReply.value ||
    hasRunningTools.value ||
    (state.messages[props.bot.name] || []).some(
      (m) => m?.role === "assistant" && m?.meta?.streaming
    )
);

/**
 * Queue left while truly idle — Relancer only after auto-drain had a chance.
 * Between two drained turns status flickers ``idle`` with messages still « En file »;
 * without this grace the bar flashes « Des messages sont en file » mid-burst.
 */
const IDLE_QUEUE_GRACE_MS = 2000;
const idleQueuedStuck = ref(false);
let idleQueuedTimer = 0;
watch(
  () =>
    !waitingHuman.value &&
    !agentLive.value &&
    !stuckBusy.value &&
    hasQueued.value,
  (idleWithQueue) => {
    clearTimeout(idleQueuedTimer);
    idleQueuedTimer = 0;
    if (!idleWithQueue) {
      idleQueuedStuck.value = false;
      return;
    }
    idleQueuedStuck.value = false;
    idleQueuedTimer = window.setTimeout(() => {
      idleQueuedStuck.value =
        !waitingHuman.value &&
        !agentLive.value &&
        !stuckBusy.value &&
        hasQueued.value;
    }, IDLE_QUEUE_GRACE_MS);
  },
  { immediate: true }
);

const showRetryBar = computed(() => {
  if (waitingHuman.value) return false;
  // Resume card already has Reprendre — never stack Relancer on top.
  if (hasPendingResume.value) return false;
  // Healthy live run (busy / streaming / tools): Working orb drains the queue after
  // the turn — never Relancer. Soft/hard stuck is the only busy exception.
  if (agentLive.value && !stuckBusy.value) return false;
  return (
    idleQueuedStuck.value ||
    stuckBusy.value ||
    (!agentLive.value && lastTurnFailed.value)
  );
});

const retryHint = computed(() => {
  if (stuckBusy.value) return t("chat.retryHintStuck");
  if (idleQueuedStuck.value) return t("chat.retryHintQueued");
  if (lastTurnFailed.value) return t("chat.retryHintFailed");
  return t("chat.retryHint");
});

const retrying = ref(false);
const retryFeedback = ref("");
let retryFeedbackTimer = 0;

async function retryPending() {
  if (retrying.value || waitingHuman.value) return;
  retrying.value = true;
  retryFeedback.value = "";
  clearTimeout(retryFeedbackTimer);
  try {
    const out = await api.retryBot(props.bot.name);
    const action = out?.action || "noop";
    if (action === "drained") retryFeedback.value = t("chat.retryDoneDrained");
    else if (action === "resumed") retryFeedback.value = t("chat.retryDoneResumed");
    else retryFeedback.value = t("chat.retryDoneNone");
  } catch (e) {
    retryFeedback.value = e?.message || String(e);
  } finally {
    retrying.value = false;
    retryFeedbackTimer = window.setTimeout(() => {
      retryFeedback.value = "";
    }, 4000);
  }
}

function absoluteScrollTop(el) {
  return Math.max(0, el.scrollHeight - el.clientHeight);
}

function isNearBottom(el) {
  if (!el) return true;
  // One target only: the real bottom (incl. « En file »). A second “peek”
  // target used to fight manual scroll and saccade near the queue.
  return Math.abs(absoluteScrollTop(el) - el.scrollTop) <= NEAR_BOTTOM_PX;
}

let messagesScrollUiTimer = 0;

function pulseMessagesScrollbar() {
  const el = scroller.value;
  if (!el) return;
  el.classList.add("messages-scrolling");
  clearTimeout(messagesScrollUiTimer);
  messagesScrollUiTimer = window.setTimeout(() => {
    el.classList.remove("messages-scrolling");
  }, 2000);
}

const historyBooting = computed(() => threadBooting(props.bot.name));
const hasHistory = computed(() =>
  (state.messages[props.bot.name] || []).some((m) => !m?.meta?.hidden_prompt),
);
const showEmpty = computed(() => !historyBooting.value && !hasHistory.value);
const loadingOlder = ref(false);

function revealThread() {
  if (router.currentRoute.value.query?.msg) {
    threadPlaced.value = true;
    return;
  }
  if (!hasHistory.value && historyBooting.value) {
    threadPlaced.value = true;
    return;
  }
  scrollMessagesToBottom(true);
}

async function fillIfShort() {
  const name = props.bot.name;
  let rounds = 0;
  while (rounds++ < 6 && threadHasMore(name)) {
    const el = scroller.value;
    if (!el || el.scrollHeight > el.clientHeight + 8) break;
    const added = await loadOlderMessages(name);
    if (!added) break;
    await nextTick();
  }
}

function onMessagesScroll() {
  stickToBottom.value = isNearBottom(scroller.value);
  pulseMessagesScrollbar();
  maybeLoadOlder();
}

async function maybeLoadOlder() {
  const el = scroller.value;
  const name = props.bot.name;
  if (!el || loadingOlder.value || !threadHasMore(name)) return;
  if (el.scrollHeight <= el.clientHeight + 8) return;
  if (el.scrollTop > 160) return;
  const prevHeight = el.scrollHeight;
  const prevTop = el.scrollTop;
  loadingOlder.value = true;
  stickToBottom.value = false;
  try {
    const added = await loadOlderMessages(name);
    await nextTick();
    const delta = el.scrollHeight - prevHeight;
    if (added && delta > 0) el.scrollTop = prevTop + delta;
  } finally {
    loadingOlder.value = false;
  }
}

/** @param {boolean} force ignore stickToBottom
 *  @param {boolean} [_absolute] kept for call sites; follow is always the true end */
function scrollMessagesToBottom(force = false, _absolute = false) {
  const el = scroller.value;
  if (!el) return;
  if (!force && !stickToBottom.value) return;
  stickToBottom.value = true;
  const top = absoluteScrollTop(el);
  if (Math.abs(top - el.scrollTop) > 1) el.scrollTop = top;
  threadPlaced.value = true;
}

/** Serialize composer POSTs so rapid 7/8/9/10 hit the API in type order. */
let sendChain = Promise.resolve();
/** In-flight composer sends (incl. waiting on the chain) — forces « En file » UI. */
let sendsPending = 0;
/** Monotonic order for queued bubbles (survives optimistic → server created_at swap). */
let queueOrdSeq = 0;

async function send() {
  const content = text.value.trim();
  const keptPending = pending.value.slice();
  const attachments = keptPending.map((p) => {
    if (p.kind === "file") {
      return { type: "file", name: p.name, path: p.path, url: p.url };
    }
    return p.dataUrl;
  });
  if ((!content && !attachments.length) || uploading.value) return;
  secretRefuseHint.value = "";
  stickToBottom.value = true;
  // Optimistic bubble — visible the instant send is pressed, before HTTP returns.
  const bot = props.bot.name;
  // Clear right away: the server call may start the agent and take a while.
  text.value = "";
  pending.value = [];
  clearComposerDraft(bot);
  clearComposerPending(bot);
  closeMentions();
  const tempId = `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const msgsNow = state.messages[bot] || [];
  const alreadyWaiting = msgsNow.some(
    (m) =>
      m?.role === "user" &&
      (m?.meta?.queued || String(m?.id || "").startsWith("tmp-"))
  );
  // Match server pre-queue: show « En file » immediately (no blue→queued flash).
  const agentLooksBusy =
    runLocked.value ||
    hasRunningTools.value ||
    msgsNow.some(
      (m) =>
        m?.role === "assistant" &&
        (m?.meta?.streaming || m?.meta?.status === "running")
    );
  // Another send already in flight → this one will park behind it.
  const optimisticQueued = agentLooksBusy || alreadyWaiting || sendsPending > 0;
  sendsPending += 1;
  const queueOrd = ++queueOrdSeq;
  const optimistic = {
    id: tempId,
    bot,
    conversation_id: "main",
    role: "user",
    content,
    attachments: attachments.map((a) =>
      typeof a === "string" ? { type: "image", url: a } : a
    ),
    meta: optimisticQueued
      ? { queued: true, queue_ord: queueOrd }
      : { queue_ord: queueOrd },
    created_at: new Date().toISOString(),
  };
  if (!state.messages[bot]) state.messages[bot] = [];
  state.messages[bot].push(optimistic);
  await nextTick();
  autosize();
  // True bottom so the just-sent bubble (incl. « En file ») is fully on screen.
  scrollMessagesToBottom(true, true);

  const run = async () => {
    try {
      const saved = await api.sendMessage(bot, content, attachments);
      const list = state.messages[bot] || [];
      // Remove every optimistic twin (SSE may already have inserted the real id).
      for (let i = list.length - 1; i >= 0; i--) {
        if (list[i]?.id === tempId) list.splice(i, 1);
      }
      if (saved?.id) {
        // Keep send-order stamp so the file does not jump when created_at swaps.
        const stamped = {
          ...saved,
          meta: {
            ...(saved.meta || {}),
            queue_ord:
              Number.isFinite(Number(saved.meta?.queue_ord))
                ? saved.meta.queue_ord
                : queueOrd,
          },
        };
        const existingIdx = list.findIndex((m) => m.id === stamped.id);
        if (existingIdx >= 0) {
          const prev = list[existingIdx];
          const prevOrd = Number(prev?.meta?.queue_ord);
          list[existingIdx] = {
            ...stamped,
            meta: {
              ...stamped.meta,
              queue_ord: Number.isFinite(Number(stamped.meta?.queue_ord))
                ? stamped.meta.queue_ord
                : Number.isFinite(prevOrd)
                  ? prevOrd
                  : queueOrd,
            },
          };
        } else list.push(stamped);
        // Same content under another tmp- id (setup / double-tap).
        for (let i = list.length - 1; i >= 0; i--) {
          const m = list[i];
          if (!m?.id || m.id === stamped.id) continue;
          if (!String(m.id).startsWith("tmp-")) continue;
          if (m.role === stamped.role && String(m.content || "") === String(stamped.content || "")) {
            list.splice(i, 1);
          }
        }
      }
      for (const p of keptPending) {
        if (p.preview) URL.revokeObjectURL(p.preview);
      }
    } catch (e) {
      const list = state.messages[bot] || [];
      const tempIdx = list.findIndex((m) => m.id === tempId);
      if (tempIdx >= 0) list.splice(tempIdx, 1);
      const code = e?.code || e?.data?.code || e?.data?.error_code || "";
      const isSecretRefuse =
        code === "secret_disclosure" ||
        /divulgation|vault secret|secret_disclosure/i.test(String(e?.message || ""));
      if (!text.value.trim()) text.value = content;
      if (!pending.value.length) pending.value = keptPending;
      else {
        for (const p of keptPending) {
          if (p.preview && !pending.value.includes(p)) URL.revokeObjectURL(p.preview);
        }
      }
      if (isSecretRefuse) {
        secretRefuseHint.value = t("chat.secretDisclosureRefuse");
      } else {
        alert(e.message || String(e));
      }
      await nextTick();
      autosize();
    } finally {
      sendsPending = Math.max(0, sendsPending - 1);
    }
    await nextTick();
    scrollMessagesToBottom(true, true);
    composer.value?.focus();
  };

  const wait = sendChain.then(run, run);
  sendChain = wait.then(
    () => undefined,
    () => undefined
  );
  await wait;
}

async function stop() {
  try {
    await api.stopBot(props.bot.name);
  } catch (e) {
    alert(e.message);
  }
}

watch(text, async (v) => {
  if (secretRefuseHint.value) secretRefuseHint.value = "";
  setComposerDraft(props.bot.name, v);
  await nextTick();
  autosize();
});

watch(
  pending,
  (items) => {
    setComposerPending(props.bot.name, items.slice());
  },
  { deep: true }
);

watch(
  () => state.composerRestore,
  async (v) => {
    if (!v || v.bot !== props.bot.name) return;
    const draft = String(v.text || "");
    state.composerRestore = null;
    if (!draft) return;
    text.value = draft;
    setComposerDraft(props.bot.name, draft);
    secretRefuseHint.value = t("chat.secretRestoredToComposer");
    await nextTick();
    autosize();
    composer.value?.focus();
  }
);

let scrollFollowRaf = 0;
watch(
  () =>
    [
      waitingForReply.value,
      (state.messages[props.bot.name] || [])
        .map((m) => `${m.id}:${m.content}:${m.meta?.status || ""}:${m.meta?.state || ""}`)
        .join("\0"),
    ].join("|"),
  async () => {
    // Never flip messages-placing mid-run: hiding the thread on each tool
    // update makes the conversation visibly jump/flicker.
    await nextTick();
    if (router.currentRoute.value.query?.msg) {
      threadPlaced.value = true;
      return;
    }
    if (!stickToBottom.value) return;
    // Coalesce rapid tool SSE bursts into one scroll per frame.
    if (scrollFollowRaf) cancelAnimationFrame(scrollFollowRaf);
    scrollFollowRaf = requestAnimationFrame(() => {
      scrollFollowRaf = 0;
      scrollMessagesToBottom(false);
    });
  }
);

watch(
  () => props.bot.name,
  async (next, prev) => {
    if (prev && prev !== next) {
      setComposerDraft(prev, text.value);
      setComposerPending(prev, pending.value.slice());
      text.value = getComposerDraft(next);
      pending.value = getComposerPending(next).slice();
      closeMentions();
      secretRefuseHint.value = "";
    }
    stickToBottom.value = true;
    threadPlaced.value = false;
    await nextTick();
    autosize();
    if (!hasHistory.value && historyBooting.value) {
      threadPlaced.value = true;
      return;
    }
    revealThread();
  }
);

watch(historyBooting, async (loading, was) => {
  if (loading || !was) return;
  await nextTick();
  if (stickToBottom.value) await fillIfShort();
  revealThread();
});

let composerMq;
function onComposerMqChange(e) {
  compactComposerPh.value = !!e.matches;
  nextTick(() => autosize());
}

onMounted(async () => {
  composerMq = window.matchMedia("(max-width: 720px)");
  compactComposerPh.value = composerMq.matches;
  composerMq.addEventListener("change", onComposerMqChange);
  await nextTick();
  autosize();
  revealThread();
});

watch(
  () => [props.bot.name, router.currentRoute.value.query?.msg],
  ([, msg]) => {
    const msgId = typeof msg === "string" ? msg : "";
    if (msgId) {
      stickToBottom.value = false;
      scrollToMessage(msgId);
    }
  },
  { immediate: true }
);

function onLightboxKey(e) {
  if (e.key === "Escape") closeLightbox();
}

watch(lightboxSrc, (src) => {
  if (src) window.addEventListener("keydown", onLightboxKey);
  else window.removeEventListener("keydown", onLightboxKey);
});

onBeforeUnmount(() => {
  // Keep drafts for this tab; do not revoke pending previews still stored in the map.
  setComposerDraft(props.bot.name, text.value);
  setComposerPending(props.bot.name, pending.value.slice());
  pending.value = [];
  if (flashTimer) clearTimeout(flashTimer);
  clearTimeout(messagesScrollUiTimer);
  clearTimeout(idleQueuedTimer);
  scroller.value?.classList.remove("messages-scrolling");
  window.removeEventListener("keydown", onLightboxKey);
  composerMq?.removeEventListener("change", onComposerMqChange);
});
</script>
