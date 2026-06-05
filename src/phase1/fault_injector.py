"""
Fault Injector -- Phase 1
=========================
Injects realistic faults into PX4 SITL simulation to test drone resilience.

How fault injection works in PX4 SITL:
- PX4 has built-in simulation parameters (SIM_*) that control sensor behavior
- Setting these parameters via MAVLink changes the simulated sensor outputs
- The drone's autopilot then has to deal with degraded/faulty sensor data
- This is exactly what happens in real-world failures

Available fault types:
1. GPS Block     -- Simulates complete GPS signal loss
2. GPS Noise     -- Adds noise to GPS readings (urban canyon, interference)
3. Battery Drain -- Simulates accelerated battery discharge
4. Baro Offset   -- Adds offset to barometer (altitude errors)
5. Mag Offset    -- Adds offset to magnetometer (compass errors)
6. Wind          -- Configures wind in the simulation environment

Usage:
    # Standalone -- inject faults interactively
    python -m src.phase1.fault_injector

    # As a module -- use in mission scripts
    from src.phase1.fault_injector import FaultInjector
    injector = FaultInjector(drone)
    await injector.inject_gps_block()
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from mavsdk import System
from mavsdk.param import Param

from .models.telemetry import FaultEvent, FaultType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("fault_injector")


class FaultInjector:
    """
    Injects faults into PX4 SITL simulation via MAVLink parameter changes.

    How it works:
    - PX4 SITL has special SIM_* parameters that control simulated sensor behavior
    - We change these parameters at runtime using MAVSDK's param plugin
    - PX4's autopilot immediately sees the degraded sensor data
    - The drone's behavior changes in response (failsafes, mode changes, etc.)

    This is the same mechanism PX4 developers use for testing failsafes.

    Important: These parameters only exist in SITL (simulation). They don't
    exist on real flight controllers. Real fault injection requires different
    approaches (hardware-in-the-loop, signal generators, etc.).
    """

    def __init__(self, drone: System):
        """
        Args:
            drone: Connected MAVSDK System instance
        """
        self.drone = drone
        # Track all injected faults for mission telemetry metadata
        self._fault_events: list[FaultEvent] = []
        # Track original parameter values so we can restore them
        self._original_params: dict[str, float] = {}

    @property
    def fault_events(self) -> list[FaultEvent]:
        """List of all fault events injected during this session."""
        return self._fault_events

    # =========================================================================
    # Parameter Helpers
    # =========================================================================

    async def _set_param_float(self, name: str, value: float):
        """
        Set a PX4 parameter to a float value.

        PX4 parameters are the autopilot's configuration system.
        There are ~1000 parameters controlling everything from
        PID gains to failsafe thresholds to simulation behavior.

        We save the original value first so we can restore it later.
        """
        # Save original value if we haven't already
        if name not in self._original_params:
            try:
                result = await self.drone.param.get_param_float(name)
                self._original_params[name] = result
                logger.debug(f"Saved original {name} = {result}")
            except Exception:
                logger.debug(f"Could not read original value for {name}")

        await self.drone.param.set_param_float(name, value)
        logger.info(f"[PARAM] Set {name} = {value}")

    async def _set_param_int(self, name: str, value: int):
        """Set a PX4 parameter to an integer value."""
        if name not in self._original_params:
            try:
                result = await self.drone.param.get_param_int(name)
                self._original_params[name] = float(result)
            except Exception:
                pass

        await self.drone.param.set_param_int(name, value)
        logger.info(f"[PARAM] Set {name} = {value}")

    def _record_fault(self, fault_type: FaultType, params: dict, description: str):
        """Record a fault event for mission telemetry metadata."""
        event = FaultEvent(
            fault_type=fault_type,
            triggered_at=datetime.now(timezone.utc),
            parameters=params,
            description=description,
        )
        self._fault_events.append(event)
        logger.info(f"[FAULT] Recorded: {description}")

    # =========================================================================
    # GPS Faults
    # =========================================================================

    async def inject_gps_block(self):
        """
        Block GPS signal completely.

        What happens:
        - PX4 parameter SIM_GPS_BLOCK = 1 tells the simulator to stop
          sending GPS data to the autopilot
        - The drone loses its global position estimate
        - PX4 may switch to a failsafe mode (LAND or RETURN depending on config)
        - GPS satellite count drops to 0, fix type becomes NO_GPS

        Real-world equivalent:
        - Flying under a bridge or in a tunnel
        - GPS jamming (intentional interference)
        - Flying in deep urban canyons between tall buildings

        This is what happened to NASA's Ingenuity -- it lost visual
        navigation references, similar to losing GPS.
        """
        logger.warning("INJECTING FAULT: GPS Block")
        await self._set_param_int("SIM_GPS_BLOCK", 1)
        self._record_fault(
            FaultType.GPS_BLOCK,
            {"SIM_GPS_BLOCK": 1},
            "GPS signal blocked -- simulating complete GPS loss",
        )

    async def restore_gps(self):
        """Restore GPS signal after blocking."""
        logger.info("RESTORING: GPS signal")
        await self._set_param_int("SIM_GPS_BLOCK", 0)

    async def inject_gps_noise(self, noise_level: float = 20.0):
        """
        Add noise to GPS readings.

        Args:
            noise_level: Noise amplitude in meters. Higher = more inaccurate GPS.
                         5.0  = mild (normal urban environment)
                         20.0 = moderate (near buildings, some interference)
                         50.0 = severe (heavy jamming, deep urban canyon)

        What happens:
        - GPS position readings become noisy/jumpy
        - The drone's position estimate becomes uncertain
        - PX4's EKF (Extended Kalman Filter) tries to filter the noise
        - If noise is too high, EKF may reject GPS entirely

        Real-world equivalent:
        - Multipath interference (GPS signals bouncing off buildings)
        - Partial GPS jamming
        - Solar storms affecting satellite signals
        """
        logger.warning(f"INJECTING FAULT: GPS Noise (level={noise_level}m)")
        await self._set_param_float("SIM_GPS_NOISE", noise_level)
        self._record_fault(
            FaultType.GPS_NOISE,
            {"SIM_GPS_NOISE": noise_level},
            f"GPS noise injected -- {noise_level}m position uncertainty",
        )

    async def restore_gps_noise(self):
        """Remove GPS noise."""
        logger.info("RESTORING: GPS noise removed")
        await self._set_param_float("SIM_GPS_NOISE", 0.0)

    # =========================================================================
    # Battery Faults
    # =========================================================================

    async def inject_battery_drain(self, empty_voltage: float = 3.7):
        """
        Simulate accelerated battery drain by raising the "empty" voltage threshold.

        Args:
            empty_voltage: Voltage per cell considered "empty".
                          Default real value: 3.5V
                          3.7V = triggers low battery warning sooner
                          3.9V = triggers critical battery very quickly
                          4.0V = almost immediate critical battery

        What happens:
        - PX4 thinks the battery is emptier than it actually is
        - Low battery warnings trigger earlier
        - If critical threshold is reached, PX4 triggers RTL (Return to Launch)
          or LAND failsafe automatically

        Real-world equivalent:
        - Old/degraded battery with reduced capacity
        - Cold weather reducing battery performance
        - Heavy payload increasing power consumption

        This is relevant to the Amazon MK30 crash -- battery/power
        management failures can cascade into control failures.
        """
        logger.warning(f"INJECTING FAULT: Battery drain (empty_voltage={empty_voltage}V/cell)")
        await self._set_param_float("BAT1_V_EMPTY", empty_voltage)
        self._record_fault(
            FaultType.BATTERY_DRAIN,
            {"BAT1_V_EMPTY": empty_voltage},
            f"Battery drain simulated -- empty threshold raised to {empty_voltage}V/cell",
        )

    async def restore_battery(self):
        """Restore normal battery parameters."""
        logger.info("RESTORING: Battery parameters")
        original = self._original_params.get("BAT1_V_EMPTY", 3.5)
        await self._set_param_float("BAT1_V_EMPTY", original)

    # =========================================================================
    # Barometer Faults
    # =========================================================================

    async def inject_baro_offset(self, offset_m: float = 10.0):
        """
        Add an offset to the barometer reading.

        Args:
            offset_m: Altitude offset in meters.
                     10.0  = drone thinks it's 10m higher than it is
                     -10.0 = drone thinks it's 10m lower than it is

        What happens:
        - The barometer reports incorrect altitude
        - PX4's altitude estimate becomes wrong
        - If the drone thinks it's higher than it is, it may descend into the ground
        - PX4's EKF fuses baro with GPS altitude to detect inconsistencies

        Real-world equivalent:
        - Weather pressure changes (barometers measure air pressure, not altitude directly)
        - Prop wash affecting barometer readings
        - Flying near buildings that create pressure differentials

        This is directly related to the Amazon MK30 crash -- the drone
        thought it had landed (altitude = 0) when it was still in the air.
        """
        logger.warning(f"INJECTING FAULT: Barometer offset ({offset_m}m)")
        await self._set_param_float("SIM_BARO_OFF", offset_m)
        self._record_fault(
            FaultType.BAROMETER_OFFSET,
            {"SIM_BARO_OFF": offset_m},
            f"Barometer offset -- drone altitude reading off by {offset_m}m",
        )

    async def restore_baro(self):
        """Remove barometer offset."""
        logger.info("RESTORING: Barometer offset removed")
        await self._set_param_float("SIM_BARO_OFF", 0.0)

    # =========================================================================
    # Magnetometer Faults
    # =========================================================================

    async def inject_mag_offset(
        self,
        x_offset: float = 0.2,
        y_offset: float = 0.2,
        z_offset: float = 0.0,
    ):
        """
        Add offsets to magnetometer readings.

        Args:
            x_offset: Offset on X axis (Gauss)
            y_offset: Offset on Y axis (Gauss)
            z_offset: Offset on Z axis (Gauss)

        What happens:
        - The compass heading becomes incorrect
        - The drone may fly in the wrong direction
        - PX4's EKF tries to detect and compensate for mag interference
        - Large offsets may cause EKF to reject magnetometer data entirely

        Real-world equivalent:
        - Flying near metal structures (bridges, power lines)
        - Electromagnetic interference from motors or electronics
        - Magnetic anomalies in certain geographic areas
        """
        logger.warning(
            f"INJECTING FAULT: Magnetometer offset "
            f"(x={x_offset}, y={y_offset}, z={z_offset} Gauss)"
        )
        await self._set_param_float("SIM_MAG_OFFSET_X", x_offset)
        await self._set_param_float("SIM_MAG_OFFSET_Y", y_offset)
        await self._set_param_float("SIM_MAG_OFFSET_Z", z_offset)
        self._record_fault(
            FaultType.MAGNETOMETER_OFFSET,
            {
                "SIM_MAG_OFFSET_X": x_offset,
                "SIM_MAG_OFFSET_Y": y_offset,
                "SIM_MAG_OFFSET_Z": z_offset,
            },
            f"Magnetometer offset -- compass heading corrupted",
        )

    async def restore_mag(self):
        """Remove magnetometer offsets."""
        logger.info("RESTORING: Magnetometer offsets removed")
        await self._set_param_float("SIM_MAG_OFFSET_X", 0.0)
        await self._set_param_float("SIM_MAG_OFFSET_Y", 0.0)
        await self._set_param_float("SIM_MAG_OFFSET_Z", 0.0)

    # =========================================================================
    # Restore All
    # =========================================================================

    async def restore_all(self):
        """
        Restore all parameters to their original values.

        Call this after a mission to clean up all injected faults.
        Important for reproducibility -- you don't want faults from
        one mission leaking into the next.
        """
        logger.info("Restoring all parameters to original values...")
        await self.restore_gps()
        await self.restore_gps_noise()
        await self.restore_battery()
        await self.restore_baro()
        await self.restore_mag()
        logger.info("All parameters restored")


# =============================================================================
# Fault Scenarios -- Pre-built combinations for testing
# =============================================================================

class FaultScenarios:
    """
    Pre-built fault scenarios that combine multiple faults.

    These simulate realistic failure patterns rather than single-fault cases.
    Each scenario is inspired by real-world drone incidents.
    """

    def __init__(self, injector: FaultInjector):
        self.injector = injector

    async def scenario_gps_degradation(self, delay_seconds: float = 30.0):
        """
        Progressive GPS degradation scenario.

        Timeline:
        1. Start with normal GPS
        2. After delay: add moderate GPS noise (urban environment)
        3. After 15s more: increase noise (heavy interference)
        4. After 15s more: complete GPS block

        Inspired by: NASA Ingenuity losing visual references over
        featureless terrain -- progressive localization failure.
        """
        logger.info("SCENARIO: Progressive GPS Degradation")
        logger.info(f"   Starting in {delay_seconds}s...")

        await asyncio.sleep(delay_seconds)

        logger.info("   Phase 1: Moderate GPS noise (urban environment)")
        await self.injector.inject_gps_noise(10.0)

        await asyncio.sleep(15)

        logger.info("   Phase 2: Heavy GPS noise (severe interference)")
        await self.injector.inject_gps_noise(30.0)

        await asyncio.sleep(15)

        logger.info("   Phase 3: Complete GPS block")
        await self.injector.inject_gps_block()

    async def scenario_altitude_confusion(self, delay_seconds: float = 20.0):
        """
        Altitude sensor confusion scenario.

        Combines barometer offset with GPS noise to create conflicting
        altitude readings -- the autopilot gets confused about its height.

        Inspired by: Amazon MK30 crash -- faulty altitude readings led
        the system to think it had landed while still airborne.
        """
        logger.info("SCENARIO: Altitude Confusion")
        logger.info(f"   Starting in {delay_seconds}s...")

        await asyncio.sleep(delay_seconds)

        logger.info("   Injecting barometer offset + GPS noise")
        await self.injector.inject_baro_offset(15.0)  # Think we're 15m higher
        await self.injector.inject_gps_noise(10.0)    # GPS also unreliable

    async def scenario_sensor_cascade(self, delay_seconds: float = 25.0):
        """
        Cascading sensor failure scenario.

        Multiple sensors degrade simultaneously -- magnetometer interference
        plus GPS noise plus barometer offset. This overwhelms the EKF
        (Extended Kalman Filter) which tries to fuse all sensor data.

        Inspired by: Bell 525 crash -- adverse feedback loops in the
        control system amplified small errors into catastrophic failure.
        """
        logger.info("SCENARIO: Sensor Cascade Failure")
        logger.info(f"   Starting in {delay_seconds}s...")

        await asyncio.sleep(delay_seconds)

        logger.info("   Phase 1: Magnetometer interference")
        await self.injector.inject_mag_offset(0.3, 0.3, 0.1)

        await asyncio.sleep(10)

        logger.info("   Phase 2: Adding GPS noise")
        await self.injector.inject_gps_noise(15.0)

        await asyncio.sleep(10)

        logger.info("   Phase 3: Adding barometer offset")
        await self.injector.inject_baro_offset(8.0)


# =============================================================================
# Standalone Mode -- Interactive fault injection for testing
# =============================================================================

async def main():
    """
    Interactive fault injection tool.

    Connects to PX4 SITL and lets you inject faults manually.
    Useful for testing while a mission is running in another terminal.

    Usage: python -m src.phase1.fault_injector
    """
    connection_str = os.getenv("PX4_CONNECTION", "udp://:14540")

    logger.info("Connecting to PX4 SITL...")
    drone = System()
    await drone.connect(system_address=connection_str)

    # Wait for connection
    async for state in drone.core.connection_state():
        if state.is_connected:
            logger.info("Connected to PX4 SITL")
            break

    injector = FaultInjector(drone)
    scenarios = FaultScenarios(injector)

    print("\n" + "=" * 60)
    print("TARS Fault Injector -- Interactive Mode")
    print("=" * 60)
    print("\nAvailable commands:")
    print("  1  -- Block GPS")
    print("  2  -- Add GPS noise")
    print("  3  -- Simulate battery drain")
    print("  4  -- Add barometer offset")
    print("  5  -- Add magnetometer offset")
    print("  6  -- Restore all faults")
    print("  s1 -- Scenario: Progressive GPS degradation")
    print("  s2 -- Scenario: Altitude confusion")
    print("  s3 -- Scenario: Sensor cascade failure")
    print("  q  -- Quit")
    print("=" * 60)

    while True:
        try:
            cmd = input("\n> Enter command: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd == "1":
            await injector.inject_gps_block()
        elif cmd == "2":
            await injector.inject_gps_noise(20.0)
        elif cmd == "3":
            await injector.inject_battery_drain(3.9)
        elif cmd == "4":
            await injector.inject_baro_offset(10.0)
        elif cmd == "5":
            await injector.inject_mag_offset(0.3, 0.3, 0.1)
        elif cmd == "6":
            await injector.restore_all()
        elif cmd == "s1":
            asyncio.create_task(scenarios.scenario_gps_degradation(delay_seconds=5))
        elif cmd == "s2":
            asyncio.create_task(scenarios.scenario_altitude_confusion(delay_seconds=5))
        elif cmd == "s3":
            asyncio.create_task(scenarios.scenario_sensor_cascade(delay_seconds=5))
        elif cmd == "q":
            await injector.restore_all()
            break
        else:
            print("Unknown command. Try 1-6, s1-s3, or q.")

    logger.info("Fault injector stopped.")


if __name__ == "__main__":
    asyncio.run(main())
