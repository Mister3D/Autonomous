use crate::api::{self, PairStart};
use crate::config::{self, Config, McpServer};
use crate::tunnel::{self, Command, Status};
use eframe::egui;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::Duration;

struct Texts {
    title: &'static str,
    url: &'static str,
    name: &'static str,
    next: &'static str,
    code_hint: &'static str,
    waiting: &'static str,
    options: &'static str,
    mcp: &'static str,
    add: &'static str,
    save: &'static str,
    forget: &'static str,
    open: &'static str,
    quit: &'static str,
    connected: &'static str,
    disconnected: &'static str,
    kicker: &'static str,
    url_lead: &'static str,
    name_required: &'static str,
    options_lead: &'static str,
    mcp_name: &'static str,
    mcp_cmd: &'static str,
    mcp_args: &'static str,
    remove: &'static str,
    mcp_empty: &'static str,
    steps: [&'static str; 4],
    notify_title: &'static str,
    notify_badge: &'static str,
    notify_toast: &'static str,
    notify_sound: &'static str,
    notify_test: &'static str,
    notify_test_title: &'static str,
    notify_test_body: &'static str,
    notify_off: &'static str,
    notify_persist: &'static str,
    notify_persist_help: &'static str,
    toast_open: &'static str,
    toast_dismiss: &'static str,
}

fn texts() -> Texts {
    let fr = sys_locale().starts_with("fr");
    if fr {
        Texts {
            title: "Compagnon Autonomous",
            url: "URL de l'instance",
            name: "Nom de cet ordinateur",
            next: "Suivant",
            code_hint: "Dans Autonomous : Réglages → Compagnons → Autoriser ce code.",
            waiting: "En attente de l'autorisation…",
            options: "Options",
            mcp: "MCP sur cet ordinateur (commande + arguments)",
            add: "Ajouter un MCP",
            save: "Enregistrer",
            forget: "Oublier cet appareil",
            open: "Ouvrir",
            quit: "Quitter",
            connected: "Relié à l'instance",
            disconnected: "Hors ligne",
            kicker: "AUTONOMOUS",
            url_lead: "Indique l'adresse que ce PC peut joindre.",
            name_required: "Donne un nom à cet ordinateur.",
            options_lead: "Tu pourras changer ça plus tard.",
            mcp_name: "Nom",
            mcp_cmd: "Commande",
            mcp_args: "Arguments",
            remove: "Retirer",
            mcp_empty: "Aucun serveur MCP.",
            steps: ["Lien", "Code", "Options", "Actif"],
            notify_title: "Notifications",
            notify_badge: "Pastille sur l'icône près de l'horloge",
            notify_toast: "Message à l'écran",
            notify_sound: "Son",
            notify_test: "Tester la notification",
            notify_test_title: "Compagnon Autonomous",
            notify_test_body: "Ceci est une notification de test.",
            notify_off: "Coche au moins une option de notification.",
            notify_persist: "Garder les notifications à l'écran",
            notify_persist_help: "Elles restent jusqu'à un clic : sur la notification pour l'ouvrir, ou sur X pour la fermer.",
            toast_open: "Ouvrir",
            toast_dismiss: "Fermer",
        }
    } else {
        Texts {
            title: "Autonomous companion",
            url: "Instance URL",
            name: "Name of this computer",
            next: "Next",
            code_hint: "In Autonomous: Settings → Companions → Approve this code.",
            waiting: "Waiting for approval…",
            options: "Options",
            mcp: "MCP on this computer (command + arguments)",
            add: "Add an MCP",
            save: "Save",
            forget: "Forget this device",
            open: "Open",
            quit: "Quit",
            connected: "Connected to the instance",
            disconnected: "Offline",
            kicker: "AUTONOMOUS",
            url_lead: "Use the address this PC can reach.",
            name_required: "Give this computer a name.",
            options_lead: "You can change this later.",
            mcp_name: "Name",
            mcp_cmd: "Command",
            mcp_args: "Arguments",
            remove: "Remove",
            mcp_empty: "No MCP server.",
            steps: ["Link", "Code", "Options", "Live"],
            notify_title: "Notifications",
            notify_badge: "Badge on the icon by the clock",
            notify_toast: "Message on screen",
            notify_sound: "Sound",
            notify_test: "Test notification",
            notify_test_title: "Autonomous companion",
            notify_test_body: "This is a test notification.",
            notify_off: "Turn on at least one notification option.",
            notify_persist: "Keep notifications on screen",
            notify_persist_help: "They stay until you click them to open, or click X to dismiss.",
            toast_open: "Open",
            toast_dismiss: "Dismiss",
        }
    }
}

fn sys_locale() -> String {
    std::env::var("LANG")
        .or_else(|_| std::env::var("LC_ALL"))
        .unwrap_or_else(|_| {
            if cfg!(windows) {
                "fr".into()
            } else {
                "en".into()
            }
        })
        .to_lowercase()
}

enum Step {
    Url,
    Code,
    Options,
    Run,
}

enum PairEvent {
    Started(PairStart),
    Approved { device_id: String, device_token: String },
    Failed(String),
    Status(String),
}

pub struct CompanionApp {
    texts: Texts,
    config: Config,
    step: Step,
    name: String,
    error: String,
    note: String,
    online: bool,
    pair_rx: Option<Receiver<PairEvent>>,
    cmd_tx: Option<Sender<Command>>,
    status_rx: Option<Receiver<Status>>,
    tray: Option<tray_icon::TrayIcon>,
    open_id: Option<tray_icon::menu::MenuId>,
    quit_id: Option<tray_icon::menu::MenuId>,
    quit: bool,
    alert: bool,
    alert_url: String,
    click_tx: Sender<String>,
    click_rx: Receiver<String>,
}

impl CompanionApp {
    fn new() -> Self {
        let config = config::load();
        let paired = !config.device_token.is_empty();
        let (click_tx, click_rx) = mpsc::channel();
        let mut app = Self {
            texts: texts(),
            name: config::default_device_name(),
            step: if paired { Step::Run } else { Step::Url },
            config,
            error: String::new(),
            note: String::new(),
            online: false,
            pair_rx: None,
            cmd_tx: None,
            status_rx: None,
            tray: None,
            open_id: None,
            quit_id: None,
            quit: false,
            alert: false,
            alert_url: String::new(),
            click_tx,
            click_rx,
        };
        app.install_tray();
        if paired {
            app.start_tunnel();
        }
        app
    }

