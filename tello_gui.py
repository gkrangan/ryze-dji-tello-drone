#!/usr/bin/env python3
"""
Ryze DJI Tello Drone — GUI Controller
Provides a simple interface for hover tests, mission files, and pattern flight.
"""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

from tello_mission import MissionExecutor


class TelloGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ryze DJI Tello Controller")
        self.resizable(False, False)

        self._log_queue: queue.Queue = queue.Queue()
        self._executor: MissionExecutor | None = None

        self._build_ui()
        self._poll_log()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        ttk.Label(self, text="Ryze DJI Tello Controller", font=("Helvetica", 15, "bold")).pack(
            pady=(14, 2)
        )

        # Global option: dry-run
        options = ttk.Frame(self)
        options.pack(fill="x", padx=18, pady=(2, 6))
        self._dry_run = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Dry Run (simulate without drone)", variable=self._dry_run).pack(
            side="left"
        )

        # Tabs
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", padx=18, pady=4)
        self._build_hover_tab()
        self._build_mission_tab()
        self._build_pattern_tab()

        # Control buttons
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=18, pady=8)

        self._run_btn = ttk.Button(btn_row, text="▶  Run", width=12, command=self._on_run)
        self._run_btn.pack(side="left", padx=(0, 6))

        self._stop_btn = ttk.Button(btn_row, text="■  Stop", width=12, command=self._on_stop, state="disabled")
        self._stop_btn.pack(side="left")

        tk.Button(
            btn_row, text="⬇  EMERGENCY LAND",
            bg="#cc0000", fg="white", font=("Helvetica", 10, "bold"),
            padx=10, pady=4, relief="flat", cursor="hand2",
            command=self._on_emergency_land,
        ).pack(side="right")

        # Log
        ttk.Label(self, text="Log", font=("Helvetica", 10, "bold")).pack(anchor="w", padx=18)
        self._log_box = scrolledtext.ScrolledText(
            self, height=13, state="disabled", font=("Courier", 10), bg="#1e1e1e", fg="#d4d4d4"
        )
        self._log_box.pack(fill="both", padx=18, pady=(0, 14))

    def _build_hover_tab(self):
        frame = ttk.Frame(self._notebook, padding=14)
        self._notebook.add(frame, text="  Hover Test  ")
        self._hover_height = self._spinbox_row(frame, "Height (ft):", 1, 9, 3.0, 0.5, row=0)
        self._hover_time   = self._spinbox_row(frame, "Duration (secs):", 1, 300, 10, 1, row=1)

    def _build_mission_tab(self):
        frame = ttk.Frame(self._notebook, padding=14)
        self._notebook.add(frame, text="  Mission File  ")

        ttk.Label(frame, text="YAML file:").grid(row=0, column=0, sticky="w", pady=6)
        self._mission_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self._mission_path, width=38).grid(row=0, column=1, padx=6)
        ttk.Button(frame, text="Browse…", command=self._browse_mission).grid(row=0, column=2)

        ttk.Label(frame, text="Example missions are in the  missions/  folder.", foreground="gray").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

    def _build_pattern_tab(self):
        frame = ttk.Frame(self._notebook, padding=14)
        self._notebook.add(frame, text="  Pattern Flight  ")

        ttk.Label(frame, text="Pattern:").grid(row=0, column=0, sticky="w", pady=6)
        self._pattern = tk.StringVar(value="square")
        combo = ttk.Combobox(
            frame, textvariable=self._pattern,
            values=["square", "circle", "figure-8"],
            width=12, state="readonly",
        )
        combo.grid(row=0, column=1, sticky="w", padx=6)
        combo.bind("<<ComboboxSelected>>", self._on_pattern_change)

        self._pattern_height = self._spinbox_row(frame, "Height (ft):", 1, 9, 3.0, 0.5, row=1)
        self._pattern_size   = self._spinbox_row(frame, "Side length (cm):", 20, 500, 100, 10, row=2)
        self._pattern_speed  = self._spinbox_row(frame, "Speed (10–100):", 10, 100, 30, 5, row=3)

        self._size_label = ttk.Label(frame, text="Side length (cm):")
        # stored so _on_pattern_change can update it
        frame.grid_slaves(row=2, column=0)[0].configure  # reference via stored var below

        # Keep a direct reference to the size label widget for updating
        for child in frame.winfo_children():
            if isinstance(child, ttk.Label) and "Side" in str(child.cget("text")):
                self._size_label_widget = child
                break

    def _on_pattern_change(self, _event=None):
        shape = self._pattern.get()
        label = "Side length (cm):" if shape == "square" else "Radius (cm):"
        try:
            self._size_label_widget.config(text=label)
        except AttributeError:
            pass

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _spinbox_row(
        self, parent, label: str, from_: float, to: float,
        default: float, increment: float, row: int
    ) -> tk.DoubleVar:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        var = tk.DoubleVar(value=default)
        ttk.Spinbox(
            parent, from_=from_, to=to, increment=increment,
            textvariable=var, width=8,
        ).grid(row=row, column=1, sticky="w", padx=6)
        return var

    def _browse_mission(self):
        path = filedialog.askopenfilename(
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if path:
            self._mission_path.set(path)

    # ------------------------------------------------------------------
    # Mission building
    # ------------------------------------------------------------------

    def _build_mission(self) -> dict | None:
        tab = self._notebook.tab(self._notebook.select(), "text").strip()

        if "Hover" in tab:
            return {
                "name": "Hover Test",
                "actions": [
                    {"type": "takeoff", "height_ft": self._hover_height.get()},
                    {"type": "hover",   "duration_secs": self._hover_time.get()},
                    {"type": "land"},
                ],
            }

        if "Mission" in tab:
            path = self._mission_path.get().strip()
            if not path:
                self._log("[Error] No mission file selected.")
                return None
            try:
                return MissionExecutor.load_yaml(path)
            except Exception as e:
                self._log(f"[Error] Failed to load mission: {e}")
                return None

        if "Pattern" in tab:
            shape = self._pattern.get()
            return {
                "name": f"Pattern: {shape}",
                "actions": [
                    {"type": "takeoff", "height_ft": self._pattern_height.get()},
                    {
                        "type": "pattern",
                        "shape": shape,
                        "size_cm": int(self._pattern_size.get()),
                        "speed":   int(self._pattern_speed.get()),
                    },
                    {"type": "land"},
                ],
            }

        return None

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_run(self):
        mission = self._build_mission()
        if not mission:
            return
        self._executor = MissionExecutor(dry_run=self._dry_run.get(), log=self._log)
        self._set_running(True)
        threading.Thread(target=self._run_mission, args=(mission,), daemon=True).start()

    def _run_mission(self, mission: dict):
        try:
            self._executor.run(mission)
        except Exception as e:
            self._log(f"[Error] {e}")
        finally:
            self.after(0, lambda: self._set_running(False))

    def _on_stop(self):
        if self._executor:
            self._executor.stop()
        self._log("[Control] Stop requested — landing...")

    def _on_emergency_land(self):
        self._log("[Control] *** EMERGENCY LAND ***")
        if self._executor:
            self._executor.stop()
            return
        if self._dry_run.get():
            self._log("[DryRun] Emergency land simulated.")
            return
        # No active mission — connect and land directly
        def _land():
            try:
                from djitellopy import Tello
                t = Tello()
                t.connect()
                t.land()
                t.end()
                self._log("[Control] Emergency land complete.")
            except Exception as e:
                self._log(f"[Error] Emergency land failed: {e}")
        threading.Thread(target=_land, daemon=True).start()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _set_running(self, running: bool):
        self._run_btn.config(state="disabled" if running else "normal")
        self._stop_btn.config(state="normal" if running else "disabled")

    # ------------------------------------------------------------------
    # Thread-safe logging
    # ------------------------------------------------------------------

    def _log(self, msg: str):
        self._log_queue.put(msg)

    def _poll_log(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            self._log_box.config(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.config(state="disabled")
        self.after(100, self._poll_log)


if __name__ == "__main__":
    app = TelloGUI()
    app.mainloop()
