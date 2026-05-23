#!/usr/bin/env python3
"""
Live video panel for the Tello GUI.
Streams the drone's front camera with optional telemetry / face / color overlays,
snapshot, and recording.
"""

import datetime
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

VIDEO_WIDTH = 480
VIDEO_HEIGHT = 360
FRAME_INTERVAL_MS = 33  # ~30 fps


class VideoPanel:
    def __init__(self, parent: ttk.Frame, log: Callable[[str], None]):
        self.parent = parent
        self.log = log

        self._running = False
        self._tello = None
        self._frame_read = None
        self._writer = None  # cv2.VideoWriter
        self._face_cascade = None  # lazy-loaded

        # UI state vars
        self._show_hud = tk.BooleanVar(value=True)
        self._show_faces = tk.BooleanVar(value=False)
        self._show_colors = tk.BooleanVar(value=False)
        self._color_choice = tk.StringVar(value="red")

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Fixed-size container so the placeholder label doesn't blow out the window.
        # (tk.Label width/height are characters/lines without an image — we want pixels.)
        canvas_frame = tk.Frame(
            self.parent, width=VIDEO_WIDTH, height=VIDEO_HEIGHT, bg="black",
        )
        canvas_frame.grid(row=0, column=0, columnspan=4, pady=(0, 8))
        canvas_frame.grid_propagate(False)

        self._canvas = tk.Label(
            canvas_frame, bg="black",
            text="(stream off)", fg="#666666",
            font=("Helvetica", 11),
        )
        self._canvas.place(relx=0.5, rely=0.5, anchor="center")

        # Controls row 1: stream / record / snapshot
        self._stream_btn = ttk.Button(self.parent, text="▶  Start Stream", width=16, command=self.toggle_stream)
        self._stream_btn.grid(row=1, column=0, sticky="w", padx=(0, 6))

        self._record_btn = ttk.Button(self.parent, text="●  Record", width=12, command=self._toggle_record, state="disabled")
        self._record_btn.grid(row=1, column=1, padx=6)

        self._snapshot_btn = ttk.Button(self.parent, text="📸  Snapshot", width=12, command=self._snapshot, state="disabled")
        self._snapshot_btn.grid(row=1, column=2, padx=6)

        # Overlay toggles
        toggles = ttk.Frame(self.parent)
        toggles.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Checkbutton(toggles, text="Telemetry HUD", variable=self._show_hud).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(toggles, text="Face detection", variable=self._show_faces).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(toggles, text="Color detection:", variable=self._show_colors).pack(side="left")
        ttk.Combobox(
            toggles, textvariable=self._color_choice,
            values=["red", "green", "blue", "yellow"],
            width=8, state="readonly",
        ).pack(side="left", padx=(4, 0))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._running

    def toggle_stream(self):
        if self._running:
            self.stop_stream()
        else:
            self.start_stream()

    def start_stream(self):
        if self._running:
            return
        try:
            from djitellopy import Tello
        except ImportError as e:
            self.log(f"[Error] djitellopy not installed: {e}")
            return

        self.log("[Video] Connecting to drone...")
        try:
            self._tello = Tello()
            self._tello.connect()
            battery = self._tello.get_battery()
            self.log(f"[Video] Connected | Battery: {battery}%")
            self._tello.streamon()
            self._frame_read = self._tello.get_frame_read()
        except Exception as e:
            self.log(f"[Error] Failed to start stream: {e}")
            self._cleanup_tello()
            return

        self._running = True
        self._stream_btn.config(text="■  Stop Stream")
        self._record_btn.config(state="normal")
        self._snapshot_btn.config(state="normal")
        self._update_frame()

    def stop_stream(self):
        if not self._running:
            return
        self._running = False
        self._close_writer()

        if self._tello:
            try:
                self._tello.streamoff()
            except Exception:
                pass
            self._cleanup_tello()

        self._stream_btn.config(text="▶  Start Stream")
        self._record_btn.config(state="disabled", text="●  Record")
        self._snapshot_btn.config(state="disabled")
        self._canvas.config(image="", text="(stream off)")
        self._canvas.image = None
        self.log("[Video] Stream stopped.")

    def shutdown(self):
        """Called on app close — ensure clean disconnect."""
        if self._running:
            self.stop_stream()

    # ------------------------------------------------------------------
    # Frame pipeline
    # ------------------------------------------------------------------

    def _update_frame(self):
        if not self._running:
            return

        try:
            frame = self._frame_read.frame if self._frame_read else None
            if frame is None or frame.size == 0:
                self.parent.after(FRAME_INTERVAL_MS, self._update_frame)
                return

            import cv2
            display = cv2.resize(frame, (VIDEO_WIDTH, VIDEO_HEIGHT))

            # Apply overlays in order
            if self._show_faces.get():
                display = self._overlay_faces(display)
            if self._show_colors.get():
                display = self._overlay_color(display, self._color_choice.get())
            if self._show_hud.get():
                display = self._overlay_hud(display)

            if self._writer is not None:
                self._writer.write(display)

            # BGR -> RGB -> PIL -> ImageTk
            rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
            from PIL import Image, ImageTk
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self._canvas.config(image=photo, text="")
            self._canvas.image = photo  # prevent GC

        except Exception as e:
            self.log(f"[Video] Frame error: {e}")

        if self._running:
            self.parent.after(FRAME_INTERVAL_MS, self._update_frame)

    # ------------------------------------------------------------------
    # Overlays
    # ------------------------------------------------------------------

    def _overlay_hud(self, frame):
        import cv2
        if not self._tello:
            return frame
        try:
            battery = self._tello.get_battery()
            height = self._tello.get_height()
            flight_time = self._tello.get_flight_time()
            text = f"BAT {battery}%   HEIGHT {height}cm   TIME {flight_time}s"
            # Translucent black bar at top
            cv2.rectangle(frame, (0, 0), (VIDEO_WIDTH, 26), (0, 0, 0), -1)
            cv2.putText(frame, text, (8, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        except Exception:
            pass  # telemetry can fail mid-frame; skip silently
        return frame

    def _overlay_faces(self, frame):
        import cv2
        if self._face_cascade is None:
            self._face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(gray, 1.1, 4)
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, "FACE", (x, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        return frame

    def _overlay_color(self, frame, color: str):
        import cv2
        import numpy as np
        from tello_mission import COLOR_RANGES
        if color not in COLOR_RANGES:
            return frame
        lower, upper = COLOR_RANGES[color]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) < 500:
                continue
            x, y, w, h = cv2.boundingRect(c)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(frame, color.upper(), (x, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
        return frame

    # ------------------------------------------------------------------
    # Snapshot & record
    # ------------------------------------------------------------------

    def _snapshot(self):
        if not self._running or self._frame_read is None:
            return
        import cv2
        frame = self._frame_read.frame
        if frame is None:
            return
        filename = f"snapshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        cv2.imwrite(filename, frame)
        self.log(f"[Video] Snapshot saved: {filename}")

    def _toggle_record(self):
        if self._writer is not None:
            self._close_writer()
            self._record_btn.config(text="●  Record")
            self.log("[Video] Recording stopped.")
        else:
            import cv2
            filename = f"recording_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(filename, fourcc, 30.0, (VIDEO_WIDTH, VIDEO_HEIGHT))
            self._record_btn.config(text="■  Stop Recording")
            self.log(f"[Video] Recording to {filename}")

    def _close_writer(self):
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_tello(self):
        if self._tello:
            try:
                self._tello.end()
            except Exception:
                pass
        self._tello = None
        self._frame_read = None
