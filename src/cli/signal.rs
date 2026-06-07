// SIGINT handler — matches Python's frais/commands/_signal.py.

use std::sync::atomic::{AtomicBool, Ordering};

static INTERRUPTED: AtomicBool = AtomicBool::new(false);

/// Install the SIGINT handler. Returns the original handler for later restoration.
/// Matches Python's install_interrupt_handler() which returns signal.signal(signal.SIGINT, _on_interrupt).
pub fn install_interrupt_handler() -> Box<dyn Fn()> {
    // Store the previous handler so we can restore it
    let prev = unsafe {
        let mut prev: libc::sigaction = std::mem::zeroed();
        let new: libc::sigaction = {
            let mut sa: libc::sigaction = std::mem::zeroed();
            sa.sa_sigaction = handle_sigint as *const () as usize;
            sa.sa_flags = libc::SA_SIGINFO;
            sa
        };
        libc::sigaction(libc::SIGINT, &new, &mut prev);
        prev
    };

    // Return a closure that restores the original handler
    Box::new(move || unsafe {
        libc::sigaction(libc::SIGINT, &prev, std::ptr::null_mut());
    })
}

extern "C" fn handle_sigint(_signum: i32, _info: *mut libc::siginfo_t, _ctx: *mut libc::c_void) {
    // Write ANSI escape to restore cursor (bypasses any TUI state)
    // Matches Python's os.write(1, b"\033[?25h\n")
    let restore = b"\x1b[?25h\n";
    unsafe {
        libc::write(1, restore.as_ptr() as *const libc::c_void, restore.len());
    }
    INTERRUPTED.store(true, Ordering::SeqCst);
    // Send SIGTERM to process group, then exit
    // Matches Python's os.killpg(os.getpgrp(), signal.SIGTERM) + os._exit(130)
    unsafe {
        libc::kill(0, libc::SIGTERM);
        libc::_exit(130);
    }
}

/// Check if an interrupt has been received.
pub fn is_interrupted() -> bool {
    INTERRUPTED.load(Ordering::SeqCst)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_interrupt_not_set_initially() {
        assert!(!is_interrupted());
    }
}
