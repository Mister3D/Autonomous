"""Marshmallow schemas (source of OpenAPI component schemas)."""

from __future__ import annotations

from marshmallow import EXCLUDE, Schema, ValidationError, fields, pre_dump, validates_schema, validate


BOT_NAME_RE = r"^[a-z0-9][a-z0-9_-]{0,31}$"
CAPABILITIES = ("none", "terminal", "screen")
BOT_STATUSES = ("idle", "busy", "waiting", "error")
MSG_ROLES = ("user", "assistant", "system", "event")


class ErrorSchema(Schema):
    error = fields.Str(required=True)
    code = fields.Str(load_default=None)


class HealthSchema(Schema):
    ok = fields.Bool(required=True)
    version = fields.Str(required=True)


class LoginSchema(Schema):
    password = fields.Str(required=True, load_only=True)
    username = fields.Str(load_default="user")


class ChangePasswordSchema(Schema):
    current_password = fields.Str(required=True, load_only=True)
    new_password = fields.Str(
        required=True,
        load_only=True,
        validate=validate.Length(min=8, max=256),
    )


class AuthStatusSchema(Schema):
    authenticated = fields.Bool(required=True)
    password_set = fields.Bool(required=True)
    must_change_password = fields.Bool(dump_default=False)
    mono_user = fields.Bool(dump_default=True)


class LoginResultSchema(Schema):
    ok = fields.Bool(required=True)
    message = fields.Str()
    must_change_password = fields.Bool(dump_default=False)


class GuardSchema(Schema):
    review_every = fields.Integer(allow_none=True, load_default=None)
    max_actions = fields.Integer(allow_none=True, load_default=None)


class DeskSchema(Schema):
    state = fields.Str(required=True)
    container_id = fields.Str(allow_none=True)
    container_name = fields.Str(allow_none=True)  # autonomous-<uuid>
    image = fields.Str(allow_none=True)
    vnc_port = fields.Integer(allow_none=True)
    novnc_path = fields.Str(allow_none=True)
    mode = fields.Str(allow_none=True)  # always "screen" on new VMs
    internet = fields.Bool(allow_none=True)
    created_at = fields.Str(allow_none=True)
    last_error = fields.Str(allow_none=True)
    slept_at = fields.Str(allow_none=True)
    # Agent wait loop (vm_request_desk) — same idea as shell pending_*.
    pending_request_id = fields.Str(allow_none=True)
    pending_state = fields.Str(allow_none=True)  # pending | approved | denied


class BotSchema(Schema):
    id = fields.Str(required=True)
    name = fields.Str(required=True)
    label = fields.Str(required=True)
    capability = fields.Str(validate=validate.OneOf(CAPABILITIES))
    internet = fields.Bool()
    auto_sleep = fields.Bool()
    memory_access = fields.Bool()
    is_manager = fields.Bool()
    desk_last_active_at = fields.Str(allow_none=True)
    status = fields.Str(validate=validate.OneOf(BOT_STATUSES))
    model = fields.Str()
    pi_session_id = fields.Str()
    guard = fields.Nested(GuardSchema)
    desk = fields.Nested(DeskSchema, allow_none=True)
    last_message_at = fields.Str(allow_none=True)
    tokens_in = fields.Integer()
    tokens_out = fields.Integer()
    avatar = fields.Str()
    avatar_color = fields.Integer()
    companion_id = fields.Str(allow_none=True)
    companion_name = fields.Str()
    companion_online = fields.Bool()
    companion_egress = fields.Bool()
    companion_killswitch = fields.Bool()
    created_at = fields.Str()
    updated_at = fields.Str()


