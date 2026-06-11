"""
Telemetry Collector -- Phase 1
==============================
Connects to PX4 SITL via MAVSDK and streams real-time telemetry.

How it works:
1. Connects to PX4 on UDP port 14540 (the offboard API port)
2. Launches multiple async tasks -- one per telemetry stream
3. Each task updates a shared state dictionary as new data arrives
4. A snapshot task periodically reads the shared state and outputs JSON

Key concepts:
- MAVSDK exposes telemetry as async generators (async for ... in drone.telemetry.X())
- asyncio.gather() runs all generators concurrently in one thread
- Shared state dict is safe because asyncio is single-threaded (no locks needed)

Usage:
    # Standalone -- just collect telemetry and print to console
    python -m tars.phase1.telemetry_collector

    # As a module -- import and use in mission_runner.py
    from tars.phase1.telemetry_collector import TelemetryCollector
    collector = TelemetryCollector(drone)
    await collector.start()
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mavsdk import System

from .models.telemetry import (
    AttitudeData,
    BatteryData,
    GpsData,
    GpsFixType,
    HealthData,
    MissionSummary,
    MissionTelemetry,
    MissionResult,
    PositionData,
    TelemetrySnapshot,
    VelocityData,
)

# Set up logging -- you'll see these messages in the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("telemetry_collector")


class TelemetryCollector:
    """
    Collects telemetry from PX4 SITL and stores it as structured snapshots.

    Architecture:
        PX4 SITL -> MAVLink UDP -> MAVSDK -> async generators -> shared state -> snapshots

    The collector runs multiple async tasks concurrently:
    - watch_position()    -- updates position data as GPS reports come in
    - watch_velocity()    -- updates NED velocity
    - watch_battery()     -- updates battery voltage and percentage
    - watch_gps_info()    -- updates satellite count and fix type
    - watch_attitude()    -- updates roll/pitch/yaw angles
    - watch_flight_mode() -- updates current flight mode string
    - watch_health()      -- updates sensor health flags
    - take_snapshots()    -- periodically combines all data into a TelemetrySnapshot
    """

    def __init__(
        self,
        drone: System,
        rate_hz: float = 1.0,
        mission_id: str = "mission_001",
        drone_id: str = "tars-sim-01",
    ):
        """
        Args:
            drone: Connected MAVSDK System instance
            rate_hz: How many snapshots per second (1.0 = one per second)
            mission_id: Unique identifier for this mission
            drone_id: Identifier for this drone
        """
        self.drone = drone
        self.rate_hz = rate_hz
        self.mission_id = mission_id
        self.drone_id = drone_id

        # Shared state -- each watch_* task updates its section
        # The snapshot task reads from this to create TelemetrySnapshot objects
        self._position: Optional[PositionData] = None
        self._velocity: Optional[VelocityData] = None
        self._battery: Optional[BatteryData] = None
        self._gps: Optional[GpsData] = None
        self._attitude: Optional[AttitudeData] = None
        self._flight_mode: Optional[str] = None
        self._health: Optional[HealthData] = None

        # Collected snapshots -- the mission's telemetry time series
        self._snapshots: list[TelemetrySnapshot] = []

        # Control flag -- set to False to stop collection
        self._collecting = False

        # Track previous position for distance calculation
        self._prev_lat: Optional[float] = None
        self._prev_lon: Optional[float] = None
        self._total_distance_m: float = 0.0

    @property
    def snapshots(self) -> list[TelemetrySnapshot]:
        """Access collected telemetry snapshots."""
        return self._snapshots

    @property
    def is_collecting(self) -> bool:
        """Whether the collector is actively taking snapshots."""
        return self._collecting

    # =========================================================================
    # Watch Tasks -- Each subscribes to one MAVSDK telemetry stream
    # =========================================================================
    # These run as concurrent async tasks. When PX4 sends new data,
    # the async generator yields it, and we update the shared state.
    #
    # IMPORTANT: These loops run forever (until cancelled). That's by design --
    # telemetry streams are continuous. We stop them by cancelling the task.
    # =========================================================================

    async def _watch_position(self):
        """Subscribe to GPS position updates."""
        logger.info("[POS] Watching position stream...")
        async for position in self.drone.telemetry.position():
            self._position = PositionData(
                latitude_deg=position.latitude_deg,
                longitude_deg=position.longitude_deg,
                absolute_altitude_m=position.absolute_altitude_m,
                relative_altitude_m=position.relative_altitude_m,
            )
            # Track distance traveled
            if self._prev_lat is not None and self._prev_lon is not None:
                dist = self._haversine_distance(
                    self._prev_lat, self._prev_lon,
                    position.latitude_deg, position.longitude_deg,
                )
                self._total_distance_m += dist
            self._prev_lat = position.latitude_deg
            self._prev_lon = position.longitude_deg

    async def _watch_velocity(self):
        """Subscribe to NED velocity updates."""
        logger.info("[VEL] Watching velocity stream...")
        async for velocity in self.drone.telemetry.velocity_ned():
            self._velocity = VelocityData(
                north_m_s=velocity.north_m_s,
                east_m_s=velocity.east_m_s,
                down_m_s=velocity.down_m_s,
            )

    async def _watch_battery(self):
        """Subscribe to battery status updates."""
        logger.info("[BAT] Watching battery stream...")
        async for battery in self.drone.telemetry.battery():
            self._battery = BatteryData(
                voltage_v=battery.voltage_v,
                remaining_percent=battery.remaining_percent * 100,  # MAVSDK returns 0-1
            )

    async def _watch_gps_info(self):
        """Subscribe to GPS receiver info (satellite count, fix type)."""
        logger.info("[GPS] Watching GPS info stream...")
        async for gps_info in self.drone.telemetry.gps_info():
            # Map MAVSDK's fix type enum to our GpsFixType
            fix_type_map = {
                0: GpsFixType.NO_GPS,
                1: GpsFixType.NO_FIX,
                2: GpsFixType.FIX_2D,
                3: GpsFixType.FIX_3D,
                4: GpsFixType.DGPS,
                5: GpsFixType.RTK_FLOAT,
                6: GpsFixType.RTK_FIXED,
            }
            fix_type = fix_type_map.get(gps_info.fix_type.value, GpsFixType.NO_FIX)
            self._gps = GpsData(
                num_satellites=gps_info.num_satellites,
                fix_type=fix_type,
            )

    async def _watch_attitude(self):
        """Subscribe to attitude (orientation) updates."""
        logger.info("[ATT] Watching attitude stream...")
        async for attitude in self.drone.telemetry.attitude_euler():
            self._attitude = AttitudeData(
                roll_deg=attitude.roll_deg,
                pitch_deg=attitude.pitch_deg,
                yaw_deg=attitude.yaw_deg,
            )

    async def _watch_flight_mode(self):
        """Subscribe to flight mode changes."""
        logger.info("[MODE] Watching flight mode stream...")
        async for mode in self.drone.telemetry.flight_mode():
            self._flight_mode = str(mode)
            logger.info(f"Flight mode changed: {self._flight_mode}")

    async def _watch_health(self):
        """Subscribe to health/calibration status."""
        logger.info("[HEALTH] Watching health stream...")
        async for health in self.drone.telemetry.health():
            self._health = HealthData(
                is_gyrometer_calibration_ok=health.is_gyrometer_calibration_ok,
                is_accelerometer_calibration_ok=health.is_accelerometer_calibration_ok,
                is_magnetometer_calibration_ok=health.is_magnetometer_calibration_ok,
                is_home_position_ok=health.is_home_position_ok,
                is_global_position_ok=health.is_global_position_ok,
            )

    # =========================================================================
    # Snapshot Task -- Periodically captures the current state
    # =========================================================================

    async def _take_snapshots(self):
        """
        Periodically read the shared state and create a TelemetrySnapshot.

        This runs at self.rate_hz frequency (default: 1 Hz = once per second).
        Each snapshot captures the LATEST value from every telemetry stream.

        Why periodic snapshots instead of event-driven?
        - Telemetry streams update at different rates (GPS: 10Hz, battery: 1Hz)
        - Periodic snapshots give us a consistent time series
        - 1 Hz is enough for analysis; raw MAVLink is ~100+ messages/sec
        """
        interval = 1.0 / self.rate_hz
        logger.info(f"[SNAP] Taking snapshots at {self.rate_hz} Hz (every {interval}s)")

        while self._collecting:
            snapshot = TelemetrySnapshot(
                timestamp=datetime.now(timezone.utc),
                position=self._position,
                velocity=self._velocity,
                battery=self._battery,
                gps=self._gps,
                attitude=self._attitude,
                flight_mode=self._flight_mode,
                health=self._health,
            )
            self._snapshots.append(snapshot)

            # Print a compact summary to console
            self._log_snapshot(snapshot)

            await asyncio.sleep(interval)

    def _log_snapshot(self, snapshot: TelemetrySnapshot):
        """Print a compact one-line summary of the snapshot."""
        parts = []
        if snapshot.position:
            parts.append(f"alt={snapshot.position.relative_altitude_m:.1f}m")
        if snapshot.battery:
            parts.append(f"bat={snapshot.battery.remaining_percent:.0f}%")
        if snapshot.gps:
            parts.append(f"sat={snapshot.gps.num_satellites}")
        if snapshot.flight_mode:
            parts.append(f"mode={snapshot.flight_mode}")
        if snapshot.attitude:
            parts.append(f"yaw={snapshot.attitude.yaw_deg:.0f}deg")

        summary = " | ".join(parts)
        logger.info(f"[{len(self._snapshots):04d}] {summary}")

    # =========================================================================
    # Public API -- Start, stop, and export
    # =========================================================================

    async def start(self):
        """
        Start all telemetry watch tasks and the snapshot task.

        This launches 8 concurrent async tasks via asyncio.gather().
        They all run in the same thread, switching at await points.

        Call stop() to end collection, or cancel the task externally.
        """
        self._collecting = True
        self._snapshots = []
        self._total_distance_m = 0.0
        self._prev_lat = None
        self._prev_lon = None

        logger.info(f"Starting telemetry collection for mission {self.mission_id}")

        # Launch all watch tasks + snapshot task concurrently
        # asyncio.gather() runs them all in parallel (cooperative multitasking)
        try:
            await asyncio.gather(
                self._watch_position(),
                self._watch_velocity(),
                self._watch_battery(),
                self._watch_gps_info(),
                self._watch_attitude(),
                self._watch_flight_mode(),
                self._watch_health(),
                self._take_snapshots(),
            )
        except asyncio.CancelledError:
            logger.info("Telemetry collection cancelled")
            self._collecting = False

    def stop(self):
        """Signal the snapshot task to stop. Watch tasks will be cancelled externally."""
        logger.info("Stopping telemetry collection")
        self._collecting = False

    def build_mission_telemetry(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        result: MissionResult = MissionResult.SUCCESS,
        faults: Optional[list] = None,
    ) -> MissionTelemetry:
        """
        Build the complete MissionTelemetry output from collected snapshots.

        This creates the final JSON-serializable object that gets saved to disk.
        It includes metadata, all telemetry snapshots, and computed summary stats.
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        # Compute summary statistics from the collected snapshots
        summary = self._compute_summary(start_time, end_time)

        return MissionTelemetry(
            mission_id=self.mission_id,
            drone_id=self.drone_id,
            start_time=start_time,
            end_time=end_time,
            faults_injected=faults or [],
            telemetry=self._snapshots,
            mission_result=result,
            summary=summary,
        )

    def _compute_summary(self, start_time: datetime, end_time: datetime) -> MissionSummary:
        """Compute aggregate statistics from collected snapshots."""
        max_alt = 0.0
        min_battery = 100.0
        max_speed = 0.0

        for snap in self._snapshots:
            if snap.position and snap.position.relative_altitude_m > max_alt:
                max_alt = snap.position.relative_altitude_m
            if snap.battery and snap.battery.remaining_percent < min_battery:
                min_battery = snap.battery.remaining_percent
            if snap.velocity:
                # Ground speed = sqrt(north^2 + east^2)
                speed = math.sqrt(
                    snap.velocity.north_m_s ** 2 + snap.velocity.east_m_s ** 2
                )
                if speed > max_speed:
                    max_speed = speed

        duration = (end_time - start_time).total_seconds()

        return MissionSummary(
            total_snapshots=len(self._snapshots),
            duration_seconds=duration,
            max_altitude_m=max_alt,
            distance_traveled_m=self._total_distance_m,
            min_battery_percent=min_battery,
            max_speed_m_s=max_speed,
            collection_rate_hz=self.rate_hz,
        )

    def save_to_file(self, mission_telemetry: MissionTelemetry, output_dir: str = "output"):
        """
        Save mission telemetry to a JSON file.

        File is named: {mission_id}.json
        Saved to: output/{mission_id}.json
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filepath = output_path / f"{mission_telemetry.mission_id}.json"

        # Pydantic v2's model_dump_json() gives us clean, serialized JSON
        json_str = mission_telemetry.model_dump_json(indent=2)

        filepath.write_text(json_str)
        logger.info(f"Saved telemetry to {filepath} ({len(self._snapshots)} snapshots)")

        return filepath

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two GPS coordinates in meters.

        Uses the Haversine formula -- the standard way to compute
        great-circle distance on a sphere (Earth).

        This is approximate (Earth isn't a perfect sphere) but accurate
        enough for our purposes (~0.3% error).
        """
        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c


