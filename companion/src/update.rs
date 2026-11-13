//! Replace this program with the binary the paired instance is serving.
//!
//! The running file is compared by sha256, not by the filename. A match means
//! there is nothing to do. Dev builds under `target/` are left alone.

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::mpsc::Receiver;
use std::thread;
use std::time::{Duration, Instant};

use crate::api;
use crate::config::Config;

const MAX_BYTES: u64 = 80 * 1024 * 1024;
const BUILD_POLL_S: u64 = 2;
const BUILD_WAIT_S: u64 = 90 * 60;

/// One check each time the tunnel connects. While the server is compiling,
/// poll until the binary is ready instead of installing the previous file.
pub fn watch(config: Config, connects: Receiver<()>) {
    if let Ok(current) = std::env::current_exe() {
        let _ = std::fs::remove_file(backup_path(&current));
    }
    while connects.recv().is_ok() {
        while connects.try_recv().is_ok() {}
        if !installable_exe() {
            continue;
        }
        if matches!(wait_and_apply(&config), Ok(true)) {
            std::process::exit(0);
        }
    }
}

fn wait_and_apply(config: &Config) -> Result<bool, String> {
    let deadline = Instant::now() + Duration::from_secs(BUILD_WAIT_S);
    loop {
        let offer = api::update_offer(config)?;
        match offer_action(&offer.state) {
            "wait" => {
                if Instant::now() >= deadline {
                    return Err("companion build still running".into());
                }
                thread::sleep(Duration::from_secs(BUILD_POLL_S));
            }
            "ready" => return apply_ready(config, &offer),
            _ => return Ok(false),
        }
    }
}

pub fn offer_action(state: &str) -> &'static str {
    match state {
        "building" => "wait",
        "ready" => "ready",
        _ => "skip",
    }
}

fn apply_ready(config: &Config, offer: &api::UpdateOffer) -> Result<bool, String> {
    let current = std::env::current_exe().map_err(|e| e.to_string())?;
    if !installable_path(&current) {
        return Ok(false);
    }
    let local = file_sha256(&current)?;
    if !needs_update(&local, &offer.sha256) {
        return Ok(false);
    }
    if offer.size == 0 || offer.size > MAX_BYTES {
        return Err("companion update has an unexpected size".into());
    }
    let staged = stage_path(&current);
    if let Err(err) = api::download_update(config, &staged) {
        let _ = std::fs::remove_file(&staged);
        return Err(err);
    }
    let got = file_sha256(&staged).map_err(|err| {
        let _ = std::fs::remove_file(&staged);
        err
    })?;
    if !same_sha(&got, &offer.sha256) || file_len(&staged)? != offer.size {
        let _ = std::fs::remove_file(&staged);
        return Err("downloaded companion did not match the server".into());
    }
    swap_in_place(&current, &staged)?;
    relaunch(&current)?;
    Ok(true)
}

pub fn needs_update(local_sha: &str, remote_sha: &str) -> bool {
    !same_sha(local_sha, remote_sha)
}

fn same_sha(left: &str, right: &str) -> bool {
    left.trim().eq_ignore_ascii_case(right.trim())
}

pub fn installable_path(path: &Path) -> bool {
    let text = path.to_string_lossy().replace('\\', "/");
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    name.starts_with("autonomous-companion")
        && !text.contains("/target/debug/")
        && !text.contains("/target/release/")
}

fn installable_exe() -> bool {
    std::env::current_exe()
        .map(|path| installable_path(&path))
        .unwrap_or(false)
}

pub fn stage_path(current: &Path) -> PathBuf {
    sibling(current, ".new")
}

pub fn backup_path(current: &Path) -> PathBuf {
    sibling(current, ".old")
}

fn sibling(current: &Path, suffix: &str) -> PathBuf {
    let mut name = current
        .file_name()
        .map(|n| n.to_os_string())
        .unwrap_or_default();
    name.push(suffix);
    current.with_file_name(name)
}

pub fn file_sha256(path: &Path) -> Result<String, String> {
    let mut file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    let mut buf = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let n = file.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        total += n as u64;
        if total > MAX_BYTES {
            return Err("companion file is too large".into());
        }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.finish())
}

/// SHA-256, small enough to avoid a crate. FIPS 180-4.
struct Sha256 {
    state: [u32; 8],
    buffer: [u8; 64],
    filled: usize,
    bits: u64,
}

