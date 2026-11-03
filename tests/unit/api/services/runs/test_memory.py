import threading
from typing import cast

from factory_simulator.api.services.runs.memory import Server, hold_lock


# A lock that sets `waited` once a second taker comes to it.
class WaitedLock:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.takers = 0
        self.counted = threading.Lock()
        self.waited = threading.Event()

    def __enter__(self) -> bool:
        with self.counted:
            self.takers += 1
            if self.takers == 2:
                self.waited.set()
        return self.lock.acquire()

    def __exit__(self, *_: object) -> None:
        self.lock.release()


def test_the_lock_of_a_run_is_reclaimed_when_its_last_request_leaves():
    server = Server(version="0.1.0")

    with hold_lock(server, "r-1"):
        held = "r-1" in server.locks

    assert held
    assert server.locks == {}


def test_a_lock_a_request_waits_for_stays_the_lock_of_the_run_after_its_holder_leaves():
    server = Server(version="0.1.0")
    lock = WaitedLock()
    server.locks["r-1"] = cast(threading.Lock, lock)
    seen: list[object] = []

    def wait_for_the_lock() -> None:
        with hold_lock(server, "r-1"):
            seen.append(server.locks.get("r-1"))

    with hold_lock(server, "r-1"):
        waiter = threading.Thread(target=wait_for_the_lock)
        waiter.start()
        lock.waited.wait()
        held = server.locks.get("r-1")
    waiter.join()

    assert held is lock
    assert seen == [lock]
    assert server.locks == {}
    assert server.lock_users == {}
