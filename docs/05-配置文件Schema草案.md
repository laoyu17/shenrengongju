# 配置文件 Schema 草案（JSON/YAML）

## 1. Schema 设计目标
- 可读性强，支持版本演进
- 明确实体结构：平台/资源/任务图/调度策略/仿真参数
- 当前实现版本：`0.2`，兼容 `0.1 -> 0.2` 自动迁移
- 说明：本文件仅描述**运行配置（模型）Schema**；批量实验文件（如 `examples/batch_matrix.yaml`）使用独立 `version: "0.1"` 结构

## 2. JSON Schema（草案，非完整）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RTOS Simulation Config",
  "type": "object",
  "required": ["version", "platform", "tasks", "scheduler", "sim"],
  "properties": {
    "version": { "type": "string" },
    "platform": {
      "type": "object",
      "required": ["processor_types", "cores"],
      "properties": {
        "processor_types": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/ProcessorType" }
        },
        "cores": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/Core" }
        }
      },
      "additionalProperties": false
    },
    "resources": {
      "type": "array",
      "items": { "$ref": "#/$defs/Resource" },
      "default": []
    },
    "tasks": {
      "type": "array",
      "minItems": 1,
      "items": { "$ref": "#/$defs/TaskGraph" }
    },
    "scheduler": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": { "type": "string" },
        "params": {
          "type": "object",
          "default": {},
          "properties": {
            "tie_breaker": { "type": "string" },
            "allow_preempt": { "type": "boolean" },
            "event_id_mode": { "type": "string" },
            "event_id_validation": { "type": "string", "enum": ["warn", "strict"] },
            "resource_acquire_policy": {
              "type": "string",
              "enum": ["legacy_sequential", "atomic_rollback"]
            }
          }
        }
      },
      "additionalProperties": false
    },
    "sim": {
      "type": "object",
      "required": ["duration", "seed"],
      "properties": {
        "duration": { "type": "number", "exclusiveMinimum": 0 },
        "seed": { "type": "integer" }
      },
      "additionalProperties": false
    }
  },
  "$defs": {
    "ProcessorType": {
      "type": "object",
      "required": ["id", "name", "core_count", "speed_factor"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "name": { "type": "string", "minLength": 1 },
        "core_count": { "type": "integer", "minimum": 1 },
        "speed_factor": { "type": "number", "exclusiveMinimum": 0 }
      },
      "additionalProperties": false
    },
    "Core": {
      "type": "object",
      "required": ["id", "type_id", "speed_factor"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "type_id": { "type": "string", "minLength": 1 },
        "speed_factor": { "type": "number", "exclusiveMinimum": 0 }
      },
      "additionalProperties": false
    },
    "Resource": {
      "type": "object",
      "required": ["id", "name", "bound_core_id", "protocol"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "name": { "type": "string", "minLength": 1 },
        "bound_core_id": { "type": "string", "minLength": 1 },
        "protocol": { "type": "string", "enum": ["mutex", "pip", "pcp"] }
      },
      "additionalProperties": false
    },
    "TaskGraph": {
      "type": "object",
      "required": ["id", "name", "task_type", "subtasks"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "name": { "type": "string", "minLength": 1 },
        "task_type": { "type": "string", "enum": ["time_deterministic", "dynamic_rt", "non_rt"] },
        "period": { "type": "number", "exclusiveMinimum": 0 },
        "deadline": { "type": "number", "exclusiveMinimum": 0 },
        "arrival": { "type": "number", "minimum": 0 },
        "phase_offset": { "type": "number", "minimum": 0 },
        "min_inter_arrival": { "type": "number", "exclusiveMinimum": 0 },
        "max_inter_arrival": { "type": "number", "exclusiveMinimum": 0 },
        "abort_on_miss": { "type": "boolean", "default": false },
        "subtasks": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/Subtask" }
        }
      },
      "additionalProperties": false
    },
    "Subtask": {
      "type": "object",
      "required": ["id", "segments"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "predecessors": {
          "type": "array",
          "items": { "type": "string", "minLength": 1 },
          "default": []
        },
        "successors": {
          "type": "array",
          "items": { "type": "string", "minLength": 1 },
          "default": []
        },
        "segments": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/Segment" }
        }
      },
      "additionalProperties": false
    },
    "Segment": {
      "type": "object",
      "required": ["id", "index", "wcet"],
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "index": { "type": "integer", "minimum": 1 },
        "wcet": { "type": "number", "exclusiveMinimum": 0 },
        "acet": { "type": "number", "exclusiveMinimum": 0 },
        "required_resources": {
          "type": "array",
          "items": { "type": "string", "minLength": 1 },
          "default": []
        },
        "mapping_hint": { "type": ["string", "null"] },
        "preemptible": { "type": "boolean", "default": true },
        "release_offsets": {
          "type": ["array", "null"],
          "items": { "type": "number", "minimum": 0 }
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

## 3. YAML 示例（草案）

```yaml
version: "0.2"
platform:
  processor_types:
    - id: CPU
      name: cpu-cluster
      core_count: 2
      speed_factor: 1.0
    - id: GPU
      name: gpu-cluster
      core_count: 1
      speed_factor: 5.0
  cores:
    - id: c0
      type_id: CPU
      speed_factor: 1.0
    - id: c1
      type_id: CPU
      speed_factor: 1.0
    - id: g0
      type_id: GPU
      speed_factor: 5.0
resources:
  - id: r0
    name: bus
    bound_core_id: c0
    protocol: mutex

tasks:
  - id: t0
    name: control
    task_type: dynamic_rt
    period: 20
    deadline: 20
    arrival: 0
    abort_on_miss: true
    subtasks:
      - id: s0
        predecessors: []
        successors: [s1]
        segments:
          - id: seg0
            index: 1
            wcet: 2.0
            required_resources: [r0]
      - id: s1
        predecessors: [s0]
        successors: []
        segments:
          - id: seg1
            index: 1
            wcet: 3.0
            mapping_hint: g0

scheduler:
  name: edf
  params:
    tie_breaker: fifo
    allow_preempt: true
    event_id_mode: deterministic
    event_id_validation: warn
    resource_acquire_policy: legacy_sequential

sim:
  duration: 100
  seed: 42
```

## 4. 约束与校验规则（摘要）
- DAG 无环；所有子任务 ID 唯一
- 资源绑定核必须存在
- 分段 index 从 1 递增
- mapping_hint 必须是存在的 core_id
- `processor_types.speed_factor` 与 `cores.speed_factor` 必须 `> 0`
- `resources` 非必填，默认 `[]`
- `scheduler.params` 非必填，默认 `{}`
- `scheduler.params.event_id_validation`：`warn | strict`（默认 `warn`）
- `scheduler.params.resource_acquire_policy`：`legacy_sequential | atomic_rollback`（默认 `legacy_sequential`）
- `TaskGraph.period/deadline` 非 schema 必填；语义层约束为：
  - `time_deterministic` 必须提供 `period`
  - 非 `non_rt` 任务必须提供 `deadline`
- `TaskGraph.max_inter_arrival` 仅对 `dynamic_rt` 有效，且需满足：
  - `min_inter_arrival`（或 `period` 推导值）存在
  - `max_inter_arrival >= min_inter_arrival`
- `phase_offset` 仅对 `time_deterministic` 有效（缺省会补为 `0.0`）
- `Segment.release_offsets` 仅允许出现在 `time_deterministic` 任务中
- 引用完整性：`required_resources`、`type_id`、`bound_core_id` 必须指向已定义实体