# =============================================================================
# Standalone Mode -- Run the collector directly for testing
# =============================================================================

async def main():
    """
    Run the telemetry collector standalone.

    This connects to PX4 SITL and streams telemetry to the console.
    Useful for testing that the connection works before running missions.

    Usage: python -m tars.phase1.telemetry_collector
    """
    # Load configuration from environment
    connection_str = os.getenv("PX4_CONNECTION", "udp://:14540")
    rate_hz = float(os.getenv("TELEMETRY_RATE_HZ", "1"))
    mission_id = os.getenv("MISSION_ID", f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    drone_id = os.getenv("DRONE_ID", "tars-sim-01")

    logger.info(f"Connecting to PX4 at {connection_str}...")

    # Create MAVSDK System and connect
    drone = System()
    await drone.connect(system_address=connection_str)

    # Wait for the drone to be discovered
    # This blocks until MAVSDK receives the first MAVLink heartbeat from PX4
    logger.info("Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            logger.info("Drone connected!")
            break

    # Wait for GPS fix -- PX4 needs this before it can do anything useful
    logger.info("Waiting for global position estimate...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            logger.info("Global position OK, home position set")
            break

    # Create collector and start
    collector = TelemetryCollector(
        drone=drone,
        rate_hz=rate_hz,
        mission_id=mission_id,
        drone_id=drone_id,
    )

    logger.info("Starting telemetry collection (Ctrl+C to stop)...")

    try:
        await collector.start()
    except KeyboardInterrupt:
        collector.stop()
        logger.info(f"Collected {len(collector.snapshots)} snapshots")


if __name__ == "__main__":
    asyncio.run(main())