    fn install_tray(&mut self) {
        use tray_icon::menu::{Menu, MenuItem};
        use tray_icon::TrayIconBuilder;
        let open = MenuItem::new(self.texts.open, true, None);
        let quit = MenuItem::new(self.texts.quit, true, None);
        self.open_id = Some(open.id().clone());
        self.quit_id = Some(quit.id().clone());
        let menu = Menu::new();
        let _ = menu.append(&open);
        let _ = menu.append(&quit);
        let rgba = mark_pixels(TRAY_ICON, false);
        let Ok(icon) = tray_icon::Icon::from_rgba(rgba, TRAY_ICON, TRAY_ICON) else {
            return;
        };
        self.tray = TrayIconBuilder::new()
            .with_menu(Box::new(menu))
            .with_menu_on_left_click(false)
            .with_tooltip(self.texts.title)
            .with_icon(icon)
            .build()
            .ok();
    }

    fn open_browser(&self) {
        let url = self.config.instance_url.trim();
        if url.is_empty() {
            return;
        }
        open_url(&self.config, url);
    }

    fn present_alert(&mut self, title: &str, body: &str, bot: &str) {
        self.fire_alert(title, body, bot, false);
    }

    fn test_notification(&mut self) {
        if !self.config.notify_badge && !self.config.notify_toast && !self.config.notify_sound {
            self.note = self.texts.notify_off.into();
            return;
        }
        self.fire_alert(
            self.texts.notify_test_title,
            self.texts.notify_test_body,
            "",
            true,
        );
    }

    fn fire_alert(&mut self, title: &str, body: &str, bot: &str, report: bool) {
        self.note = if body.is_empty() {
            title.to_string()
        } else {
            format!("{title} — {body}")
        };
        let open = config::discussion_url(&self.config.instance_url, bot);
        if !open.is_empty() {
            self.alert_url = open.clone();
        }
        if self.config.notify_badge {
            self.alert = true;
            self.apply_tray_icon();
            if let Some(tray) = &self.tray {
                let tip = if body.is_empty() {
                    title.to_string()
                } else {
                    format!("{title}\n{body}")
                };
                let _ = tray.set_tooltip(Some(tip));
            }
        }
        if self.config.notify_toast {
            let title = title.to_string();
            let body = body.to_string();
            let sound = self.config.notify_sound;
            let clicks = self.click_tx.clone();
            let persist = self.config.persistent_notifications;
            let labels = (self.texts.toast_open, self.texts.toast_dismiss);
            if report {
                if let Err(err) = show_toast(&title, &body, sound, persist, labels, open, clicks) {
                    self.error = err;
                }
            } else {
                thread::spawn(move || {
                    let _ = show_toast(&title, &body, sound, persist, labels, open, clicks);
                });
            }
        } else if self.config.notify_sound {
            ding();
        }
    }

    fn clear_alert(&mut self) {
        if !self.alert {
            return;
        }
        self.alert = false;
        self.alert_url.clear();
        self.apply_tray_icon();
        if let Some(tray) = &self.tray {
            let _ = tray.set_tooltip(Some(self.texts.title));
        }
    }

    fn apply_tray_icon(&self) {
        let Some(tray) = &self.tray else { return };
        let Ok(icon) = tray_icon::Icon::from_rgba(mark_pixels(TRAY_ICON, self.alert), TRAY_ICON, TRAY_ICON) else {
            return;
        };
        let _ = tray.set_icon(Some(icon));
    }