class BotCreateSchema(Schema):
    # Free-form display name (spaces / capitals OK). Technical id = slug or auto.
    name = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    slug = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(
            BOT_NAME_RE,
            error="slug: a-z, 0-9, _ ou - (max 32, commence par lettre/chiffre)",
        ),
    )
    label = fields.Str(load_default=None)
    internet = fields.Bool(load_default=True)
    memory_access = fields.Bool(
        load_default=True,
        metadata={
            "description": "Access shared household memory (core facts + browse). Default true."
        },
    )
    is_manager = fields.Bool(
        load_default=False,
        metadata={
            "description": (
                "Orchestrator: may list peers and delegate tasks without waiting. "
                "Only one Manager is allowed (409 manager_exists if another exists)."
            )
        },
    )
    model = fields.Str(load_default=None)
    avatar = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={"description": "Companion character id (optional; auto-picked if omitted)."},
    )
    avatar_color = fields.Integer(
        load_default=None,
        allow_none=True,
        metadata={"description": "Swatch index 0–17 (optional; default 0)."},
    )


class BotPatchSchema(Schema):
    label = fields.Str()
    internet = fields.Bool()
    auto_sleep = fields.Bool(
        metadata={
            "description": "Stop desk after 5 min idle (default true). Disable for long-running scripts."
        }
    )
    memory_access = fields.Bool(
        metadata={
            "description": "Shared memory access (core prompt + browse tools). Default true."
        }
    )
    is_manager = fields.Bool(
        metadata={
            "description": (
                "Orchestrator: peer list + async delegation (no blocking wait). "
                "Only one Manager allowed (409 manager_exists)."
            )
        }
    )
    model = fields.Str()
    guard = fields.Nested(GuardSchema)
    status = fields.Str(validate=validate.OneOf(BOT_STATUSES))
    avatar = fields.Str(
        metadata={"description": "Companion character id (avatar/characters/<id>)."}
    )
    avatar_color = fields.Integer(
        metadata={"description": "Swatch index 0–17 (0 = original drawing)."}
    )
    companion_id = fields.Str(
        allow_none=True,
        metadata={"description": "Paired companion this bot may use. Empty clears the link."},
    )
    companion_egress = fields.Bool(
        metadata={"description": "Route this bot's internet through its companion."},
    )
    companion_killswitch = fields.Bool(
        metadata={"description": "If egress is on and the companion is offline, cut this bot's external network."},
    )


class PiStatusSchema(Schema):
    installed = fields.Bool(required=True)
    ready = fields.Bool(required=True)
    reason = fields.Str(allow_none=True)
    version = fields.Str(allow_none=True)
    bin = fields.Str(allow_none=True)
    models_json = fields.Str()
    models_count = fields.Integer()
    doc_url = fields.Str()
    local_doc = fields.Str()


class PiModelSchema(Schema):
    provider = fields.Str(required=True)
    id = fields.Str(required=True)
    ref = fields.Str(required=True)
    label = fields.Str()


class CapabilitySchema(Schema):
    level = fields.Str(required=True, validate=validate.OneOf(CAPABILITIES))


class ChatFileAttachmentSchema(Schema):
    """File dropped / picked in chat → stored under ~/files/upload/<uuid>/."""

    type = fields.Str(required=True)
    name = fields.Str(required=True)
    path = fields.Str(required=True)
    url = fields.Str(required=True)
    size = fields.Integer(load_default=None)


class MessageSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    conversation_id = fields.Str()
    role = fields.Str(validate=validate.OneOf(MSG_ROLES))
    content = fields.Str(required=True)
    # str = pasted image URL ; dict = chat file under ~/files/upload/
    attachments = fields.List(fields.Raw())
    meta = fields.Dict()
    created_at = fields.Str()


class ReactionCreateSchema(Schema):
    emoji = fields.Str(required=True, validate=validate.Length(min=1, max=16))
    message_id = fields.Str(load_default=None)


class MessageCreateSchema(Schema):
    content = fields.Str(load_default="")
    attachments = fields.List(fields.Raw(), load_default=list)
    # Optional agent prompt override (stored bubble stays ``content``).
    prompt = fields.Str(load_default=None, allow_none=True)

    @validates_schema
    def require_content_or_attachments(self, data, **kwargs):
        if not (data.get("content") or "").strip() and not (data.get("attachments") or []):
            raise ValidationError(
                "content or attachments required",
                field_name="content",
            )