impl Sha256 {
    fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
                0x1f83d9ab, 0x5be0cd19,
            ],
            buffer: [0; 64],
            filled: 0,
            bits: 0,
        }
    }

    fn update(&mut self, mut data: &[u8]) {
        self.bits += (data.len() as u64) * 8;
        if self.filled > 0 {
            let need = 64 - self.filled;
            let take = need.min(data.len());
            self.buffer[self.filled..self.filled + take].copy_from_slice(&data[..take]);
            self.filled += take;
            data = &data[take..];
            if self.filled == 64 {
                let block = self.buffer;
                self.compress(&block);
                self.filled = 0;
            }
        }
        while data.len() >= 64 {
            self.compress(&data[..64]);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.buffer[..data.len()].copy_from_slice(data);
            self.filled = data.len();
        }
    }

    fn finish(mut self) -> String {
        let mut block = [0_u8; 64];
        block[..self.filled].copy_from_slice(&self.buffer[..self.filled]);
        block[self.filled] = 0x80;
        if self.filled >= 56 {
            self.compress(&block);
            block = [0; 64];
        }
        block[56..].copy_from_slice(&self.bits.to_be_bytes());
        self.compress(&block);
        self.state.iter().map(|word| format!("{word:08x}")).collect()
    }

    fn compress(&mut self, block: &[u8]) {
        const K: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
            0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
            0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
            0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
            0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
            0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
            0xc67178f2,
        ];
        let mut w = [0_u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes(block[i * 4..i * 4 + 4].try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];
        let mut f = self.state[5];
        let mut g = self.state[6];
        let mut h = self.state[7];
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        let next = [a, b, c, d, e, f, g, h];
        for (slot, add) in self.state.iter_mut().zip(next) {
            *slot = slot.wrapping_add(add);
        }
    }
}

fn file_len(path: &Path) -> Result<u64, String> {
    Ok(std::fs::metadata(path).map_err(|e| e.to_string())?.len())
}

pub fn swap_in_place(current: &Path, staged: &Path) -> Result<(), String> {
    if cfg!(windows) {
        let old = backup_path(current);
        let _ = std::fs::remove_file(&old);
        std::fs::rename(current, &old).map_err(|e| e.to_string())?;
        if let Err(err) = std::fs::rename(staged, current) {
            let _ = std::fs::rename(&old, current);
            return Err(err.to_string());
        }
    } else {
        std::fs::rename(staged, current).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn relaunch(current: &Path) -> Result<(), String> {
    Command::new(current)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn empty_file_sha_is_the_well_known_value() {
        let dir = std::env::temp_dir().join(format!("ac-sha-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("empty");
        std::fs::File::create(&path).unwrap().write_all(b"").unwrap();
        let sha = file_sha256(&path).unwrap();
        assert_eq!(
            sha,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        std::fs::write(&path, b"abc").unwrap();
        assert_eq!(
            file_sha256(&path).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn building_means_wait_and_a_failure_is_skipped() {
        assert_eq!(offer_action("building"), "wait");
        assert_eq!(offer_action("ready"), "ready");
        assert_eq!(offer_action("failed"), "skip");
        assert_eq!(offer_action(""), "skip");
    }

    #[test]
    fn same_hash_does_not_update() {
        assert!(!needs_update("AbC", "abc"));
        assert!(needs_update("aaa", "bbb"));
    }

    #[test]
    fn dev_builds_are_not_replaced() {
        assert!(!installable_path(Path::new(
            "/src/target/release/autonomous-companion"
        )));
        assert!(installable_path(Path::new(
            "/home/me/Downloads/autonomous-companion-0.1.22.exe"
        )));
        assert!(!installable_path(Path::new("/tmp/other.exe")));
    }

    #[test]
    fn swap_replaces_the_file_in_place() {
        let dir = std::env::temp_dir().join(format!("ac-swap-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let current = dir.join("autonomous-companion");
        let staged = stage_path(&current);
        std::fs::write(&current, b"old").unwrap();
        std::fs::write(&staged, b"new").unwrap();
        swap_in_place(&current, &staged).unwrap();
        assert_eq!(std::fs::read(&current).unwrap(), b"new");
        assert!(!staged.exists());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
