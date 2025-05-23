import tkinter as tk
import time
import threading
import requests
import sys

with open("timer_log.txt", "a") as f:
    f.write(f"[START] Timer dimulai untuk doc_id: {sys.argv}\n")

# --- Cek parameter doc_id ---
if len(sys.argv) < 2:
    print("❌ doc_id belum diberikan. Jalankan: python timer.py <doc_id>")
    sys.exit(1)

doc_id = sys.argv[1]

# --- Fungsi countdown ---
def start_countdown(seconds):
    def run():
        for i in range(seconds, -1, -1):
            label.config(text=f"{i} detik")
            time.sleep(1)
        root.destroy()

        # --- Arahkan kembali ke halaman utama photobox (opsional) ---
        try:
            url = f"http://127.0.0.1:5000/{doc_id}"
            print(f"🔁 Redirecting to {url}")
            requests.get(url)
        except Exception as e:
            print("❌ Gagal redirect ke homepage:", e)

    threading.Thread(target=run, daemon=True).start()

# --- Setup GUI ---
root = tk.Tk()
root.title("Photobox Countdown")
root.overrideredirect(True)           # Hilangkan border window
root.attributes("-topmost", True)     # Tampil di atas semua window
root.configure(bg='white')

# --- Posisi window tengah atas ---
screen_width = root.winfo_screenwidth()
window_width = 200
window_height = 60
x_position = int((screen_width / 2) - (window_width / 2))
y_position = 20

root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")

# --- Label waktu ---
label = tk.Label(root, text="", font=("Poppins", 18), bg="white", fg="black")
label.pack(expand=True)

# --- Mulai countdown ---
start_countdown(60)

# --- Tampilkan window ---
root.mainloop()