    fn start_tunnel(&mut self) {
        if self.cmd_tx.is_some() {
            return;
        }
        let (cmd_tx, cmd_rx) = mpsc::channel();
        let (status_tx, status_rx) = mpsc::channel();
        let config = self.config.clone();
        thread::spawn(move || tunnel::serve(config, cmd_rx, status_tx));
        self.cmd_tx = Some(cmd_tx);
        self.status_rx = Some(status_rx);
    }

    fn begin_pair(&mut self) {
        self.error.clear();
        let instance = match config::normalize_url(&self.config.instance_url) {
            Ok(url) => url,
            Err(err) => {
                self.error = err;
                return;
            }
        };
        self.config.instance_url = instance.clone();
        let name = self.name.trim().to_string();
        if name.is_empty() {
            self.error = self.texts.name_required.into();
            return;
        }
        let (tx, rx) = mpsc::channel();
        self.pair_rx = Some(rx);
        self.step = Step::Code;
        thread::spawn(move || {
            let started = match api::pair(&instance, &name) {
                Ok(started) => started,
                Err(err) => {
                    let _ = tx.send(PairEvent::Failed(err));
                    return;
                }
            };
            let pair_id = started.pair_id.clone();
            let secret = started.poll_secret.clone();
            let _ = tx.send(PairEvent::Started(started));
            for _ in 0..450 {
                thread::sleep(Duration::from_secs(2));
                match api::poll(&instance, &pair_id, &secret) {
                    Ok(polled) if polled.status == "approved" => {
                        if let Some(token) = polled.device_token {
                            let _ = tx.send(PairEvent::Approved {
                                device_id: polled.device_id.unwrap_or_default(),
                                device_token: token,
                            });
                            return;
                        }
                        let _ = tx.send(PairEvent::Status(polled.status));
                    }
                    Ok(polled) if polled.status == "denied" || polled.status == "expired" => {
                        let _ = tx.send(PairEvent::Failed(polled.status));
                        return;
                    }
                    Ok(polled) => {
                        let _ = tx.send(PairEvent::Status(polled.status));
                    }
                    Err(err) => {
                        let _ = tx.send(PairEvent::Failed(err));
                        return;
                    }
                }
            }
            let _ = tx.send(PairEvent::Failed("expired".into()));
        });
    }

    fn drain_pair(&mut self) {
        let Some(rx) = self.pair_rx.as_ref() else {
            return;
        };
        while let Ok(event) = rx.try_recv() {
            match event {
                PairEvent::Started(started) => {
                    self.note = started.user_code;
                }
                PairEvent::Approved { device_id, device_token } => {
                    self.config.device_id = device_id;
                    self.config.device_token = device_token;
                    let _ = config::save(&self.config);
                    self.step = Step::Options;
                    self.error.clear();
                }
                PairEvent::Failed(err) => {
                    self.error = err;
                    self.step = Step::Url;
                }
                PairEvent::Status(status) => {
                    if self.note.is_empty() {
                        self.note = status;
                    }
                }
            }
        }
    }

    fn drain_clicks(&mut self) {
        while let Ok(url) = self.click_rx.try_recv() {
            open_url(&self.config, &url);
            self.clear_alert();
            self.alert_url.clear();
        }
    }

    fn drain_status(&mut self) {
        let events = {
            let Some(rx) = self.status_rx.as_ref() else {
                return;
            };
            let mut events = Vec::new();
            while let Ok(event) = rx.try_recv() {
                events.push(event);
            }
            events
        };
        for event in events {
            match event {
                Status::Connected => {
                    self.online = true;
                    self.note = self.texts.connected.into();
                }
                Status::Disconnected(message) => {
                    self.online = false;
                    self.note = format!("{} — {message}", self.texts.disconnected);
                }
                Status::Note(message) => self.error = message,
                Status::Alert { title, body, bot } => self.present_alert(&title, &body, &bot),
            }
        }
    }

    fn save_options(&mut self) {
        self.error.clear();
        if let Err(err) = config::save(&self.config) {
            self.error = err;
            return;
        }
        self.start_tunnel();
        if let Err(err) = api::set_options(&self.config) {
            self.error = err;
            return;
        }
        if let Some(tx) = &self.cmd_tx {
            let _ = tx.send(Command::Mcp(self.config.mcp.clone()));
        }
        self.step = Step::Run;
    }

    fn forget(&mut self) {
        let _ = api::forget(&self.config);
        if let Some(tx) = self.cmd_tx.take() {
            let _ = tx.send(Command::Shutdown);
        }
        self.status_rx = None;
        self.config.device_token.clear();
        self.config.device_id.clear();
        self.config.egress = false;
        self.config.killswitch = false;
        let _ = config::save(&self.config);
        self.online = false;
        self.step = Step::Url;
    }

