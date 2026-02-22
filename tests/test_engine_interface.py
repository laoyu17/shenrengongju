from __future__ import annotations

from rtos_sim.core.engine import SimEngine
from rtos_sim.core.interfaces import ISimEngine


def test_isimengine_declares_resume_and_stop() -> None:
    abstract_methods = ISimEngine.__abstractmethods__
    assert "resume" in abstract_methods
    assert "stop" in abstract_methods


def test_simengine_implements_interface_contract() -> None:
    engine = SimEngine()
    assert isinstance(engine, ISimEngine)
    assert callable(engine.resume)
    assert callable(engine.stop)
