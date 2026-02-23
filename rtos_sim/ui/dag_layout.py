"""DAG layout helpers used by the UI layer."""

from __future__ import annotations


def compute_auto_layout_positions(
    subtask_ids: list[str],
    edges: list[tuple[str, str]],
    *,
    x_start: float = 80.0,
    y_start: float = 80.0,
    x_gap: float = 170.0,
    y_gap: float = 115.0,
) -> dict[str, tuple[float, float]]:
    """Compute a deterministic layered layout for a DAG-like graph."""
    if not subtask_ids:
        return {}

    children: dict[str, set[str]] = {sub_id: set() for sub_id in subtask_ids}
    indegree: dict[str, int] = {sub_id: 0 for sub_id in subtask_ids}
    for src_id, dst_id in edges:
        if src_id not in children or dst_id not in children:
            continue
        if dst_id in children[src_id]:
            continue
        children[src_id].add(dst_id)
        indegree[dst_id] += 1

    queue = sorted([sub_id for sub_id, degree in indegree.items() if degree == 0])
    level: dict[str, int] = {sub_id: 0 for sub_id in subtask_ids}
    visited: set[str] = set()
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for nxt in sorted(children.get(current, set())):
            level[nxt] = max(level[nxt], level[current] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] <= 0:
                queue.append(nxt)

    # Fallback for non-DAG or disconnected edge cases.
    if len(visited) < len(subtask_ids):
        for idx, sub_id in enumerate(sorted(subtask_ids)):
            level[sub_id] = max(level.get(sub_id, 0), idx // 4)

    level_groups: dict[int, list[str]] = {}
    for sub_id in subtask_ids:
        level_groups.setdefault(level.get(sub_id, 0), []).append(sub_id)
    for values in level_groups.values():
        values.sort()

    positions: dict[str, tuple[float, float]] = {}
    for col, layer in enumerate(sorted(level_groups)):
        for row, sub_id in enumerate(level_groups[layer]):
            positions[sub_id] = (x_start + col * x_gap, y_start + row * y_gap)
    return positions