    fn poll_tray(&mut self, ctx: &egui::Context) {
        use tray_icon::menu::MenuEvent;
        use tray_icon::{MouseButton, MouseButtonState, TrayIconEvent};
        while let Ok(event) = TrayIconEvent::receiver().try_recv() {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                if self.alert_url.is_empty() {
                    self.clear_alert();
                    self.open_browser();
                } else {
                    let url = self.alert_url.clone();
                    self.clear_alert();
                    open_url(&self.config, &url);
                }
            }
        }
        while let Ok(event) = MenuEvent::receiver().try_recv() {
            if Some(&event.id) == self.quit_id.as_ref() {
                self.quit = true;
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            } else if Some(&event.id) == self.open_id.as_ref() {
                ctx.send_viewport_cmd(egui::ViewportCommand::Visible(true));
                ctx.send_viewport_cmd(egui::ViewportCommand::Focus);
            }
        }
    }
}

const INK: egui::Color32 = egui::Color32::from_rgb(28, 28, 30);
const MUTED: egui::Color32 = egui::Color32::from_rgb(142, 142, 147);
const ACCENT: egui::Color32 = egui::Color32::from_rgb(240, 140, 18);
const PAPER: egui::Color32 = egui::Color32::from_rgb(255, 255, 255);
const CANVAS: egui::Color32 = egui::Color32::from_rgb(246, 245, 242);
const LINE: egui::Color32 = egui::Color32::from_rgb(231, 231, 235);
const OK: egui::Color32 = egui::Color32::from_rgb(47, 158, 98);
const DANGER: egui::Color32 = egui::Color32::from_rgb(197, 52, 52);

const WINDOW_ICON: u32 = 256;
const TRAY_ICON: u32 = 64;

fn mark_pixels(size: u32, alert: bool) -> Vec<u8> {
    let n = size as usize;
    let mut rgba = vec![0u8; n * n * 4];
    let s = size as f32;
    let samples = 3i32;
    let sample_n = (samples * samples) as f32;
    for y in 0..n {
        for x in 0..n {
            let mut red = 0.0f32;
            let mut green = 0.0f32;
            let mut blue = 0.0f32;
            let mut alpha = 0.0f32;
            for sy in 0..samples {
                for sx in 0..samples {
                    let px = x as f32 + (sx as f32 + 0.5) / samples as f32;
                    let py = y as f32 + (sy as f32 + 0.5) / samples as f32;
                    let nx = (px - s * 0.5) / s;
                    let ny = (py - s * 0.5) / s;
                    let disc = (nx * nx + ny * ny).sqrt() - 0.46;
                    let left = seg(nx, ny, 0.0, -0.30, -0.22, 0.28) - 0.058;
                    let right = seg(nx, ny, 0.0, -0.30, 0.22, 0.28) - 0.058;
                    let bar = seg(nx, ny, -0.105, 0.05, 0.105, 0.05) - 0.036;
                    let letter = left.min(right).min(bar);
                    let (sr, sg, sb, sa) = shade(disc, letter, alert, nx, ny, s);
                    red += sr;
                    green += sg;
                    blue += sb;
                    alpha += sa;
                }
            }
            let i = (y * n + x) * 4;
            rgba[i] = (red / sample_n).round() as u8;
            rgba[i + 1] = (green / sample_n).round() as u8;
            rgba[i + 2] = (blue / sample_n).round() as u8;
            rgba[i + 3] = (alpha / sample_n * 255.0).round() as u8;
        }
    }
    rgba
}

fn seg(px: f32, py: f32, ax: f32, ay: f32, bx: f32, by: f32) -> f32 {
    let abx = bx - ax;
    let aby = by - ay;
    let ab2 = abx * abx + aby * aby;
    let t = if ab2 == 0.0 {
        0.0
    } else {
        (((px - ax) * abx + (py - ay) * aby) / ab2).clamp(0.0, 1.0)
    };
    let dx = px - (ax + abx * t);
    let dy = py - (ay + aby * t);
    (dx * dx + dy * dy).sqrt()
}

fn shade(disc: f32, letter: f32, alert: bool, nx: f32, ny: f32, size: f32) -> (f32, f32, f32, f32) {
    let aa = 0.65 / size;
    let cover = |d: f32| (0.5 - d / aa).clamp(0.0, 1.0);
    let disc_c = cover(disc);
    let letter_c = cover(letter);
    let badge_c = if alert {
        let dx = nx - 0.30;
        let dy = ny + 0.30;
        cover((dx * dx + dy * dy).sqrt() - 0.105)
    } else {
        0.0
    };
    if disc_c <= 0.0 && badge_c <= 0.0 {
        return (0.0, 0.0, 0.0, 0.0);
    }
    let mut red = 240.0f32;
    let mut green = 140.0f32;
    let mut blue = 18.0f32;
    let mut alpha = disc_c;
    let ink = letter_c * disc_c;
    red += (255.0 - red) * ink;
    green += (255.0 - green) * ink;
    blue += (255.0 - blue) * ink;
    if badge_c > 0.0 {
        red += (197.0 - red) * badge_c;
        green += (52.0 - green) * badge_c;
        blue += (52.0 - blue) * badge_c;
        alpha += (1.0 - alpha) * badge_c;
    }
    (red, green, blue, alpha)
}

