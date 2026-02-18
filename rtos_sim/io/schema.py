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
                        "event_id_mode": {"type": "string"},
                        "event_id_validation": {"type": "string", "enum": ["warn", "strict"]},
                        "resource_acquire_policy": {
                            "type": "string",
                            "enum": ["legacy_sequential", "atomic_rollback"],
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
    },
    "additionalProperties": False,
}
