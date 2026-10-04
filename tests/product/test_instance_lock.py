from __future__ import annotations

import os

import pytest

pytest.importorskip("msvcrt", reason="Windows 전용 파일 잠금 (msvcrt)")
from pharma_proto.instance_lock import InstanceAlreadyRunning, InstanceLock


def test_instance_lock_blocks_a_second_owner_and_can_be_reacquired(tmp_path):
    path = tmp_path / "runtime" / "instance.lock"
    first = InstanceLock.acquire(path)
    try:
        with pytest.raises(InstanceAlreadyRunning):
            InstanceLock.acquire(path)
        first.write_state(pid=os.getpid(), port=43123)
        assert InstanceLock.read_state(path) == {"pid": os.getpid(), "port": 43123}
    finally:
        first.release()

    assert InstanceLock.read_state(path) is None
    second = InstanceLock.acquire(path)
    second.release()


def test_instance_lock_release_is_idempotent(tmp_path):
    lock = InstanceLock.acquire(tmp_path / "instance.lock")
    lock.release()
    lock.release()