class MessageListQuerySchema(Schema):
    before = fields.Str(load_default=None)
    limit = fields.Integer(load_default=50, validate=validate.Range(min=1, max=200))


class TerminalExecSchema(Schema):
    command = fields.Str(required=True, validate=validate.Length(min=1))
    timeout = fields.Integer(load_default=30, validate=validate.Range(min=1, max=600))


class TerminalLogSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    command = fields.Str()
    exit_code = fields.Integer(allow_none=True)
    output = fields.Str()
    created_at = fields.Str()


class JobSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    kind = fields.Str()
    state = fields.Str()
    progress = fields.Integer()
    log = fields.List(fields.Str())
    error = fields.Str(allow_none=True)
    created_at = fields.Str()
    updated_at = fields.Str()


class DeskResetSchema(Schema):
    confirm = fields.Bool(required=True)


class DeskCreateSchema(Schema):
    """Options when provisioning the bot VM (shell and desktop together)."""

    class Meta:
        unknown = EXCLUDE

    internet = fields.Bool(load_default=True)


class DeskRequestSchema(Schema):
    """Agent asks the user to authorize creating the VM."""

    class Meta:
        unknown = EXCLUDE

    reason = fields.Str(load_default="", validate=validate.Length(max=500))


class DeskRequestResultSchema(Schema):
    ok = fields.Bool(required=True)
    deduped = fields.Bool()
    message_id = fields.Str()
    state = fields.Str()


class FilesQuerySchema(Schema):
    path = fields.Str(load_default=".")


class FileEntrySchema(Schema):
    name = fields.Str(required=True)
    path = fields.Str(required=True)
    is_dir = fields.Bool(required=True)
    size = fields.Integer(allow_none=True)
    modified_at = fields.Str(allow_none=True)


class FileMoveSchema(Schema):
    src = fields.Str(required=True, validate=validate.Length(min=1))
    dest = fields.Str(load_default=".")


class FileContentSchema(Schema):
    path = fields.Str(required=True)
    name = fields.Str()
    size = fields.Integer()
    content = fields.Str(required=True)
    encoding = fields.Str()


class FileWriteSchema(Schema):
    path = fields.Str(required=True, validate=validate.Length(min=1))
    content = fields.Str(load_default="")


class SettingsSchema(Schema):
    """Flat settings map (key → value)."""

    class Meta:
        unknown = "include"

    guard_review_every = fields.Integer(data_key="guard.review_every", allow_none=True)
    guard_max_actions = fields.Integer(data_key="guard.max_actions", allow_none=True)
    guard_max_images_per_prompt = fields.Integer(
        data_key="guard.max_images_per_prompt", allow_none=True
    )
    grounding_max_loops = fields.Integer(
        data_key="grounding.max_loops", allow_none=True
    )

    @pre_dump
    def _expose_dotted_keys(self, data, **kwargs):
        # Stored keys are dotted (`guard.review_every`). Field names are not,
        # and a dotted `attribute` would be read as a nested path.
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in self.fields.items():
            key = field.data_key or name
            if key in data and name not in out:
                out[name] = data[key]
        return out
    agent_backend = fields.Str()
    desktop_image = fields.Str()
    ack_unwired_agent = fields.Bool()
    locale = fields.Str()
    timezone = fields.Str(allow_none=True)
    first_chat_done = fields.Bool()
    first_chat_prefs_pending = fields.Str(allow_none=True)
    first_chat_onboarding = fields.Bool()
    update_channel = fields.Str(
        data_key="update.channel",
        allow_none=True,
        metadata={"description": "Self-update git branch: main | dev | custom"},
    )
    update_remote_url = fields.Str(
        data_key="update.remote_url",
        allow_none=True,
        metadata={"description": "Optional git remote URL for self-update (fork)"},
    )
    companions_enabled = fields.Bool(
        data_key="companions.enabled",
        allow_none=True,
        metadata={"description": "Allow public companion pairing requests"},
    )
    bots_default_model = fields.Str(
        data_key="bots.default_model",
        allow_none=True,
        metadata={
            "description": "Default Pi model ref (provider/id) when the Manager creates a bot without model="
        },
    )


