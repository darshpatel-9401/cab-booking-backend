import routers.rides as rides_module
from models import RIDE_ACCEPTED, RIDE_IN_PROGRESS, RIDE_REQUESTED


def test_only_waiting_or_accepted_rides_can_be_cancelled():
    assert set(rides_module.CANCELLABLE_STATUSES) == {RIDE_REQUESTED, RIDE_ACCEPTED}


def test_active_statuses_cover_the_whole_trip():
    assert set(rides_module.ACTIVE_STATUSES) == {
        RIDE_REQUESTED,
        RIDE_ACCEPTED,
        RIDE_IN_PROGRESS,
    }