"""Desk /dev/shm follows host RAM instead of a fixed 256 MiB."""

from autonomous.services.desk import _SHM_FLOOR, shm_size_bytes


def test_shm_is_half_the_ram_and_never_below_the_floor():
    assert shm_size_bytes(8 * 1024 ** 3) == 4 * 1024 ** 3
    assert shm_size_bytes(128 * 1024 ** 2) == _SHM_FLOOR
    assert shm_size_bytes(0) == _SHM_FLOOR
    assert shm_size_bytes(-1) == _SHM_FLOOR


def test_live_host_shm_matches_half_the_ram():
    from autonomous.services.desk import mem_total_bytes

    total = mem_total_bytes()
    assert total > 0
    assert shm_size_bytes() == max(_SHM_FLOOR, total // 2)