fn show_toast(
    title: &str,
    body: &str,
    sound: bool,
    persist: bool,
    labels: (&str, &str),
    open: String,
    clicks: Sender<String>,
) -> Result<(), String> {
    let mut note = notify_rust::Notification::new();
    note.summary(title).body(body).appname("Autonomous");
    if sound {
        note.sound_name("Default");
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    note.action("default", labels.0);
    // Persistent: Windows maps Critical urgency to scenario="reminder" (stays until the
    // user acts; needs at least one button). Linux: Critical + no timeout. macOS: no-op.
    if persist {
        note.timeout(notify_rust::Timeout::Never);
        #[cfg(any(windows, all(unix, not(target_os = "macos"))))]
        note.urgency(notify_rust::Urgency::Critical);
        #[cfg(windows)]
        {
            note.action("open", labels.0);
            note.action("dismiss", labels.1);
        }
    }
    #[cfg(target_os = "macos")]
    let _ = labels;
    let handle = match note.show() {
        Ok(handle) => handle,
        Err(err) => {
            if sound {
                ding();
            }
            return Err(err.to_string());
        }
    };
    if open.is_empty() {
        return Ok(());
    }
    thread::spawn(move || {
        let _ = handle.wait_for_response(move |response: &notify_rust::NotificationResponse| {
            let open_clicked = match response {
                notify_rust::NotificationResponse::Action(key) => key == "open",
                _ => false,
            };
            if response.is_default_action() || open_clicked {
                let _ = clicks.send(open.clone());
            }
        });
    });
    Ok(())
}

fn ding() {
    #[cfg(windows)]
    unsafe {
        #[link(name = "user32")]
        extern "system" {
            fn MessageBeep(kind: u32) -> i32;
        }
        MessageBeep(0x40);
    }
    #[cfg(target_os = "macos")]
    {
        let _ = std::process::Command::new("afplay")
            .arg("/System/Library/Sounds/Glass.aiff")
            .spawn();
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let _ = std::process::Command::new("paplay")
            .arg("/usr/share/sounds/freedesktop/stereo/message.oga")
            .spawn();
    }
}

fn open_url(config: &crate::config::Config, url: &str) {
    if let Some(bot) = config::discussion_bot(&config.instance_url, url) {
        if !config.device_token.is_empty() && api::focus_open(config, &bot).unwrap_or(false) {
            focus_existing_page();
            return;
        }
    }
    shell_open(url);
}

#[cfg(windows)]
fn focus_existing_page() {
    #[link(name = "user32")]
    extern "system" {
        fn EnumWindows(
            cb: extern "system" fn(*mut std::ffi::c_void, isize) -> i32,
            lparam: isize,
        ) -> i32;
        fn GetWindowTextW(hwnd: *mut std::ffi::c_void, buf: *mut u16, max: i32) -> i32;
        fn IsWindowVisible(hwnd: *mut std::ffi::c_void) -> i32;
        fn SetForegroundWindow(hwnd: *mut std::ffi::c_void) -> i32;
        fn ShowWindow(hwnd: *mut std::ffi::c_void, cmd: i32) -> i32;
        fn BringWindowToTop(hwnd: *mut std::ffi::c_void) -> i32;
        fn GetWindowThreadProcessId(hwnd: *mut std::ffi::c_void, pid: *mut u32) -> u32;
        fn GetCurrentThreadId() -> u32;
        fn AttachThreadInput(from: u32, to: u32, attach: i32) -> i32;
    }
    extern "system" fn each(hwnd: *mut std::ffi::c_void, lparam: isize) -> i32 {
        unsafe {
            if IsWindowVisible(hwnd) == 0 {
                return 1;
            }
            let mut buf = [0u16; 512];
            let n = GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32);
            if n <= 0 {
                return 1;
            }
            let title = String::from_utf16_lossy(&buf[..n as usize]);
            if title.contains("\u{00b7} Autonomous") {
                *(lparam as *mut *mut std::ffi::c_void) = hwnd;
                return 0;
            }
            1
        }
    }
    unsafe {
        let mut found: *mut std::ffi::c_void = std::ptr::null_mut();
        EnumWindows(each, &mut found as *mut _ as isize);
        if found.is_null() {
            return;
        }
        ShowWindow(found, 9);
        let target = GetWindowThreadProcessId(found, std::ptr::null_mut());
        let mine = GetCurrentThreadId();
        AttachThreadInput(mine, target, 1);
        BringWindowToTop(found);
        SetForegroundWindow(found);
        AttachThreadInput(mine, target, 0);
    }
}

