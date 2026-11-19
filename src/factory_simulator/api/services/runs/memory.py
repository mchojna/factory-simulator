"""The memory of the server: the running runs it keeps and their locks.

Examples:
    >>> Server(version="0.1.0").memories
    {}
"""

import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

from factory_simulator import engine


@dataclass(frozen=True, slots=True, kw_only=True)
class RunMemory:
    """What the server keeps in memory of a running run.

    Attributes:
        world (World): The world of the run.
        state (State): The state in which the decisions of its period are made.
        interaction_count (int, optional): The number of its rows in
            `interactions`; 0 when not given.

    Examples:
        >>> from decimal import Decimal
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> RunMemory(world=world, state=engine.build_state(world)).interaction_count
        0
    """

    world: engine.World
    state: engine.State
    interaction_count: int = 0


@dataclass(slots=True, kw_only=True)
class Server:
    """The version of the server and what it keeps of running runs.

    Attributes:
        version (str): The version of the package.
        memories (dict[str, RunMemory]): The memory of each running run, by
            identifier.
        locks (dict[str, Lock]): The lock of each run that a request holds or waits
            for.
        lock_users (dict[str, int]): The number of requests that hold or wait for the
            lock of each run in `locks`.
        registry_lock (Lock): The lock over `memories`, `locks` and `lock_users`.

    Examples:
        >>> Server(version="0.1.0").version
        '0.1.0'
    """

    version: str
    memories: dict[str, RunMemory] = field(default_factory=dict[str, RunMemory])
    locks: dict[str, threading.Lock] = field(default_factory=dict[str, threading.Lock])
    lock_users: dict[str, int] = field(default_factory=dict[str, int])
    registry_lock: threading.Lock = field(default_factory=threading.Lock)


def memory_of(server: Server, run_id: str) -> RunMemory | None:
    """Give what the server keeps of a running run, or None.

    Args:
        server (Server): The server.
        run_id (str): The identifier of the run.

    Returns:
        RunMemory | None: The world and state of the run, or None when not kept.

    Examples:
        >>> memory_of(Server(version="0.1.0"), "r-1") is None
        True
    """
    with server.registry_lock:
        return server.memories.get(run_id)


def keep_memory(server: Server, run_id: str, memory: RunMemory) -> None:
    """Keep the memory of a running run.

    Args:
        server (Server): The server, changed in place.
        run_id (str): The identifier of the run.
        memory (RunMemory): The world and state of the run.

    Examples:
        >>> from decimal import Decimal
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> server = Server(version="0.1.0")
        >>> memory = RunMemory(world=world, state=engine.build_state(world))
        >>> keep_memory(server, "r-1", memory)
        >>> memory_of(server, "r-1") is memory, server.locks
        (True, {})
    """
    with server.registry_lock:
        server.memories[run_id] = memory


def forget_memory(server: Server, run_id: str) -> None:
    """Forget the memory of a run that has finished.

    Args:
        server (Server): The server, changed in place.
        run_id (str): The identifier of the run.

    Examples:
        >>> from decimal import Decimal
        >>> world = engine.draw_world(
        ...     engine.Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=engine.Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     engine.Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> server = Server(version="0.1.0")
        >>> memory = RunMemory(world=world, state=engine.build_state(world))
        >>> keep_memory(server, "r-1", memory)
        >>> forget_memory(server, "r-1")
        >>> memory_of(server, "r-1") is None
        True
    """
    with server.registry_lock:
        del server.memories[run_id]


@contextmanager
def hold_lock(server: Server, run_id: str) -> Generator[None]:
    """Hold the lock of a run; the last request to leave the lock removes it.

    Every request that holds or waits for the lock of a run counts in `lock_users`,
    so all of them share one lock until the count falls to 0.

    Args:
        server (Server): The server, changed in place.
        run_id (str): The identifier of the run.

    Yields:
        None: Nothing; the lock is held until the block ends.

    Examples:
        >>> server = Server(version="0.1.0")
        >>> with hold_lock(server, "r-1"):
        ...     server.lock_users
        {'r-1': 1}
        >>> server.locks, server.lock_users
        ({}, {})
    """
    with server.registry_lock:
        lock = server.locks.setdefault(run_id, threading.Lock())
        server.lock_users[run_id] = server.lock_users.get(run_id, 0) + 1
    try:
        with lock:
            yield
    finally:
        with server.registry_lock:
            server.lock_users[run_id] -= 1
            if server.lock_users[run_id] == 0:
                del server.lock_users[run_id]
                del server.locks[run_id]
