"""
Telemetry Data Models -- Pydantic v2
====================================
These models define the exact shape of every piece of telemetry data
that flows through TARS. Using Pydantic gives us:

1. **Type safety** -- catches wrong data types at runtime
2. **Validation** -- ensures values are within expected ranges
3. **JSON serialization** -- .model_dump_json() gives us clean JSON output
4. **Documentation** -- the model IS the documentation

Every field has a description explaining what it represents in drone terms.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums -- Named constants for categorical telemetry values
# =============================================================================

class GpsFixType(str, Enum):
    """
    GPS fix quality levels. Higher = more accurate position.
    
    NO_FIX: GPS receiver can't determine position at all
    FIX_2D: Latitude/longitude only, no altitude (minimum 3 satellites)
    FIX_3D: Full 3D position with altitude (minimum 4 satellites)
    DGPS: Differential GPS -- uses ground station corrections (~1m accuracy)
    RTK_FLOAT: Real-Time Kinematic float -- centimeter-level, still converging
    RTK_FIXED: RTK fixed -- centimeter-level, fully converged (best possible)
    """
    NO_FIX = "NO_FIX"
    NO_GPS = "NO_GPS"
    FIX_2D = "FIX_2D"
    FIX_3D = "FIX_3D"
    DGPS = "DGPS"
    RTK_FLOAT = "RTK_FLOAT"
    RTK_FIXED = "RTK_FIXED"


class MissionResult(str, Enum):
    """Outcome of a completed mission."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ABORTED = "ABORTED"
    IN_PROGRESS = "IN_PROGRESS"


class FaultType(str, Enum):
    """Types of faults that can be injected into the simulation."""
    GPS_BLOCK = "gps_block"
    GPS_NOISE = "gps_noise"
    WIND_GUST = "wind_gust"
    BATTERY_DRAIN = "battery_drain"
    BAROMETER_OFFSET = "barometer_offset"
    MAGNETOMETER_OFFSET = "magnetometer_offset"


# =============================================================================
# Telemetry Component Models -- Each represents one sensor/subsystem
# =============================================================================

class PositionData(BaseModel):
    """
    Drone's position in 3D space.
    
    GPS gives us latitude/longitude (horizontal position on Earth).
    Altitude comes from GPS + barometer fusion.
    
    - absolute_altitude_m: Height above mean sea level (AMSL)
    - relative_altitude_m: Height above the takeoff point (most useful for flying)
    """
    latitude_deg: float = Field(description="Latitude in degrees (WGS84)")
    longitude_deg: float = Field(description="Longitude in degrees (WGS84)")
    absolute_altitude_m: float = Field(description="Altitude above mean sea level in meters")
    relative_altitude_m: float = Field(description="Altitude above takeoff point in meters")


class VelocityData(BaseModel):
    """
    Drone's velocity in NED (North-East-Down) frame.
    
    NED is the standard coordinate frame in aviation:
    - North: positive = moving north
    - East: positive = moving east  
    - Down: positive = moving DOWN (yes, down is positive -- aviation convention)
    
    So a drone climbing has a NEGATIVE down velocity.
    """
    north_m_s: float = Field(description="Velocity northward in m/s")
    east_m_s: float = Field(description="Velocity eastward in m/s")
    down_m_s: float = Field(description="Velocity downward in m/s (negative = climbing)")


class BatteryData(BaseModel):
    """
    Battery state.
    
    Voltage drops as the battery discharges. A typical 3S LiPo:
    - Full: ~12.6V (4.2V per cell x 3)
    - Empty: ~10.5V (3.5V per cell x 3)
    
    remaining_percent is estimated by PX4 based on voltage curve + current draw.
    """
    voltage_v: float = Field(description="Battery voltage in volts")
    remaining_percent: float = Field(
        description="Estimated remaining capacity (0-100)",
        ge=0.0,
        le=100.0,
    )


class GpsData(BaseModel):
    """
    GPS receiver status.
    
    num_satellites: More satellites = better accuracy. Minimum 4 for 3D fix.
    fix_type: Quality level of the GPS solution.
    
    In simulation, PX4 SITL typically reports 10-12 satellites with FIX_3D.
    When we inject GPS faults, these values degrade.
    """
    num_satellites: int = Field(description="Number of visible GPS satellites", ge=0)
    fix_type: GpsFixType = Field(description="GPS fix quality level")


