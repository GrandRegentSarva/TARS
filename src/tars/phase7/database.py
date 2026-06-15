"""
Neo4j Database Module
=====================
Async Neo4j driver lifecycle, connectivity checks, and transaction helpers.

Provides:
- Driver initialization and shutdown
- Connectivity verification
- Transaction execution helper with automatic rollback on failure
- Session factory for direct use
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TypeVar

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, AsyncTransaction

from .config import settings

logger = logging.getLogger("phase7.database")

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Module-level driver instance
# ---------------------------------------------------------------------------
_driver: Optional[AsyncDriver] = None


async def init_driver() -> AsyncDriver:
    """
    Initialize the Neo4j async driver.

    Safe to call multiple times; returns the existing driver if already
    initialized.

    Returns:
        The initialized AsyncDriver instance.
    """
    global _driver
    if _driver is not None:
        return _driver

    _driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    logger.info("Neo4j driver initialized: %s", settings.NEO4J_URI)
    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver and release resources."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def get_driver() -> AsyncDriver:
    """
    Get the current Neo4j driver instance.

    Raises:
        RuntimeError: If the driver has not been initialized.
    """
    if _driver is None:
        raise RuntimeError(
            "Neo4j driver not initialized. Call init_driver() first."
        )
    return _driver


async def check_connectivity() -> bool:
    """
    Verify Neo4j connectivity by running a lightweight query.

    Returns:
        True if Neo4j is reachable and responsive, False otherwise.
    """
    if _driver is None:
        return False
    try:
        await _driver.verify_connectivity()
        return True
    except Exception as exc:
        logger.warning("Neo4j connectivity check failed: %s", exc)
        return False


def get_session() -> AsyncSession:
    """
    Create a new Neo4j async session.

    The caller is responsible for closing the session.

    Returns:
        A new AsyncSession for the configured database.

    Raises:
        RuntimeError: If the driver has not been initialized.
    """
    driver = get_driver()
    return driver.session(database=settings.NEO4J_DATABASE)


async def execute_read(
    query: str,
    parameters: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Execute a read transaction and return results as dicts.

    Args:
        query: Parameterized Cypher query.
        parameters: Query parameters.

    Returns:
        List of record dicts.
    """
    driver = get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(query, parameters or {})
        records = await result.data()
        return records


async def execute_write(
    query: str,
    parameters: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Execute a write transaction and return results as dicts.

    Args:
        query: Parameterized Cypher query.
        parameters: Query parameters.

    Returns:
        List of record dicts.
    """
    driver = get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(query, parameters or {})
        records = await result.data()
        return records


async def execute_write_transaction(
    work: Callable[[AsyncTransaction], Any],
) -> Any:
    """
    Execute a function within a write transaction with automatic
    commit on success and rollback on failure.

    Args:
        work: Async callable that receives an AsyncTransaction.

    Returns:
        The return value of the work function.
    """
    driver = get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        return await session.execute_write(work)
