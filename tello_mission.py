#!/usr/bin/env python3
"""
Mission executor for the Ryze DJI Tello drone.

Loads a YAML mission dict and runs actions sequentially.
Supports: takeoff, land, hover, move, rotate, pattern (square/circle/figure-8),
and on_detect (face or color via OpenCV).
"""

import math
import threading
import time
from typing import Callable

import yaml

FEET_TO_CM = 30.48
MIN_MOVE_CM = 20
SIMULATED_TAKEOFF_HEIGHT_CM = 80

# HSV color ranges for detection (lower, upper)
COLOR_RANGES = {
    "red":    ([0,   120,  70], [10,  255, 255]),
    "green":  ([36,   50,  70], [89,  255, 255]),
    "blue":   ([94,   80,   2], [126, 255, 255]),
    "yellow": ([25,   50,  70], [35,  255, 255]),
}


class MissionExecutor:
    def __init__(self, dry_run: bool = False, log: Callable = print):
        self.dry_run = dry_run
        self.log = log
        self.tello = None
        self._stop = threading.Event()
        self._in_flight = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @staticmethod
    def load_yaml(path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    def run(self, mission: dict):
        self._stop.clear()
        self._in_flight = False
        self.log(f"[Mission] Starting: {mission.get('name', 'Unnamed')}")
        self._connect()
        try:
            for action in mission.get("actions", []):
                if self._stop.is_set():
                    self.log("[Mission] Stopped by user.")
                    break
                self._dispatch(action)
        finally:
            if self._in_flight:
                self._do_land({})
            self._disconnect()
            self.log("[Mission] Complete.")

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self):
        if self.dry_run:
            self.log("[DryRun] *** Dry-run mode — no drone commands will be sent ***")
            self.log("[DryRun] Connected | Battery: 85% (simulated)")
            return
        from djitellopy import Tello
        self.tello = Tello()
        self.tello.connect()
        battery = self.tello.get_battery()
        self.log(f"[Tello] Connected | Battery: {battery}%")
        if battery < 20:
            self.log("[Warning] Low battery — consider charging before flight.")

    def _disconnect(self):
        if self.dry_run or self.tello is None:
            return
        self.tello.end()

    # ------------------------------------------------------------------
    # Action dispatcher
    # ------------------------------------------------------------------

    _HANDLERS = {
        "takeoff":   "_do_takeoff",
        "land":      "_do_land",
        "hover":     "_do_hover",
        "move":      "_do_move",
        "rotate":    "_do_rotate",
        "pattern":   "_do_pattern",
        "on_detect": "_do_on_detect",
    }

    def _dispatch(self, action: dict):
        t = action.get("type")
        handler = self._HANDLERS.get(t)
        if not handler:
            self.log(f"[Warning] Unknown action type: {t!r} — skipping")
            return
        getattr(self, handler)(action)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _do_takeoff(self, action: dict):
        self.log("[Flight] Taking off...")
        if self.dry_run:
            time.sleep(1)
            self.log("[DryRun] Takeoff simulated.")
        else:
            self.tello.takeoff()
        self._in_flight = True

        height_ft = action.get("height_ft")
        if height_ft:
            self._adjust_height(round(height_ft * FEET_TO_CM))

    def _do_land(self, action: dict):
        self.log("[Flight] Landing...")
        if self.dry_run:
            time.sleep(0.5)
        else:
            self.tello.land()
        self._in_flight = False
        self.log("[Flight] Landed safely.")

    def _do_hover(self, action: dict):
        height_ft = action.get("height_ft")
        if height_ft:
            self._adjust_height(round(height_ft * FEET_TO_CM))

        duration = action.get("duration_secs", 5)
        self.log(f"[Hover] Holding position for {duration}s...")
        deadline = time.time() + duration
        last_tick = -1
        while not self._stop.is_set():
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            secs_left = int(remaining)
            if secs_left != last_tick:
                self.log(f"[Hover] {secs_left}s remaining...")
                last_tick = secs_left
            if not self.dry_run:
                self.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.1)

    def _do_move(self, action: dict):
        speed = max(10, min(100, action.get("speed", 30)))

        if "direction" in action:
            dist = max(MIN_MOVE_CM, action.get("distance_cm", 50))
            direction = action["direction"].lower()
            self.log(f"[Move] {direction} {dist}cm @ speed {speed}")
            if not self.dry_run:
                fn = {
                    "forward":  self.tello.move_forward,
                    "back":     self.tello.move_back,
                    "backward": self.tello.move_back,
                    "left":     self.tello.move_left,
                    "right":    self.tello.move_right,
                    "up":       self.tello.move_up,
                    "down":     self.tello.move_down,
                }.get(direction)
                if fn:
                    fn(dist)
                else:
                    self.log(f"[Warning] Unknown direction: {direction}")
            else:
                time.sleep(1)
        else:
            x = action.get("x", 0)
            y = action.get("y", 0)
            z = action.get("z", 0)
            self.log(f"[Move] x={x}cm y={y}cm z={z}cm @ speed {speed}")
            if not self.dry_run:
                self.tello.go_xyz_speed(x, y, z, speed)
            else:
                time.sleep(1)

    def _do_rotate(self, action: dict):
        degrees = action.get("degrees", 90)
        direction = action.get("direction", "clockwise").lower()
        self.log(f"[Rotate] {direction} {degrees}°")
        if self.dry_run:
            time.sleep(0.5)
        elif direction == "clockwise":
            self.tello.rotate_clockwise(degrees)
        else:
            self.tello.rotate_counter_clockwise(degrees)

    def _do_pattern(self, action: dict):
        shape = action.get("shape", "square").lower()
        size_cm = max(MIN_MOVE_CM, action.get("size_cm", 100))
        speed = max(10, min(100, action.get("speed", 30)))
        self.log(f"[Pattern] {shape} | size={size_cm}cm speed={speed}")

        if shape == "square":
            self._square(size_cm, speed)
        elif shape == "circle":
            self._circle(radius_cm=size_cm, speed=speed)
        elif shape in ("figure-8", "figure8"):
            self._figure8(radius_cm=size_cm, speed=speed)
        else:
            self.log(f"[Warning] Unknown pattern shape: {shape}")

    def _do_on_detect(self, action: dict):
        target = action.get("target", "face").lower()
        color = action.get("color", "red").lower()
        on_found = action.get("on_found", "hover").lower()
        timeout = action.get("timeout_secs", 15)

        self.log(f"[Detect] Scanning for {target} | timeout={timeout}s | on_found={on_found}")

        if self.dry_run:
            self.log("[DryRun] Detection skipped in dry-run mode.")
            return

        import cv2
        import numpy as np

        self.tello.streamon()
        frame_read = self.tello.get_frame_read()
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        deadline = time.time() + timeout
        detected = False
        try:
            while time.time() < deadline and not self._stop.is_set():
                self.tello.send_rc_control(0, 0, 0, 0)
                frame = frame_read.frame
                if target == "face":
                    detected = self._detect_face(frame, face_cascade)
                elif target == "color":
                    detected = self._detect_color(frame, color)

                if detected:
                    self.log(f"[Detect] {target} detected!")
                    if on_found == "land":
                        self._do_land({})
                    break
                time.sleep(0.1)

            if not detected:
                self.log(f"[Detect] Timeout — {target} not found.")
        finally:
            self.tello.streamoff()

    # ------------------------------------------------------------------
    # Patterns
    # ------------------------------------------------------------------

    def _square(self, side_cm: int, speed: int):
        sides = [
            ("forward", self.tello.move_forward if not self.dry_run else None),
            ("right",   self.tello.move_right   if not self.dry_run else None),
            ("back",    self.tello.move_back     if not self.dry_run else None),
            ("left",    self.tello.move_left     if not self.dry_run else None),
        ]
        for i, (label, fn) in enumerate(sides, 1):
            if self._stop.is_set():
                break
            self.log(f"[Pattern] Square leg {i}/4 — {label} {side_cm}cm")
            if fn:
                fn(side_cm)
            else:
                time.sleep(1)

    def _circle(self, radius_cm: int, speed: int):
        # Continuous RC: forward velocity + yaw produces a circular arc
        # radius ≈ forward_speed_cms / (yaw_rate_dps * π/180)
        # RC units ≈ cm/s and deg/s for Tello
        yaw_rate = int(speed * 180 / (math.pi * radius_cm))
        yaw_rate = max(10, min(100, yaw_rate))
        period = 360 / yaw_rate
        self.log(f"[Pattern] Circle radius≈{radius_cm}cm ~{period:.1f}s")
        if not self.dry_run:
            start = time.time()
            while time.time() - start < period and not self._stop.is_set():
                self.tello.send_rc_control(0, speed, 0, yaw_rate)
                time.sleep(0.05)
            self.tello.send_rc_control(0, 0, 0, 0)
        else:
            time.sleep(period)

    def _figure8(self, radius_cm: int, speed: int):
        yaw_rate = int(speed * 180 / (math.pi * radius_cm))
        yaw_rate = max(10, min(100, yaw_rate))
        period = 360 / yaw_rate
        self.log(f"[Pattern] Figure-8 radius≈{radius_cm}cm ~{period * 2:.1f}s total")
        for yaw, label in [(yaw_rate, "clockwise"), (-yaw_rate, "counter-clockwise")]:
            if self._stop.is_set():
                break
            self.log(f"[Pattern] Figure-8 loop — {label}")
            if not self.dry_run:
                start = time.time()
                while time.time() - start < period and not self._stop.is_set():
                    self.tello.send_rc_control(0, speed, 0, yaw)
                    time.sleep(0.05)
                self.tello.send_rc_control(0, 0, 0, 0)
            else:
                time.sleep(period)

    # ------------------------------------------------------------------
    # CV helpers
    # ------------------------------------------------------------------

    def _detect_face(self, frame, cascade) -> bool:
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
        return len(faces) > 0

    def _detect_color(self, frame, color: str) -> bool:
        import cv2
        import numpy as np
        if color not in COLOR_RANGES:
            self.log(f"[Warning] Unknown color: {color!r}")
            return False
        lower, upper = COLOR_RANGES[color]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        return int(cv2.countNonZero(mask)) > 500

    # ------------------------------------------------------------------
    # Internal: height adjustment
    # ------------------------------------------------------------------

    def _adjust_height(self, target_cm: int):
        if self.dry_run:
            current_cm = SIMULATED_TAKEOFF_HEIGHT_CM
        else:
            time.sleep(1.5)
            current_cm = self.tello.get_height()

        delta = target_cm - current_cm
        self.log(
            f"[Height] Current: {current_cm}cm | Target: {target_cm}cm "
            f"({target_cm / FEET_TO_CM:.1f}ft) | Delta: {delta:+}cm"
        )
        if delta >= MIN_MOVE_CM:
            self.log(f"[Height] Moving up {delta}cm")
            if not self.dry_run:
                self.tello.move_up(delta)
        elif delta <= -MIN_MOVE_CM:
            self.log(f"[Height] Moving down {abs(delta)}cm")
            if not self.dry_run:
                self.tello.move_down(abs(delta))
        else:
            self.log("[Height] Within tolerance — no adjustment needed.")