class AttitudeData(BaseModel):
    """
    Drone's orientation in 3D space (Euler angles).
    
    - roll: Tilt left/right (positive = right wing down)
    - pitch: Tilt forward/backward (positive = nose up)
    - yaw: Compass heading (0=North, 90=East, 180=South, 270=West)
    
    In stable hover, roll and pitch should be near 0.
    Large roll/pitch values during hover = something is wrong (wind, motor issue).
    """
    roll_deg: float = Field(description="Roll angle in degrees")
    pitch_deg: float = Field(description="Pitch angle in degrees")
    yaw_deg: float = Field(description="Yaw angle in degrees (compass heading)")


class HealthData(BaseModel):
    """
    PX4 health checks -- the autopilot's self-assessment.
    
    PX4 runs continuous calibration checks on its sensors.
    If any of these are False, the drone may refuse to arm or may
    trigger a failsafe during flight.
    
    These are the flags that Phase 4's Incident Engine will monitor
    to detect sensor degradation.
    """
    is_gyrometer_calibration_ok: bool = Field(description="Gyroscope calibration status")
    is_accelerometer_calibration_ok: bool = Field(description="Accelerometer calibration status")
    is_magnetometer_calibration_ok: bool = Field(description="Magnetometer calibration status")
    is_home_position_ok: bool = Field(description="Home position has been set")
    is_global_position_ok: bool = Field(description="Global position (GPS) is available")


# =============================================================================
# Composite Models -- Combine components into full snapshots and missions
# =============================================================================

class TelemetrySnapshot(BaseModel):
    """
    A single point-in-time capture of all telemetry data.
    
    This is what the telemetry collector produces every 1 second (at 1 Hz).
    It combines all sensor data into one unified snapshot with a timestamp.
    
    Think of it as: "At this exact moment, here's everything we know about the drone."
    """
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of this snapshot",
    )
    position: Optional[PositionData] = Field(default=None, description="GPS position")
    velocity: Optional[VelocityData] = Field(default=None, description="NED velocity")
    battery: Optional[BatteryData] = Field(default=None, description="Battery state")
    gps: Optional[GpsData] = Field(default=None, description="GPS receiver status")
    attitude: Optional[AttitudeData] = Field(default=None, description="Orientation angles")
    flight_mode: Optional[str] = Field(default=None, description="Current PX4 flight mode")
    health: Optional[HealthData] = Field(default=None, description="PX4 health checks")


class FaultEvent(BaseModel):
    """
    Records when a fault was injected during a mission.
    
    This metadata is crucial for Phase 4 -- the Incident Engine needs to know
    what faults were active to correlate with telemetry anomalies.
    """
    fault_type: FaultType = Field(description="Type of fault injected")
    triggered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the fault was triggered",
    )
    parameters: dict = Field(
        default_factory=dict,
        description="Fault-specific parameters (e.g., wind speed, noise level)",
    )
    description: str = Field(default="", description="Human-readable description")


class MissionSummary(BaseModel):
    """
    Computed summary statistics for a completed mission.
    
    These aggregate metrics give a quick overview without reading
    every telemetry snapshot. Useful for Phase 2 (Mission Replay)
    and Phase 9 (Evaluation Layer).
    """
    total_snapshots: int = Field(description="Number of telemetry snapshots collected")
    duration_seconds: float = Field(description="Total mission duration in seconds")
    max_altitude_m: float = Field(default=0.0, description="Peak altitude reached")
    distance_traveled_m: float = Field(default=0.0, description="Approximate total distance")
    min_battery_percent: float = Field(default=100.0, description="Lowest battery level observed")
    max_speed_m_s: float = Field(default=0.0, description="Peak ground speed")
    collection_rate_hz: float = Field(default=1.0, description="Telemetry collection rate")


class MissionTelemetry(BaseModel):
    """
    Complete telemetry record for an entire mission.
    
    This is the top-level output file -- everything about a mission in one JSON.
    It's the primary input for Phase 2 (Mission Replay System).
    
    Structure:
    - Metadata: mission_id, drone_id, timestamps
    - Faults: what was injected and when
    - Telemetry: array of time-series snapshots
    - Result: SUCCESS / FAILURE / ABORTED
    - Summary: computed aggregate statistics
    """
    mission_id: str = Field(description="Unique mission identifier")
    drone_id: str = Field(default="tars-sim-01", description="Drone identifier")
    start_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Mission start time (UTC)",
    )
    end_time: Optional[datetime] = Field(default=None, description="Mission end time (UTC)")
    faults_injected: list[FaultEvent] = Field(
        default_factory=list,
        description="Faults injected during this mission",
    )
    telemetry: list[TelemetrySnapshot] = Field(
        default_factory=list,
        description="Time-series telemetry snapshots",
    )
    mission_result: MissionResult = Field(
        default=MissionResult.IN_PROGRESS,
        description="Final mission outcome",
    )
    summary: Optional[MissionSummary] = Field(
        default=None,
        description="Computed summary statistics",
    )
