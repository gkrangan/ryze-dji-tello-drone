#!/usr/bin/env python3
"""
Tello Drone Hover Controller
Takeoff → adjust to target height → hover → land (auto or on command)

Usage:
    python tello_hover.py                             # defaults: 3ft, 10s
    python tello_hover.py --height 5 --time 30       # 5ft hover for 30s
    python tello_hover.py --dry-run                  # simulate without flying
    python tello_hover.py --dry-run --height 5 --time 5
"""

import argparse
import signal
import threading
import time

FEET_TO_CM = 30.48
MIN_MOVE_CM = 20  # Tello SDK minimum single-axis move
SIMULATED_TAKEOFF_HEIGHT_CM = 80  # approximate post-takeoff height


def feet_to_cm(feet: float) -> int:
    return round(feet * FEET_TO_CM)


class HoverController:
    def __init__(self, height_feet: float = 3.0, hover_secs: float = 10.0, dry_run: bool = False):
        self.height_cm = feet_to_cm(height_feet)
        self.hover_secs = hover_secs
        self.dry_run = dry_run
        self._land_event = threading.Event()

        if not dry_run:
            from djitellopy import Tello
            self.tello = Tello()
        else:
            self.tello = None

    # ------------------------------------------------------------------
    # Drone calls — each method is a no-op in dry-run mode
    # ------------------------------------------------------------------

    def connect(self):
        if self.dry_run:
            print("[DryRun] Skipping connection — simulated battery: 85%")
            return
        self.tello.connect()
        battery = self.tello.get_battery()
        print(f"[Tello] Connected | Battery: {battery}%")
        if battery < 20:
            print("[Warning] Low battery — consider charging before flight.")

    def _adjust_height(self):
        if self.dry_run:
            time.sleep(0.5)
            current_cm = SIMULATED_TAKEOFF_HEIGHT_CM
        else:
            time.sleep(1.5)  # let barometer/optical-flow stabilize post-takeoff
            current_cm = self.tello.get_height()

        delta = self.height_cm - current_cm
        print(
            f"[Height] Current: {current_cm}cm | "
            f"Target: {self.height_cm}cm ({self.height_cm / FEET_TO_CM:.1f}ft) | "
            f"Delta: {delta:+}cm"
        )
        if delta >= MIN_MOVE_CM:
            print(f"[Height] Moving up {delta}cm...")
            if not self.dry_run:
                self.tello.move_up(delta)
        elif delta <= -MIN_MOVE_CM:
            print(f"[Height] Moving down {abs(delta)}cm...")
            if not self.dry_run:
                self.tello.move_down(abs(delta))
        else:
            print("[Height] Within tolerance — no adjustment needed.")

    def _hover_loop(self):
        deadline = time.time() + self.hover_secs
        last_printed = -1
        while not self._land_event.is_set():
            remaining = deadline - time.time()
            if remaining <= 0:
                print("\n[Hover] Time elapsed. Landing automatically...")
                break
            # Print a countdown tick every second
            secs_left = int(remaining)
            if secs_left != last_printed:
                print(f"[Hover] {secs_left}s remaining...", end="\r", flush=True)
                last_printed = secs_left
            if not self.dry_run:
                self.tello.send_rc_control(0, 0, 0, 0)
            time.sleep(0.1)

    def _listen_for_land_command(self):
        print("[Command] Type  'land'  and press Enter to land immediately.\n")
        while not self._land_event.is_set():
            try:
                cmd = input()
                if cmd.strip().lower() in ("land", "l"):
                    print("[Command] Land command received.")
                    self._land_event.set()
            except EOFError:
                break

    # ------------------------------------------------------------------
    # Main flight sequence
    # ------------------------------------------------------------------

    def run(self):
        if self.dry_run:
            print("[DryRun] *** Dry-run mode — no drone commands will be sent ***\n")

        self.connect()

        def _on_sigint(sig, frame):
            print("\n[Signal] Ctrl+C detected — landing now.")
            self._land_event.set()

        signal.signal(signal.SIGINT, _on_sigint)

        listener = threading.Thread(target=self._listen_for_land_command, daemon=True)
        listener.start()

        try:
            print("[Flight] Taking off...")
            if not self.dry_run:
                self.tello.takeoff()
            else:
                time.sleep(1)
                print("[DryRun] Takeoff simulated.")

            print(f"[Flight] Adjusting to {self.height_cm / FEET_TO_CM:.1f}ft ({self.height_cm}cm)...")
            self._adjust_height()

            print(f"[Flight] Hovering for {self.hover_secs}s...")
            self._hover_loop()

        finally:
            print("\n[Flight] Landing...")
            if not self.dry_run:
                self.tello.land()
                self.tello.end()
            else:
                time.sleep(0.5)
            print("[Flight] Landed safely.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomously hover a Ryze DJI Tello drone at a set height."
    )
    parser.add_argument(
        "--height", type=float, default=3.0,
        metavar="FEET",
        help="Hover height in feet (default: 3.0)"
    )
    parser.add_argument(
        "--time", type=float, default=10.0,
        metavar="SECS",
        help="Hover duration in seconds (default: 10)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate the flight sequence without connecting to the drone"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    controller = HoverController(
        height_feet=args.height,
        hover_secs=args.time,
        dry_run=args.dry_run,
    )
    controller.run()