class NovncInfoSchema(Schema):
    url = fields.Str(required=True)
    ws_path = fields.Str(required=True)
    vnc_port = fields.Integer(allow_none=True)
    state = fields.Str()


class ScreenshotCreateSchema(Schema):
    show_in_chat = fields.Bool(load_default=True)


class ScreenshotSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    path = fields.Str()
    url = fields.Str()
    width = fields.Integer()
    height = fields.Integer()
    bytes = fields.Integer()
    created_at = fields.Str()
    show_in_chat = fields.Bool()
    message_id = fields.Str(allow_none=True)


class OkSchema(Schema):
    ok = fields.Bool(required=True)
    message = fields.Str()


class BotPackageUsageSchema(Schema):
    """Disk footprint of one bot package (Details panel)."""

    bot = fields.Str(required=True)
    total_bytes = fields.Integer(required=True)
    host_bytes = fields.Integer(required=True)
    files_bytes = fields.Integer(required=True)
    screenshots_bytes = fields.Integer(required=True)
    browser_bytes = fields.Integer(required=True)
    shared_bytes = fields.Integer(required=True)
    chat_bytes = fields.Integer(required=True)
    messages = fields.Integer(required=True)
    agent_bytes = fields.Integer(required=True)
    downloads_bytes = fields.Integer(required=True)
    vm_bytes = fields.Integer(allow_none=True)
    vm_state = fields.Str(required=True)


class RetryUnprocessedSchema(Schema):
    ok = fields.Bool(required=True)
    action = fields.Str(
        metadata={
            "description": "drained | resumed | noop — what the retry did",
        }
    )
    queued = fields.Int()
    started = fields.Bool()


class BotMailSendSchema(Schema):
    to = fields.Str(required=True, metadata={"description": "Target bot name or @name"})
    content = fields.Str(
        load_default="",
        allow_none=True,
        metadata={"description": "Peer-facing brief (optional if attachments are set)"},
    )
    attachments = fields.List(
        fields.Str(),
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=10),
        metadata={
            "description": (
                "Optional paths under the sender's private ~/files to copy into the "
                "recipient's .autonomous/mail-inbox staging area"
            )
        },
    )
    expect_reply = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={
            "description": (
                "Manager only: wrap content as an async delegation and ask the peer "
                "to Tell @you back with this summary when done"
            )
        },
    )


class BotMailDelegateSchema(Schema):
    to = fields.Str(required=True, metadata={"description": "Worker bot name"})
    task = fields.Str(required=True, validate=validate.Length(min=1))
    expect_reply = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={"description": "What the worker should put in the Dit-à callback."},
    )


class BotMailPeerSchema(Schema):
    """Peer bot summary for managers (orchestration)."""

    name = fields.Str(required=True)
    label = fields.Str()
    status = fields.Str()
    capability = fields.Str()
    is_manager = fields.Bool()


class HouseholdBotSpecSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    model = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={"description": "Pi model ref or hint; falls back to bots.default_model"},
    )
    label = fields.Str(load_default=None, allow_none=True)
    slug = fields.Str(load_default=None, allow_none=True)
    internet = fields.Bool(load_default=True)
    memory_access = fields.Bool(load_default=True)
    avatar = fields.Str(load_default=None, allow_none=True)
    avatar_color = fields.Integer(load_default=None, allow_none=True)


class HouseholdCreateSchema(Schema):
    bots = fields.List(
        fields.Nested(HouseholdBotSpecSchema),
        required=True,
        validate=validate.Length(min=1, max=20),
    )


