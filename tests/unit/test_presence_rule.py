"""Tests unitaires — règle de présence."""

from src.domain.rules.presence_rule import can_enter, can_exit
from src.domain.value_objects.enums import PresenceStatus


def test_can_enter_if_absent():
    assert can_enter(None) is True


def test_can_enter_if_out():
    assert can_enter(PresenceStatus.OUT) is True


def test_cannot_enter_if_already_in():
    assert can_enter(PresenceStatus.IN) is False


def test_can_exit_if_in():
    assert can_exit(PresenceStatus.IN) is True


def test_cannot_exit_if_out():
    assert can_exit(PresenceStatus.OUT) is False


def test_cannot_exit_if_unknown():
    assert can_exit(None) is False
