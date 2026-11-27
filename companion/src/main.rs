// GUI builds must not open a black console on Windows (double-click / Startup).
#![cfg_attr(feature = "gui", windows_subsystem = "windows")]

fn main() {
    #[cfg(feature = "gui")]
    autonomous_companion::run();
    #[cfg(not(feature = "gui"))]
    {
        eprintln!("rebuild with --features gui");
        std::process::exit(1);
    }
}