class HouseholdDeleteCreateSchema(Schema):
    bots = fields.List(
        fields.Str(),
        required=True,
        validate=validate.Length(min=1, max=50),
        metadata={"description": "Bot slugs to propose for deletion (checked by default)"},
    )
    prompt = fields.Str(load_default="", allow_none=True)
    title = fields.Str(load_default="", allow_none=True)


class HouseholdDeleteResolveSchema(Schema):
    action = fields.Str(
        required=True,
        validate=validate.OneOf(["confirm", "deny", "approve", "cancel"]),
    )
    bots = fields.List(
        fields.Str(),
        load_default=None,
        allow_none=True,
        metadata={"description": "Checked bot slugs when action=confirm"},
    )


class BotMailAskSchema(Schema):
    id = fields.Str(required=True)
    from_bot = fields.Str()
    to_bot = fields.Str()
    question = fields.Str()
    state = fields.Str()
    answer = fields.Str(allow_none=True)
    inbox_id = fields.Str(allow_none=True)
    created_at = fields.Str()
    answered_at = fields.Str(allow_none=True)


class BotMailInboxSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    from_bot = fields.Str(allow_none=True)
    kind = fields.Str()
    content = fields.Str()
    correlation_id = fields.Str(allow_none=True)
    state = fields.Str()
    created_at = fields.Str()
    delivered_at = fields.Str(allow_none=True)


class VaultInjectSchema(Schema):
    """Type/paste a granted vault field into the desk — secret never in response."""

    entry_id = fields.Str(required=True)
    field = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={"description": "Secret field id (password, api_key, …). Default: best guess."},
    )
    method = fields.Str(
        load_default="type",
        validate=validate.OneOf(("type", "paste")),
        metadata={"description": "type = keystrokes via VNC; paste = clipboard + Ctrl+Shift+V"},
    )


class VaultInjectResultSchema(Schema):
    ok = fields.Bool(required=True)
    bot = fields.Str()
    entry_id = fields.Str()
    field = fields.Str()
    method = fields.Str()
    chars = fields.Integer()
    secret_returned = fields.Bool()


class DeskClickSchema(Schema):
    x = fields.Integer(required=True)
    y = fields.Integer(required=True)
    button = fields.Str(
        load_default="left",
        validate=validate.OneOf(("left", "right", "middle", "double", "move")),
    )


class DeskClickResultSchema(Schema):
    ok = fields.Bool(required=True)
    bot = fields.Str()
    x = fields.Integer()
    y = fields.Integer()
    button = fields.Str()
    detail = fields.Str()
    page = fields.Str()


class DeskTypeSchema(Schema):
    text = fields.Str(required=True, validate=validate.Length(min=1, max=8000))
    method = fields.Str(
        load_default="type",
        validate=validate.OneOf(("type", "paste")),
    )


class DeskTypeResultSchema(Schema):
    ok = fields.Bool(required=True)
    bot = fields.Str()
    method = fields.Str()
    chars = fields.Integer()
    detail = fields.Str()


class DeskScrollSchema(Schema):
    dy = fields.Integer(required=True)
    x = fields.Integer(load_default=0)
    y = fields.Integer(load_default=0)


class DeskScrollResultSchema(Schema):
    ok = fields.Bool(required=True)
    bot = fields.Str()
    dy = fields.Integer()
    x = fields.Integer()
    y = fields.Integer()
    detail = fields.Str()
    page = fields.Str()


class DeskKeySchema(Schema):
    key = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    repeats = fields.Integer(load_default=1, validate=validate.Range(min=1, max=50))


class DeskKeyResultSchema(Schema):
    ok = fields.Bool(required=True)
    bot = fields.Str()
    key = fields.Str()
    repeats = fields.Integer()
    detail = fields.Str()
    page = fields.Str()


class DeskDragSchema(Schema):
    x = fields.Integer(required=True)
    y = fields.Integer(required=True)
    x2 = fields.Integer(required=True)
    y2 = fields.Integer(required=True)


