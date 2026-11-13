//! Register the companion to start when the user signs in.
//! A tray program needs a desktop session, so this is login — not a pre-login boot service.

use std::path::{Path, PathBuf};

const LINUX_NAME: &str = "autonomous-companion.desktop";
const MACOS_LABEL: &str = "fr.mister3d.autonomous-companion";
const WINDOWS_CMD: &str = "Autonomous Companion.cmd";

pub fn linux_desktop(exe: &Path) -> String {
    format!(
        "[Desktop Entry]\n\
         Type=Application\n\
         Name=Autonomous Companion\n\
         Comment=Start Autonomous Companion when you sign in\n\
         Exec={}\n\
         X-GNOME-Autostart-enabled=true\n\
         StartupNotify=false\n",
        desktop_exec(exe),
    )
}

pub fn macos_plist(exe: &Path) -> String {
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
         <!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \
         \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n\
         <plist version=\"1.0\">\n\
         <dict>\n\
         \t<key>Label</key>\n\
         \t<string>{MACOS_LABEL}</string>\n\
         \t<key>ProgramArguments</key>\n\
         \t<array>\n\
         \t\t<string>{}</string>\n\
         \t</array>\n\
         \t<key>RunAtLoad</key>\n\
         \t<true/>\n\
         </dict>\n\
         </plist>\n",
        xml_escape(&exe.display().to_string()),
    )
}

/// `start` command stored in the current user's Startup folder.
pub fn windows_startup_script(exe: &Path) -> String {
    let shown = exe.display().to_string().replace('%', "%%").replace('"', "");
    format!("@echo off\r\nstart \"\" \"{shown}\"\r\n")
}

fn desktop_exec(exe: &Path) -> String {
    let raw = exe.display().to_string();
    if raw.contains(|c: char| c.is_whitespace() || matches!(c, '"' | '\\' | '\'')) {
        format!("\"{}\"", raw.replace('"', "\\\""))
    } else {
        raw
    }
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

pub fn apply(enabled: bool) -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    apply_exe(enabled, &exe)
}

fn apply_exe(enabled: bool, exe: &Path) -> Result<(), String> {
    match std::env::consts::OS {
        "linux" => write_or_remove(enabled, &linux_autostart_path()?, &linux_desktop(exe)),
        "macos" => write_or_remove(enabled, &macos_plist_path()?, &macos_plist(exe)),
        "windows" => write_or_remove(
            enabled,
            &windows_startup_path()?,
            &windows_startup_script(exe),
        ),
        other => Err(format!("sign-in start is not available on {other}")),
    }
}

fn write_or_remove(enabled: bool, path: &Path, body: &str) -> Result<(), String> {
    if !enabled {
        if path.is_file() {
            std::fs::remove_file(path).map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(path, body).map_err(|e| e.to_string())?;
    Ok(())
}

fn linux_autostart_path() -> Result<PathBuf, String> {
    let base = directories::BaseDirs::new().ok_or_else(|| "no home directory".to_string())?;
    Ok(base.config_dir().join("autostart").join(LINUX_NAME))
}

fn macos_plist_path() -> Result<PathBuf, String> {
    let base = directories::BaseDirs::new().ok_or_else(|| "no home directory".to_string())?;
    Ok(base
        .home_dir()
        .join("Library/LaunchAgents")
        .join(format!("{MACOS_LABEL}.plist")))
}

fn windows_startup_path() -> Result<PathBuf, String> {
    let appdata = std::env::var_os("APPDATA").ok_or_else(|| "APPDATA is not set".to_string())?;
    Ok(PathBuf::from(appdata)
        .join("Microsoft")
        .join("Windows")
        .join("Start Menu")
        .join("Programs")
        .join("Startup")
        .join(WINDOWS_CMD))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn linux_desktop_quotes_a_path_with_spaces() {
        let text = linux_desktop(Path::new("/opt/my app/autonomous-companion-0.1.20"));
        assert!(text.contains("Exec=\"/opt/my app/autonomous-companion-0.1.20\""));
        assert!(text.contains("X-GNOME-Autostart-enabled=true"));
    }

    #[test]
    fn windows_script_quotes_the_exe_and_escapes_percent() {
        let text = windows_startup_script(Path::new(
            r"C:\Users\me\autonomous-companion-0.1.20.exe",
        ));
        assert!(text.contains("start \"\" \"C:\\Users\\me\\autonomous-companion-0.1.20.exe\""));
        let odd = windows_startup_script(Path::new(r"C:\Temp\100%done\app.exe"));
        assert!(odd.contains("100%%done"));
    }

    #[test]
    fn macos_plist_runs_at_load_and_escapes_xml() {
        let text = macos_plist(Path::new("/Users/me/autonomous-companion&0.1.20"));
        assert!(text.contains("<key>RunAtLoad</key>"));
        assert!(text.contains("autonomous-companion&amp;0.1.20"));
        assert!(text.contains(MACOS_LABEL));
    }
}