#[cfg(not(windows))]
fn focus_existing_page() {}

fn shell_open(url: &str) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = std::process::Command::new("cmd")
            .args(["/C", "start", "", url])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn();
    }
    #[cfg(target_os = "macos")]
    {
        let _ = std::process::Command::new("open").arg(url).spawn();
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let _ = std::process::Command::new("xdg-open").arg(url).spawn();
    }
}

fn apply_theme(ctx: &egui::Context) {
    let mut style = (*ctx.style()).clone();
    style.spacing.item_spacing = egui::vec2(8.0, 10.0);
    style.spacing.button_padding = egui::vec2(14.0, 8.0);
    style.text_styles.insert(
        egui::TextStyle::Body,
        egui::FontId::new(15.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Button,
        egui::FontId::new(15.0, egui::FontFamily::Proportional),
    );
    style.text_styles.insert(
        egui::TextStyle::Monospace,
        egui::FontId::new(28.0, egui::FontFamily::Monospace),
    );
    let mut visuals = egui::Visuals::light();
    visuals.window_fill = CANVAS;
    visuals.panel_fill = CANVAS;
    visuals.extreme_bg_color = PAPER;
    visuals.faint_bg_color = CANVAS;
    visuals.widgets.noninteractive.fg_stroke.color = INK;
    visuals.widgets.noninteractive.bg_stroke = egui::Stroke::new(1.0_f32, LINE);
    let radius = egui::CornerRadius::same(10);
    for widget in [
        &mut visuals.widgets.noninteractive,
        &mut visuals.widgets.inactive,
        &mut visuals.widgets.hovered,
        &mut visuals.widgets.active,
        &mut visuals.widgets.open,
    ] {
        widget.corner_radius = radius;
    }
    visuals.widgets.inactive.bg_fill = PAPER;
    visuals.widgets.inactive.weak_bg_fill = CANVAS;
    visuals.widgets.inactive.fg_stroke.color = INK;
    visuals.widgets.hovered.bg_fill = egui::Color32::from_rgb(255, 244, 230);
    visuals.widgets.hovered.weak_bg_fill = egui::Color32::from_rgb(255, 244, 230);
    visuals.selection.bg_fill = ACCENT;
    visuals.selection.stroke.color = PAPER;
    visuals.hyperlink_color = ACCENT;
    style.visuals = visuals;
    ctx.set_style(style);
}

fn card_frame() -> egui::Frame {
    egui::Frame::default()
        .fill(PAPER)
        .stroke(egui::Stroke::new(1.0_f32, LINE))
        .corner_radius(egui::CornerRadius::same(16))
        .inner_margin(egui::Margin::same(18))
}

fn show_card(ui: &mut egui::Ui, add: impl FnOnce(&mut egui::Ui)) {
    card_frame().show(ui, |ui| {
        ui.set_min_width(ui.available_width());
        add(ui);
    });
}

enum Btn {
    Primary,
    Normal,
    Danger,
}

fn web_button(ui: &mut egui::Ui, label: &str, kind: Btn, width: Option<f32>) -> egui::Response {
    let font = egui::FontId::new(14.0, egui::FontFamily::Proportional);
    let galley = ui
        .painter()
        .layout_no_wrap(label.to_owned(), font.clone(), INK);
    let width = width.unwrap_or_else(|| galley.size().x + 22.0);
    let (rect, response) = ui.allocate_exact_size(egui::vec2(width, 34.0), egui::Sense::click());
    let hovered = response.hovered();
    let (fill, text, stroke) = match kind {
        Btn::Primary => (
            if hovered {
                egui::Color32::from_rgb(221, 125, 11)
            } else {
                ACCENT
            },
            PAPER,
            egui::Stroke::NONE,
        ),
        Btn::Normal => (
            if hovered { CANVAS } else { PAPER },
            INK,
            egui::Stroke::new(1.0_f32, LINE),
        ),
        Btn::Danger => (
            if hovered {
                egui::Color32::from_rgb(253, 242, 242)
            } else {
                PAPER
            },
            DANGER,
            egui::Stroke::new(1.0_f32, egui::Color32::from_rgb(240, 201, 201)),
        ),
    };
    ui.painter().rect(
        rect,
        egui::CornerRadius::same(8),
        fill,
        stroke,
        egui::StrokeKind::Inside,
    );
    ui.painter().text(
        rect.center(),
        egui::Align2::CENTER_CENTER,
        label,
        font,
        text,
    );
    response
}

impl eframe::App for CompanionApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        ctx.request_repaint_after(Duration::from_millis(200));
        self.drain_pair();
        self.drain_status();
        self.drain_clicks();
        self.poll_tray(ctx);
        if ctx.input(|i| i.viewport().close_requested()) && !self.quit {
            if !self.config.device_token.is_empty() {
                ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
                ctx.send_viewport_cmd(egui::ViewportCommand::Visible(false));
            }
        }
        egui::CentralPanel::default().show(ctx, |ui| {
            let width = ui.available_width().min(440.0);
            let spare = (ui.available_width() - width).max(0.0) / 2.0;
            ui.horizontal(|ui| {
                ui.add_space(spare);
                ui.vertical(|ui| {
                    ui.set_width(width);
                    ui.add_space(8.0);
                    self.header(ui);
                    ui.add_space(16.0);
                    if !self.error.is_empty() {
                        self.error_banner(ui);
                        ui.add_space(12.0);
                    }
                    match self.step {
                        Step::Url => self.ui_url(ui),
                        Step::Code => self.ui_code(ui),
                        Step::Options => self.ui_options(ui),
                        Step::Run => self.ui_run(ui),
                    }
                });
            });
        });
    }
}