class DeskDragResultSchema(Schema):
    ok = fields.Bool(required=True)
    bot = fields.Str()
    x = fields.Integer()
    y = fields.Integer()
    x2 = fields.Integer()
    y2 = fields.Integer()
    detail = fields.Str()
    page = fields.Str()


class BrowserResultSchema(Schema):
    """CDP payloads vary by command — keep declared fields + pass through extras."""

    class Meta:
        unknown = "include"

    ok = fields.Bool(required=True)
    bot = fields.Str()
    error = fields.Str()
    pages = fields.List(fields.Dict())
    navigated = fields.Str()
    url = fields.Str()
    title = fields.Str()
    html = fields.Str()
    text = fields.Str()
    truncated = fields.Bool()
    chars = fields.Integer()
    links = fields.List(fields.Dict())
    count = fields.Integer()
    elements = fields.List(fields.Dict())
    overlays = fields.List(fields.Dict())
    loaded = fields.Bool()
    timed_out = fields.Bool()
    ready_state = fields.Str(allow_none=True)
    waited_s = fields.Float()
    has_focus = fields.Bool()
    cleared = fields.List(fields.Str())
    origin = fields.Str()
    editable = fields.Bool()
    frames = fields.List(fields.Dict())
    slider_hints = fields.List(fields.Dict())
    query_fallback = fields.Bool()
    chrome_h = fields.Integer()
    iframe_offset = fields.Dict()
    scrollY = fields.Integer()
    innerHeight = fields.Integer()
    scrollHeight = fields.Integer()
    scrolled = fields.Dict()
    position = fields.Dict()
    selector = fields.Str()
    tag = fields.Str()
    value = fields.Raw()
    type = fields.Str()
    description = fields.Str()
    from_ = fields.Dict(data_key="from")


class BrowserNavigateSchema(Schema):
    url = fields.Str(required=True, validate=validate.Length(min=1, max=4000))


class BrowserHtmlSchema(Schema):
    max_chars = fields.Integer(load_default=12000, validate=validate.Range(min=500, max=100000))
    selector = fields.Str(load_default=None, allow_none=True)


class BrowserTextSchema(Schema):
    max_chars = fields.Integer(load_default=8000, validate=validate.Range(min=100, max=100000))


class BrowserLinksSchema(Schema):
    query = fields.Str(load_default=None, allow_none=True)
    max_links = fields.Integer(load_default=40, validate=validate.Range(min=1, max=200))


class BrowserWaitLoadSchema(Schema):
    timeout = fields.Float(load_default=15.0, validate=validate.Range(min=1, max=30))


class BrowserTabSchema(Schema):
    index = fields.Integer(load_default=0, validate=validate.Range(min=0, max=50))
    match = fields.Str(load_default="")


class BrowserScrollSchema(Schema):
    dy = fields.Integer(load_default=600)
    dx = fields.Integer(load_default=0)


class BrowserSnapshotSchema(Schema):
    max_elements = fields.Integer(
        load_default=60, validate=validate.Range(min=1, max=120)
    )
    query = fields.Str(load_default=None, allow_none=True)


class BrowserClickSelectorSchema(Schema):
    selector = fields.Str(required=True, validate=validate.Length(min=1, max=2000))


class BrowserEvalSchema(Schema):
    js = fields.Str(required=True, validate=validate.Length(min=1, max=8000))


class GroundLocateSchema(Schema):
    instruction = fields.Str(required=True, validate=validate.Length(min=1, max=2000))
    action_hint = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(
            ("click", "left_click", "right_click", "double", "drag", "scroll")
        ),
    )
    verify = fields.Bool(load_default=True)
    check_exists = fields.Bool(load_default=True)
    max_retries = fields.Integer(
        load_default=None,
        allow_none=True,
        validate=validate.Range(min=1, max=8),
    )
    show_in_chat = fields.Bool(load_default=True)


class ScreenDescribeSchema(Schema):
    question = fields.Str(
        load_default=None, allow_none=True, validate=validate.Length(max=1000)
    )
    show_in_chat = fields.Bool(load_default=False)


