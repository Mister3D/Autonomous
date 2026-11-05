fn main() {
    #[cfg(feature = "gui")]
    autonomous_companion::run();
    #[cfg(not(feature = "gui"))]
    {
        eprintln!("rebuild with --features gui");
        std::process::exit(1);
    }
}