impl CompanionApp {
    fn header(&self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let (rect, _) = ui.allocate_exact_size(egui::vec2(36.0, 36.0), egui::Sense::hover());
            ui.painter().circle_filled(rect.center(), 18.0, ACCENT);
            ui.painter().text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                "A",
                egui::FontId::new(18.0, egui::FontFamily::Proportional),
                PAPER,
            );
            ui.vertical(|ui| {
                ui.label(
                    egui::RichText::new(self.texts.kicker)
                        .size(11.0)
                        .color(MUTED)
                        .strong(),
                );
                ui.label(egui::RichText::new(self.texts.title).size(22.0).strong().color(INK));
            });
        });
        ui.add_space(14.0);
        let current = match self.step {
            Step::Url => 0,
            Step::Code => 1,
            Step::Options => 2,
            Step::Run => 3,
        };
        ui.columns(4, |cols| {
            for (index, col) in cols.iter_mut().enumerate() {
                let on = index <= current;
                let (rect, _) =
                    col.allocate_exact_size(egui::vec2(col.available_width(), 4.0), egui::Sense::hover());
                col.painter()
                    .rect_filled(rect, 2.0, if on { ACCENT } else { LINE });
                col.add_space(6.0);
                col.label(
                    egui::RichText::new(self.texts.steps[index])
                        .size(12.0)
                        .color(if index == current { INK } else { MUTED }),
                );
            }
        });
    }

    fn error_banner(&self, ui: &mut egui::Ui) {
        egui::Frame::default()
            .fill(egui::Color32::from_rgb(253, 242, 242))
            .stroke(egui::Stroke::new(1.0_f32, DANGER))
            .corner_radius(egui::CornerRadius::same(12))
            .inner_margin(egui::Margin::same(12))
            .show(ui, |ui| {
                ui.label(egui::RichText::new(&self.error).color(DANGER));
            });
    }

    fn primary(&self, ui: &mut egui::Ui, label: &str) -> egui::Response {
        web_button(ui, label, Btn::Primary, Some(ui.available_width()))
    }

    fn field(ui: &mut egui::Ui, label: &str, value: &mut String) {
        ui.label(egui::RichText::new(label).size(13.0).strong().color(INK));
        ui.add(
            egui::TextEdit::singleline(value)
                .desired_width(f32::INFINITY)
                .margin(egui::Margin::symmetric(10, 8)),
        );
    }

    fn ui_url(&mut self, ui: &mut egui::Ui) {
        ui.label(egui::RichText::new(self.texts.url_lead).color(MUTED));
        ui.add_space(8.0);
        show_card(ui, |ui| {
            Self::field(ui, self.texts.url, &mut self.config.instance_url);
            ui.add_space(8.0);
            Self::field(ui, self.texts.name, &mut self.name);
        });
        ui.add_space(16.0);
        if self.primary(ui, self.texts.next).clicked() {
            self.begin_pair();
        }
    }

    fn ui_code(&mut self, ui: &mut egui::Ui) {
        ui.label(egui::RichText::new(self.texts.code_hint).color(MUTED));
        ui.add_space(8.0);
        let code = if self.note.is_empty() {
            "····".to_string()
        } else {
            self.note.clone()
        };
        show_card(ui, |ui| {
            ui.vertical_centered(|ui| {
                ui.add_space(8.0);
                ui.label(
                    egui::RichText::new(code)
                        .size(40.0)
                        .monospace()
                        .strong()
                        .color(INK),
                );
                ui.add_space(8.0);
                ui.label(egui::RichText::new(self.texts.waiting).color(MUTED));
            });
        });
    }

    fn ui_options(&mut self, ui: &mut egui::Ui) {
        ui.label(egui::RichText::new(self.texts.options_lead).color(MUTED));
        ui.add_space(8.0);
        show_card(ui, |ui| {
            ui.label(egui::RichText::new(self.texts.notify_title).strong().color(INK));
            ui.checkbox(&mut self.config.notify_badge, self.texts.notify_badge);
            ui.checkbox(&mut self.config.notify_toast, self.texts.notify_toast);
            ui.checkbox(&mut self.config.notify_sound, self.texts.notify_sound);
            ui.checkbox(&mut self.config.persistent_notifications, self.texts.notify_persist);
            ui.label(egui::RichText::new(self.texts.notify_persist_help).color(MUTED).size(13.0));
            ui.add_space(8.0);
            if web_button(ui, self.texts.notify_test, Btn::Normal, Some(ui.available_width()))
                .clicked()
            {
                self.test_notification();
            }
        });
        ui.add_space(12.0);
        self.mcp_editor(ui);
        ui.add_space(16.0);
        if self.primary(ui, self.texts.save).clicked() {
            self.save_options();
        }
    }

    fn ui_run(&mut self, ui: &mut egui::Ui) {
        show_card(ui, |ui| {
            ui.horizontal(|ui| {
                let (rect, _) = ui.allocate_exact_size(egui::vec2(12.0, 12.0), egui::Sense::hover());
                ui.painter()
                    .circle_filled(rect.center(), 6.0, if self.online { OK } else { MUTED });
                let status = if self.online {
                    self.texts.connected
                } else {
                    self.texts.disconnected
                };
                ui.label(egui::RichText::new(status).strong().color(INK));
            });
            if !self.note.is_empty() && self.note != self.texts.connected {
                ui.label(egui::RichText::new(&self.note).color(MUTED).size(13.0));
            }
            ui.add_space(8.0);
            let mut prefs = false;
            ui.label(egui::RichText::new(self.texts.notify_title).strong().color(INK));
            if ui
                .checkbox(&mut self.config.notify_badge, self.texts.notify_badge)
                .changed()
            {
                prefs = true;
            }
            if ui
                .checkbox(&mut self.config.notify_toast, self.texts.notify_toast)
                .changed()
            {
                prefs = true;
            }
            if ui
                .checkbox(&mut self.config.notify_sound, self.texts.notify_sound)
                .changed()
            {
                prefs = true;
            }
            if ui
                .checkbox(&mut self.config.persistent_notifications, self.texts.notify_persist)
                .changed()
            {
                prefs = true;
            }
            ui.label(egui::RichText::new(self.texts.notify_persist_help).color(MUTED).size(13.0));
            ui.add_space(8.0);
            if web_button(ui, self.texts.notify_test, Btn::Normal, Some(ui.available_width()))
                .clicked()
            {
                self.test_notification();
            }
            if prefs {
                let _ = config::save(&self.config);
            }
        });
        ui.add_space(12.0);
        self.mcp_editor(ui);
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            let gap = ui.spacing().item_spacing.x;
            let width = ((ui.available_width() - gap) / 2.0).max(40.0);
            if web_button(ui, self.texts.save, Btn::Normal, Some(width)).clicked() {
                let _ = config::save(&self.config);
                if let Some(tx) = &self.cmd_tx {
                    let _ = tx.send(Command::Mcp(self.config.mcp.clone()));
                }
            }
            if web_button(ui, self.texts.forget, Btn::Danger, Some(width)).clicked() {
                self.forget();
            }
        });
    }

    fn mcp_editor(&mut self, ui: &mut egui::Ui) {
        show_card(ui, |ui| {
            ui.label(egui::RichText::new(self.texts.mcp).strong().color(INK));
            ui.add_space(6.0);
            if self.config.mcp.is_empty() {
                ui.label(egui::RichText::new(self.texts.mcp_empty).color(MUTED));
            }
            let mut remove = None;
            for (index, server) in self.config.mcp.iter_mut().enumerate() {
                ui.add_space(8.0);
                ui.separator();
                ui.add_space(6.0);
                Self::field(ui, self.texts.mcp_name, &mut server.name);
                Self::field(ui, self.texts.mcp_cmd, &mut server.command);
                Self::field(ui, self.texts.mcp_args, &mut server.args);
                if web_button(ui, self.texts.remove, Btn::Normal, None).clicked() {
                    remove = Some(index);
                }
            }
            if let Some(index) = remove {
                self.config.mcp.remove(index);
            }
            ui.add_space(8.0);
            if web_button(ui, self.texts.add, Btn::Normal, None).clicked() {
                self.config.mcp.push(McpServer {
                    name: String::new(),
                    command: String::new(),
                    args: String::new(),
                });
            }
        });
    }
}

pub fn run() {
    let native = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([480.0, 680.0])
            .with_min_inner_size([420.0, 560.0])
            .with_icon(std::sync::Arc::new(egui::IconData {
                rgba: mark_pixels(WINDOW_ICON, false),
                width: WINDOW_ICON,
                height: WINDOW_ICON,
            })),
        ..Default::default()
    };
    let _ = eframe::run_native(
        "Autonomous",
        native,
        Box::new(|cc| {
            apply_theme(&cc.egui_ctx);
            Ok(Box::new(CompanionApp::new()))
        }),
    );
}