class ScreenDescribeResultSchema(Schema):
    ok = fields.Bool(required=True)
    text = fields.Str()
    screenshot_id = fields.Str(allow_none=True)
    model = fields.Str(allow_none=True)
    code = fields.Str(load_default=None, allow_none=True)


class GroundLocateResultSchema(Schema):
    ok = fields.Bool(required=True)
    status = fields.Str()
    action = fields.Str()
    x = fields.Integer()
    y = fields.Integer()
    x2 = fields.Integer()
    y2 = fields.Integer()
    direction = fields.Str()
    error = fields.Str()
    instruction = fields.Str()
    screenshot_id = fields.Str()
    image_size = fields.Dict()
    grounder_size = fields.Dict()
    grounder_raw = fields.Str()
    verifier = fields.Dict()
    attempt = fields.Integer()
    nudged = fields.Bool()
    max_loops = fields.Integer()
    loops = fields.List(fields.Dict())
    capture_url = fields.Str()


class ScheduleCreateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    cron = fields.Str(
        required=True,
        metadata={"description": "5-field cron in the user timezone (settings)"},
    )
    instruction = fields.Str(load_default="", validate=validate.Length(max=8000))
    recurring = fields.Bool(load_default=True)
    anchor_message_id = fields.Str(load_default=None, allow_none=True)
    enabled = fields.Bool(load_default=True)


class SchedulePatchSchema(Schema):
    name = fields.Str(validate=validate.Length(min=1, max=64))
    cron = fields.Str(
        metadata={"description": "5-field cron in the user timezone (settings)"}
    )
    instruction = fields.Str(validate=validate.Length(max=8000))
    recurring = fields.Bool()
    anchor_message_id = fields.Str(allow_none=True)
    enabled = fields.Bool()


class ScheduleSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    name = fields.Str()
    cron = fields.Str(metadata={"description": "5-field cron in the user timezone"})
    cron_utc = fields.Str(metadata={"description": "Stored UTC equivalent"})
    recurring = fields.Bool()
    instruction = fields.Str()
    anchor_message_id = fields.Str(allow_none=True)
    enabled = fields.Bool()
    next_run_at = fields.Str()
    next_run_local = fields.Str(
        metadata={"description": "Next fire as YYYY-MM-DD HH:MM in the user timezone"}
    )
    now_local = fields.Str(
        metadata={"description": "Current wall time YYYY-MM-DD HH:MM in the user timezone"}
    )
    last_run_at = fields.Str(allow_none=True)
    created_at = fields.Str()
    updated_at = fields.Str()
    timezone = fields.Str(metadata={"description": "User IANA timezone (settings), else host"})
    utc_offset = fields.Str(metadata={"description": "UTC offset of that timezone at read time"})


class WebhookCreateSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    instruction = fields.Str(load_default="", validate=validate.Length(max=8000))
    anchor_message_id = fields.Str(load_default=None, allow_none=True)
    enabled = fields.Bool(load_default=True)


class WebhookPatchSchema(Schema):
    name = fields.Str(validate=validate.Length(min=1, max=64))
    instruction = fields.Str(validate=validate.Length(max=8000))
    anchor_message_id = fields.Str(allow_none=True)
    enabled = fields.Bool()


class WebhookSchema(Schema):
    id = fields.Str(required=True)
    bot = fields.Str()
    name = fields.Str()
    token = fields.Str()
    instruction = fields.Str()
    anchor_message_id = fields.Str(allow_none=True)
    enabled = fields.Bool()
    created_at = fields.Str()
    updated_at = fields.Str()
    url_path = fields.Str(metadata={"description": "Fire path (/api/v1/hooks)"})
    url = fields.Str(metadata={"description": "Absolute fire URL (use with Bearer token)"})


class HookFireResultSchema(Schema):
    ok = fields.Bool(required=True)
    message_id = fields.Str()
    bot = fields.Str()
    queued = fields.Bool()
