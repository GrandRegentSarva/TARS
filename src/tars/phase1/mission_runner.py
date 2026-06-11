"""
Mission Runner -- Phase 1
=========================
Commands the drone through a complete autonomous mission:
    arm -> takeoff -> fly waypoints (square pattern) -> return to launch -> land

How it works:
1. Connects to PX4 SITL via MAVSDK
2. Waits for the drone to be ready (GPS fix, health checks)
3. Uploads a mission plan (4 waypoints forming a square)
4. Starts the mission -- PX4 autopilot handles the actual flying
5. Monitors mission progress until completion
6. Telemetry collection runs concurrently the entire time
7. Fault events from the injector are saved into the mission JSON

The mission and telemetry collection run as parallel async tasks.
When the mission finishes, telemetry is saved to a JSON file.

Usage:
    python -m tars.phase1.mission_runner

    # With custom mission ID
    MISSION_ID=mission_003 python -m tars.phase1.mission_runner
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

from .models.telemetry import MissionResult
from .telemetry_collector import TelemetryCollector
from .fault_injector import FaultInjector, FaultScenarios

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("mission_runner")


# =============================================================================
# Mission Configuration
# =============================================================================
# PX4 SITL default home position is in Zurich, Switzerland:
#   Latitude:  47.397742 N
#   Longitude:  8.545594 E
#   Altitude:  488m AMSL (above mean sea level)
#
# Our waypoints are offset from this home position to create a square pattern.
# Each waypoint is ~100m from the adjacent ones.
#
# Coordinate offsets (approximate):
#   1 deg latitude  ~ 111,000 meters
#   1 deg longitude ~ 74,000 meters (at 47 N latitude)
#   So 100m ~ 0.0009 deg latitude, 0.00135 deg longitude
# =============================================================================

# Home position (PX4 SITL default -- Zurich)
HOME_LAT = 47.397742
HOME_LON = 8.545594

# Offset for ~100m square
LAT_OFFSET = 0.0009    # ~100m north
LON_OFFSET = 0.00135   # ~100m east

# Flight altitude above takeoff point
FLIGHT_ALTITUDE_M = 20.0

# Speed during mission (m/s)
FLIGHT_SPEED_M_S = 5.0


def create_square_mission() -> list[MissionItem]:
    """
    Create a square mission plan with 4 waypoints.

    The square is oriented with HOME at the southwest corner:

        WP2 (NW) -------- WP3 (NE)
         |                  |
         |    ~100m x 100m  |
         |                  |
        WP1 (SW) -------- WP4 (SE)
              HOME

    Each MissionItem defines:
    - latitude/longitude: where to fly
    - relative_altitude_m: height above takeoff point
    - speed_m_s: how fast to fly to this waypoint
    - is_fly_through: True = don't stop at waypoint, just fly through it
    - gimbal_pitch/yaw_deg: camera angle (0 = forward, -90 = straight down)
    - camera_action: what to do with camera at this waypoint
    - loiter_time_s: how long to hover at this waypoint (0 = don't hover)
    - acceptance_radius_m: how close to get before considering waypoint "reached"
    """
    waypoints = [
        # WP1: Southwest corner (near home) -- fly here first after takeoff
        MissionItem(
            latitude_deg=HOME_LAT,
            longitude_deg=HOME_LON,
            relative_altitude_m=FLIGHT_ALTITUDE_M,
            speed_m_s=FLIGHT_SPEED_M_S,
            is_fly_through=True,            # Don't stop, fly through
            gimbal_pitch_deg=0.0,           # Camera forward
            gimbal_yaw_deg=float("nan"),    # Don't change camera yaw
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,              # No hovering
            camera_photo_interval_s=float("nan"),
            acceptance_radius_m=5.0,        # Within 5m = "reached"
            yaw_deg=float("nan"),           # Don't force heading
            camera_photo_distance_m=float("nan"),
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
        # WP2: Northwest corner -- 100m north of home
        MissionItem(
            latitude_deg=HOME_LAT + LAT_OFFSET,
            longitude_deg=HOME_LON,
            relative_altitude_m=FLIGHT_ALTITUDE_M,
            speed_m_s=FLIGHT_SPEED_M_S,
            is_fly_through=True,
            gimbal_pitch_deg=0.0,
            gimbal_yaw_deg=float("nan"),
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,
            camera_photo_interval_s=float("nan"),
            acceptance_radius_m=5.0,
            yaw_deg=float("nan"),
            camera_photo_distance_m=float("nan"),
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
        # WP3: Northeast corner -- 100m north + 100m east of home
        MissionItem(
            latitude_deg=HOME_LAT + LAT_OFFSET,
            longitude_deg=HOME_LON + LON_OFFSET,
            relative_altitude_m=FLIGHT_ALTITUDE_M,
            speed_m_s=FLIGHT_SPEED_M_S,
            is_fly_through=True,
            gimbal_pitch_deg=0.0,
            gimbal_yaw_deg=float("nan"),
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,
            camera_photo_interval_s=float("nan"),
            acceptance_radius_m=5.0,
            yaw_deg=float("nan"),
            camera_photo_distance_m=float("nan"),
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
        # WP4: Southeast corner -- 100m east of home (completes the square)
        MissionItem(
            latitude_deg=HOME_LAT,
            longitude_deg=HOME_LON + LON_OFFSET,
            relative_altitude_m=FLIGHT_ALTITUDE_M,
            speed_m_s=FLIGHT_SPEED_M_S,
            is_fly_through=True,
            gimbal_pitch_deg=0.0,
            gimbal_yaw_deg=float("nan"),
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=0.0,
            camera_photo_interval_s=float("nan"),
            acceptance_radius_m=5.0,
            yaw_deg=float("nan"),
            camera_photo_distance_m=float("nan"),
            vehicle_action=MissionItem.VehicleAction.NONE,
        ),
    ]

    return waypoints


async def wait_for_drone_ready(drone: System):
    """
    Wait until the drone is ready to fly.

    PX4 requires several conditions before it will arm:
    1. Connection established (MAVLink heartbeat received)
    2. Global position available (GPS has a fix)
    3. Home position set (PX4 knows where "home" is for Return-to-Launch)

    This function blocks until all conditions are met.
    In simulation, this typically takes 5-15 seconds after PX4 starts.
    """
    # Wait for connection
    logger.info("Waiting for drone connection...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            logger.info("Drone connected!")
            break

    # Wait for global position + home position
    logger.info("Waiting for GPS fix and home position...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            logger.info("GPS fix acquired, home position set")
            break


async def run_mission(drone: System) -> MissionResult:
    """
    Upload and execute the square mission plan.

    Steps:
    1. Create the waypoint list
    2. Upload the mission plan to PX4
    3. Arm the drone (enable motors)
    4. Start the mission (PX4 autopilot takes over)
    5. Monitor progress until mission is finished
    6. Return to launch and land

    Returns:
        MissionResult -- SUCCESS, FAILURE, or ABORTED
    """
    # Create the square mission
    waypoints = create_square_mission()
    mission_plan = MissionPlan(waypoints)

    logger.info(f"Uploading mission plan ({len(waypoints)} waypoints)...")
    await drone.mission.upload_mission(mission_plan)
    logger.info("Mission uploaded")

    # Set return-to-launch after mission completes
    # This tells PX4 to fly back to the home position and land after the last waypoint
    await drone.mission.set_return_to_launch_after_mission(True)
    logger.info("Return-to-launch after mission: enabled")

    # Arm the drone -- this enables the motors
    # PX4 will refuse to arm if health checks fail (no GPS, uncalibrated sensors, etc.)
    logger.info("Arming drone...")
    await drone.action.arm()
    logger.info("Drone armed!")

    # Start the mission -- PX4 autopilot now controls the drone
    logger.info("Starting mission...")
    await drone.mission.start_mission()
    logger.info("Mission started!")

    # Monitor mission progress
    # This async generator yields updates whenever the mission state changes
    # (new waypoint reached, mission paused, mission finished, etc.)
    mission_result = MissionResult.IN_PROGRESS

    async for mission_progress in drone.mission.mission_progress():
        logger.info(
            f"Mission progress: waypoint {mission_progress.current} "
            f"of {mission_progress.total}"
        )

        # Check if mission is finished
        if mission_progress.current == mission_progress.total:
            logger.info("All waypoints reached!")
            break

    # Wait for the drone to land (RTL mode)
    # After the last waypoint, PX4 switches to Return-to-Launch mode
    # and flies back to home position, then lands automatically
    logger.info("Returning to launch and landing...")

    # Monitor until the drone is on the ground and disarmed
    async for in_air in drone.telemetry.in_air():
        if not in_air:
            logger.info("Drone has landed!")
            mission_result = MissionResult.SUCCESS
            break

    # Disarm (motors off) -- may already be disarmed after landing
    try:
        await drone.action.disarm()
        logger.info("Drone disarmed")
    except Exception:
        logger.info("Drone already disarmed")

    return mission_result


async def main():
    """
    Main entry point -- connects, collects telemetry, and runs the mission.

    This orchestrates three concurrent activities:
    1. Telemetry collection (runs the entire time)
    2. Mission execution (runs the flight plan)
    3. Optional fault scenario (runs in background if FAULT_SCENARIO is set)

    A FaultInjector is created in this process so that injected faults are
    recorded in its fault_events list and persisted into the output JSON.

    Note: Faults injected from a *separate* process (e.g., the interactive
    fault_injector CLI) will affect PX4 behavior and show up in telemetry,
    but will NOT appear in faults_injected because that process has its own
    FaultInjector instance. To get faults into the JSON, either:
    - Set FAULT_SCENARIO env var (s1, s2, s3, s4) to run a built-in scenario
    - Or extend this runner to accept fault commands programmatically

    When the mission finishes, telemetry collection stops and
    everything is saved to a JSON file.
    """
    # Load configuration
    connection_str = os.getenv("PX4_CONNECTION", "udp://:14540")
    rate_hz = float(os.getenv("TELEMETRY_RATE_HZ", "1"))
    mission_id = os.getenv("MISSION_ID", f"mission_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    drone_id = os.getenv("DRONE_ID", "tars-sim-01")
    output_dir = os.getenv("OUTPUT_DIR", "output")
    fault_scenario = os.getenv("FAULT_SCENARIO", "")

    logger.info("=" * 60)
    logger.info("TARS Phase 1 -- Mission Runner")
    logger.info("=" * 60)
    logger.info(f"Mission ID:  {mission_id}")
    logger.info(f"Drone ID:    {drone_id}")
    logger.info(f"Connection:  {connection_str}")
    logger.info(f"Rate:        {rate_hz} Hz")
    logger.info(f"Output:      {output_dir}/")
    if fault_scenario:
        logger.info(f"Fault:       scenario {fault_scenario}")
    logger.info("=" * 60)

    # Connect to PX4 SITL
    drone = System()
    await drone.connect(system_address=connection_str)

    # Wait for drone to be ready
    await wait_for_drone_ready(drone)

    # Create telemetry collector
    collector = TelemetryCollector(
        drone=drone,
        rate_hz=rate_hz,
        mission_id=mission_id,
        drone_id=drone_id,
    )

    # Create fault injector -- tracks fault events for the mission output
    injector = FaultInjector(drone)

    # Record mission start time
    start_time = datetime.now(timezone.utc)

    # Run telemetry collection and mission concurrently
    # We use a task group pattern:
    # - Telemetry collection runs as a background task
    # - Mission runs in the foreground
    # - When mission finishes, we cancel the telemetry task

    # Start telemetry collection as a background task
    telemetry_task = asyncio.create_task(collector.start())

    # Give telemetry streams a moment to initialize
    await asyncio.sleep(2)

    # If a fault scenario was requested, launch it as a background task
    # The scenario runs concurrently with the mission, injecting faults
    # at timed intervals. Because it uses the same injector instance,
    # all fault events are captured in injector.fault_events.
    fault_task = None
    if fault_scenario:
        scenarios = FaultScenarios(injector)
        scenario_map = {
            "s1": scenarios.scenario_gps_degradation,
            "s2": scenarios.scenario_altitude_confusion,
            "s3": scenarios.scenario_sensor_cascade,
            "s4": scenarios.scenario_wind_shear,
        }
        scenario_fn = scenario_map.get(fault_scenario.lower())
        if scenario_fn:
            logger.info(f"Launching fault scenario {fault_scenario} in background...")
            fault_task = asyncio.create_task(scenario_fn(delay_seconds=10))
        else:
            logger.warning(
                f"Unknown fault scenario '{fault_scenario}'. "
                f"Valid options: {', '.join(scenario_map.keys())}"
            )

    # Run the mission
    try:
        mission_result = await run_mission(drone)
        logger.info(f"Mission result: {mission_result.value}")
    except Exception as e:
        logger.error(f"Mission failed: {e}")
        mission_result = MissionResult.FAILURE

    # Cancel fault scenario if still running
    if fault_task and not fault_task.done():
        fault_task.cancel()
        try:
            await fault_task
        except asyncio.CancelledError:
            pass

    # Stop telemetry collection
    collector.stop()
    telemetry_task.cancel()
    try:
        await telemetry_task
    except asyncio.CancelledError:
        pass

    # Record end time
    end_time = datetime.now(timezone.utc)

    # Build and save the complete mission telemetry
    # Pass fault events from the injector into the mission output
    mission_telemetry = collector.build_mission_telemetry(
        start_time=start_time,
        end_time=end_time,
        result=mission_result,
        faults=injector.fault_events,
    )

    filepath = collector.save_to_file(mission_telemetry, output_dir=output_dir)

    # Print summary
    if mission_telemetry.summary:
        s = mission_telemetry.summary
        logger.info("=" * 60)
        logger.info("Mission Summary")
        logger.info("=" * 60)
        logger.info(f"  Duration:        {s.duration_seconds:.1f}s")
        logger.info(f"  Snapshots:       {s.total_snapshots}")
        logger.info(f"  Max altitude:    {s.max_altitude_m:.1f}m")
        logger.info(f"  Distance:        {s.distance_traveled_m:.1f}m")
        logger.info(f"  Min battery:     {s.min_battery_percent:.1f}%")
        logger.info(f"  Max speed:       {s.max_speed_m_s:.1f} m/s")
        logger.info(f"  Faults injected: {len(injector.fault_events)}")
        logger.info(f"  Output file:     {filepath}")
        logger.info("=" * 60)

    # Restore any injected faults to leave simulation in clean state
    if injector.fault_events:
        await injector.restore_all()


if __name__ == "__main__":
    asyncio.run(main())
