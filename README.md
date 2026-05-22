# Ryze DJI Tello Drone — Python Controller

A Python application to autonomously control the Ryze DJI Tello drone, built incrementally from a simple hover controller up to more complex autonomous behaviors.

---

## Requirements

- Python 3.8+
- Ryze DJI Tello drone
- WiFi connection to the drone (connect your machine to the Tello's WiFi hotspot before running)

## Setup

```bash
git clone https://github.com/gkrangan/ryze-dji-tello-drone.git
cd ryze-dji-tello-drone
pip install -r requirements.txt
```

---

## Controllers

### `tello_hover.py` — Hover Controller

Takeoff → hover at a configurable height → land automatically or on command.

**Flight sequence:**
1. Connects to the drone and checks battery
2. Takes off (drone lifts to ~80cm by default)
3. Adjusts to the target height
4. Hovers in place for the configured duration, actively sending zero-velocity commands every 100ms to minimize drift
5. Lands automatically when time is up

**Usage:**

```bash
python tello_hover.py                        # defaults: 3ft, 10s
python tello_hover.py --height 5 --time 30  # 5ft hover for 30s
python tello_hover.py --height 2             # 2ft hover for 10s (default)
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--height` | `3.0` | Hover height in feet |
| `--time` | `10` | Hover duration in seconds |

**Landing on demand:**

| Method | Action |
|--------|--------|
| Type `land` + Enter | Graceful land at any time during hover |
| `Ctrl+C` | Emergency land immediately |

**Notes:**
- The Tello SDK enforces a 20cm minimum per move command. If the target height is within ±20cm of the post-takeoff position (~80cm), no height adjustment is issued — the drone hovers at its natural takeoff height.
- Battery below 20% will show a warning before flight. The drone itself will auto-land if battery drops critically low mid-flight.

---

## Roadmap

- [x] Hover controller — takeoff, hold height, land on command
- [ ] Waypoint navigation
- [ ] Pattern flight (square, circle)
- [ ] Computer vision triggers
