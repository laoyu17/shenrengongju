from __future__ import annotations

from rtos_sim.protocols import PCPResourceProtocol, ResourceRuntimeSpec


def _resources(*resource_ids: str, ceiling: float = 1.0) -> dict[str, ResourceRuntimeSpec]:
    return {
        resource_id: ResourceRuntimeSpec(bound_core_id="c0", ceiling_priority=ceiling)
        for resource_id in resource_ids
    }


def test_pcp_request_reentry_and_busy_owner_metadata() -> None:
    protocol = PCPResourceProtocol()
    protocol.configure(_resources("r0", ceiling=3.0))
    protocol.set_priority_domain("absolute_deadline")

    first = protocol.request("segA", "r0", "c0", priority=1.0)
    again = protocol.request("segA", "r0", "c0", priority=1.0)
    busy = protocol.request("segB", "r0", "c0", priority=2.0)

    assert first.granted is True
    assert first.metadata["priority_domain"] == "absolute_deadline"
    assert again.granted is True
    assert busy.granted is False
    assert busy.reason == "resource_busy"
    assert busy.metadata["owner_segment"] == "segA"


def test_pcp_release_non_owner_and_best_waiter_selection() -> None:
    protocol = PCPResourceProtocol()
    protocol.configure(_resources("r0", ceiling=5.0))

    assert protocol.release("nobody", "r0").woken == []
    assert protocol.request("owner", "r0", "c0", priority=1.0).granted is True
    assert protocol.request("w1", "r0", "c0", priority=2.0).granted is False
    assert protocol.request("w2", "r0", "c0", priority=3.0).granted is False
    # Update existing waiter priority to ensure queue replacement path is covered.
    assert protocol.request("w1", "r0", "c0", priority=4.0).granted is False

    release = protocol.release("owner", "r0")
    assert release.woken == ["w1"]


def test_pcp_system_ceiling_block_and_deferred_wake() -> None:
    protocol = PCPResourceProtocol()
    protocol.configure(
        {
            "r0": ResourceRuntimeSpec(bound_core_id="c0", ceiling_priority=10.0),
            "r1": ResourceRuntimeSpec(bound_core_id="c0", ceiling_priority=2.0),
        }
    )

    assert protocol.request("holder", "r0", "c0", priority=1.0).granted is True
    blocked = protocol.request("waiter", "r1", "c0", priority=1.0)
    assert blocked.granted is False
    assert blocked.reason == "system_ceiling_block"
    assert blocked.metadata["system_ceiling"] == 10.0

    release = protocol.release("holder", "r0")
    assert "waiter" in release.woken


def test_pcp_dynamic_ceiling_update_changes_block_decision() -> None:
    protocol = PCPResourceProtocol()
    protocol.configure(
        {
            "r0": ResourceRuntimeSpec(bound_core_id="c0", ceiling_priority=-1e18),
            "r1": ResourceRuntimeSpec(bound_core_id="c0", ceiling_priority=-1e18),
        }
    )
    protocol.set_priority_domain("absolute_deadline")

    assert protocol.request("owner", "r0", "c0", priority=-50.0).granted is True
    protocol.update_resource_ceilings({"r0": -5.0, "r1": -20.0})
    blocked = protocol.request("waiter", "r1", "c0", priority=-20.0)

    assert blocked.granted is False
    assert blocked.reason == "system_ceiling_block"
    assert blocked.metadata["system_ceiling"] == -5.0


def test_pcp_cancel_segment_releases_owned_resources_and_noop_for_unknown() -> None:
    protocol = PCPResourceProtocol()
    protocol.configure(_resources("r0", "r1", ceiling=4.0))

    assert protocol.request("owner", "r0", "c0", priority=1.0).granted is True
    assert protocol.request("owner", "r1", "c0", priority=1.0).granted is True
    assert protocol.request("w0", "r0", "c0", priority=2.0).granted is False
    assert protocol.request("w1", "r1", "c0", priority=3.0).granted is False

    cancel = protocol.cancel_segment("owner")
    assert set(cancel.woken) == {"w0", "w1"}
    assert protocol.cancel_segment("missing").woken == []


def test_pcp_internal_helper_branches_are_stable() -> None:
    protocol = PCPResourceProtocol()
    protocol.configure(_resources("r0", "r1", ceiling=5.0))

    # _try_wake_ceiling_blocked: target resource occupied branch.
    protocol._ceiling_blocked["segX"] = ("r1", 1.0)  # type: ignore[attr-defined]
    protocol._owners["r1"] = "holder"  # type: ignore[attr-defined]
    assert protocol._try_wake_ceiling_blocked() == []  # type: ignore[attr-defined]

    # _try_wake_ceiling_blocked: still blocked by system ceiling branch.
    protocol._owners["r1"] = None  # type: ignore[attr-defined]
    protocol._owners["r0"] = "holder"  # type: ignore[attr-defined]
    protocol._ceilings["r0"] = 5.0  # type: ignore[attr-defined]
    assert protocol._try_wake_ceiling_blocked() == []  # type: ignore[attr-defined]

    # _current_system_ceiling: None ceiling entry is ignored.
    protocol._ceilings["r0"] = None  # type: ignore[attr-defined]
    assert protocol._current_system_ceiling() is None  # type: ignore[attr-defined]

    protocol._owners["r0"] = None  # type: ignore[attr-defined]
    assert protocol._try_wake_ceiling_blocked() == ["segX"]  # type: ignore[attr-defined]

    # _recompute_segment_priority no-op branches.
    assert protocol._recompute_segment_priority("ghost") == {}  # type: ignore[attr-defined]
    protocol._segment_base_priority["segY"] = 2.0  # type: ignore[attr-defined]
    protocol._segment_effective_priority["segY"] = 2.0  # type: ignore[attr-defined]
    protocol._held_by_segment["segY"] = set()  # type: ignore[attr-defined]
    assert protocol._recompute_segment_priority("segY") == {}  # type: ignore[attr-defined]
