"""
Keeps slack_bridge.py running forever.
Only one instance is allowed — a second launch kills the old one first.
"""
import subprocess, sys, time, os, socket, signal, psutil

SCRIPT   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slack_bridge.py")
LOCK_PORT = 47392   # local port used as a single-instance lock

def kill_existing():
    """Kill any other run_bridge / slack_bridge processes before starting."""
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.pid == current_pid:
                continue
            cmdline = " ".join(proc.info['cmdline'] or [])
            if "slack_bridge" in cmdline or "run_bridge" in cmdline:
                print(f"[run_bridge] Killing old instance PID {proc.pid}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

def acquire_lock():
    """Bind to a local port — fails immediately if another instance holds it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(('127.0.0.1', LOCK_PORT))
        return sock   # keep open to hold the lock
    except OSError:
        return None

if __name__ == "__main__":
    print("[run_bridge] Checking for existing instances…")
    kill_existing()
    time.sleep(1)

    lock = acquire_lock()
    if lock is None:
        print("[run_bridge] Could not acquire lock — retrying after kill…")
        time.sleep(2)
        lock = acquire_lock()
        if lock is None:
            print("[run_bridge] ERROR: another instance is still holding the port. Exiting.")
            sys.exit(1)

    print("[run_bridge] Lock acquired. This is the only running instance.")

    while True:
        print(f"\n[run_bridge] Starting slack_bridge.py …")
        result = subprocess.run([sys.executable, SCRIPT])
        print(f"[run_bridge] Exited (code {result.returncode}). Restarting in 5s …")
        time.sleep(5)
