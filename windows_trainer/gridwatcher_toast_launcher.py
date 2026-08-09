import os
import sys
import subprocess
import tkinter as tk
from tkinter import messagebox

def launch_prompt():
    # Hide main root window
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    # Ask user with native Windows Dialog box
    ans = messagebox.askyesno(
        "⚡ GridWatcher ML Trainer",
        "New grid telemetry collected from Orange Pi.\n\nWould you like to update & sync the ML Model to GitHub now?",
        parent=root
    )

    root.destroy()

    if ans:
        # User clicked YES: Launch the GUI retrainer
        gui_script = os.path.join(os.path.dirname(__file__), "gridwatcher_ml_gui.py")
        subprocess.Popen([sys.executable, gui_script])

    # If NO clicked, script exits cleanly using 0 resources!

if __name__ == "__main__":
    launch_prompt()
