"""JSON schema for configuration structure validation."""

from __future__ import annotations

CONFIG_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RTOS Simulation Config",
    "type": "object",
    "required": ["version", "platform", "tasks", "scheduler", "sim"],
    "properties": {
        "version": {"type": "string"},
        "platform": {
            "type": "object",
            "required": ["processor_types", "cores"],
            "properties": {
                "processor_types": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/ProcessorType"},
                },
                "cores": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/Core"},
                },
            },
            "additionalProperties": False,
        },
        "resources": {
            "type": "array",
            "items": {"$ref": "#/$defs/Resource"},
            "default": [],
        },
        "tasks": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/TaskGraph"},
        },
        "scheduler": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "params": {
                    "type": "object",
                    "default": {},
                    "properties": {
                        "tie_breaker": {"type": "string"},
                        "allow_preempt": {"type": "boolean"},
                        "event_id_mode": {
                            "type": "string",
                            "enum": ["deterministic", "random", "seeded_random"],
                        },
                        "etm": {"type": "string"},
                        "etm_params": {"type": "object"},
                        "resource_acquire_policy": {
                            "type": "string",
                            "enum": ["legacy_sequential", "atomic_rollback"],
                        },
                        "static_window_mode": {
                            "type": ["boolean", "number", "string"],
                        },
                        "static_windows": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/StaticWindowConstraint"},
                            "default": [],
                        },
                    },
                },
            },
            "additionalProperties": False,
        },
        "sim": {
            "type": "object",
            "required": ["duration", "seed"],
            "properties": {
                "duration": {"type": "number", "exclusiveMinimum": 0},
                "seed": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "planning": {"$ref": "#/$defs/Planning"},
    },
    "$defs": {
        "ProcessorType": {
            "type": "object",
            "required": ["id", "name", "core_count", "speed_factor"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "core_count": {"type": "integer", "minimum": 1},
                "speed_factor": {"type": "number", "exclusiveMinimum": 0},
            },
            "additionalProperties": False,
        },
        "Core": {
            "type": "object",
            "required": ["id", "type_id", "speed_factor"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "type_id": {"type": "string", "minLength": 1},
                "speed_factor": {"type": "number", "exclusiveMinimum": 0},
            },
            "additionalProperties": False,
        },
        "Resource": {
            "type": "object",
            "required": ["id", "name", "bound_core_id", "protocol"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "bound_core_id": {"type": "string", "minLength": 1},
                "protocol": {"type": "string", "enum": ["mutex", "pip", "pcp"]},
            },
            "additionalProperties": False,
        },
        "TaskGraph": {
            "type": "object",
            "required": ["id", "name", "task_type", "subtasks"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "task_type": {
                    "type": "string",
                    "enum": ["time_deterministic", "dynamic_rt", "non_rt"],
                },
                "period": {"type": "number", "exclusiveMinimum": 0},
                "deadline": {"type": "number", "exclusiveMinimum": 0},
                "arrival": {"type": "number", "minimum": 0},
                "phase_offset": {"type": "number", "minimum": 0},
                "min_inter_arrival": {"type": "number", "exclusiveMinimum": 0},
                "max_inter_arrival": {"type": "number", "exclusiveMinimum": 0},
                "arrival_model": {
                    "type": "string",
                    "enum": ["fixed_interval", "uniform_interval"],
                },
                "arrival_process": {"$ref": "#/$defs/ArrivalProcess"},
                "task_mapping_hint": {"type": ["string", "null"]},
                "abort_on_miss": {"type": "boolean", "default": False},
                "subtasks": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/Subtask"},
                },
            },
            "additionalProperties": False,
        },
        "Subtask": {
            "type": "object",
            "required": ["id", "segments"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "predecessors": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                },
                "successors": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                },
                "subtask_mapping_hint": {"type": ["string", "null"]},
                "segments": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/Segment"},
                },
            },
            "additionalProperties": False,
        },
        "Segment": {
            "type": "object",
            "required": ["id", "index", "wcet"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "index": {"type": "integer", "minimum": 1},
                "wcet": {"type": "number", "exclusiveMinimum": 0},
                "acet": {"type": "number", "exclusiveMinimum": 0},
                "required_resources": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                },
                "mapping_hint": {"type": ["string", "null"]},
                "preemptible": {"type": "boolean", "default": True},
                "release_offsets": {
                    "type": ["array", "null"],
                    "items": {"type": "number", "minimum": 0},
                },
            },
            "additionalProperties": False,
        },
        "ArrivalProcess": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["fixed", "uniform", "poisson", "one_shot", "custom"],
                },
                "params": {
                    "type": "object",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "number"},
                            {"type": "string"},
                            {"type": "boolean"},
                        ]
                    },
                    "default": {},
                },
                "max_releases": {"type": ["integer", "null"], "minimum": 1},
            },
            "allOf": [
                {
                    "if": {"properties": {"type": {"const": "custom"}}},
                    "then": {
                        "properties": {
                            "params": {
                                "required": ["generator"],
                                "properties": {
                                    "generator": {
                                        "type": "string",
                                        "minLength": 1,
                                    }
                                },
                            }
                        }
                    },
                }
            ],
            "additionalProperties": False,
        },
        "StaticWindowConstraint": {
            "type": "object",
            "required": ["core_id"],
            "properties": {
                "core_id": {"type": "string", "minLength": 1},
                "segment_key": {"type": "string", "minLength": 1},
                "task_id": {"type": "string", "minLength": 1},
                "subtask_id": {"type": "string", "minLength": 1},
                "segment_id": {"type": "string", "minLength": 1},
                "start": {"type": "number"},
                "end": {"type": "number"},
                "start_time": {"type": "number"},
                "end_time": {"type": "number"},
            },
            "allOf": [
                {
                    "anyOf": [
                        {"required": ["segment_key"]},
                        {"required": ["task_id"]},
                    ]
                },
                {
                    "anyOf": [
                        {"required": ["start", "end"]},
                        {"required": ["start", "end_time"]},
                        {"required": ["start_time", "end"]},
                        {"required": ["start_time", "end_time"]},
                    ]
                },
                {
                    "if": {"required": ["subtask_id"]},
                    "then": {"required": ["task_id", "segment_id"]},
                },
                {
                    "if": {"required": ["segment_id"]},
                    "then": {"required": ["task_id", "subtask_id"]},
                },
            ],
            "additionalProperties": False,
        },
        "Planning": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": False},
                "planner": {"type": "string", "default": "np_edf"},
                "lp_objective": {"type": "string", "default": "response_time"},
                "task_scope": {
                    "type": "string",
                    "enum": ["sync_only", "sync_and_dynamic_rt", "all"],
                    "default": "sync_only",
                },
                "include_non_rt": {"type": "boolean", "default": False},
                "horizon": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "params": {"type": "object", "default": {}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
