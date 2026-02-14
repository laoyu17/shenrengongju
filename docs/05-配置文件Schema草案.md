# 配置文件 Schema 草案（JSON/YAML）

## 1. Schema 设计目标
- 可读性强，支持版本演进
- 明确实体结构：平台/资源/任务图/调度策略/仿真参数
- 当前实现版本：`0.2`，兼容 `0.1 -> 0.2` 自动迁移

## 2. JSON Schema（草案，非完整）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RTOS Simulation Config",
  "type": "object",
  "required": ["version", "platform", "resources", "tasks", "scheduler", "sim"],
  "properties": {
    "version": { "type": "string" },
    "platform": {
      "type": "object",
      "required": ["processor_types", "cores"],
      "properties": {
        "processor_types": {
          "type": "array",
          "items": { "$ref": "#/definitions/ProcessorType" }
        },
        "cores": {
          "type": "array",
          "items": { "$ref": "#/definitions/Core" }
        }
      }
    },
    "resources": {
      "type": "array",
      "items": { "$ref": "#/definitions/Resource" }
    },
    "tasks": {
      "type": "array",
      "items": { "$ref": "#/definitions/TaskGraph" }
    },
    "scheduler": {
      "type": "object",
      "required": ["name", "params"],
      "properties": {
        "name": { "type": "string" },
        "params": { "type": "object" }
      }
    },
    "sim": {
      "type": "object",
      "required": ["duration", "seed"],
      "properties": {
        "duration": { "type": "number" },
        "seed": { "type": "integer" }
      }
    }
  },
  "definitions": {
    "ProcessorType": {
      "type": "object",
      "required": ["id", "name", "core_count", "speed_factor"],
      "properties": {
        "id": { "type": "string" },
        "name": { "type": "string" },
        "core_count": { "type": "integer", "minimum": 1 },
        "speed_factor": { "type": "number", "minimum": 0 }
      }
    },
    "Core": {
      "type": "object",
      "required": ["id", "type_id", "speed_factor"],
      "properties": {
        "id": { "type": "string" },
        "type_id": { "type": "string" },
        "speed_factor": { "type": "number", "minimum": 0 }
      }
    },
    "Resource": {
      "type": "object",
      "required": ["id", "name", "bound_core_id", "protocol"],
      "properties": {
        "id": { "type": "string" },
        "name": { "type": "string" },
        "bound_core_id": { "type": "string" },
        "protocol": { "type": "string" }
      }
    },
    "TaskGraph": {
      "type": "object",
      "required": ["id", "name", "task_type", "period", "deadline", "subtasks"],
      "properties": {
        "id": { "type": "string" },
        "name": { "type": "string" },
        "task_type": { "type": "string", "enum": ["time_deterministic", "dynamic_rt", "non_rt"] },
        "period": { "type": "number" },
        "deadline": { "type": "number" },
        "arrival": { "type": "number" },
        "abort_on_miss": { "type": "boolean" },
        "subtasks": {
          "type": "array",
          "items": { "$ref": "#/definitions/Subtask" }
        }
      }
    },
    "Subtask": {
      "type": "object",
      "required": ["id", "segments"],
      "properties": {
        "id": { "type": "string" },
        "predecessors": { "type": "array", "items": { "type": "string" } },
        "successors": { "type": "array", "items": { "type": "string" } },
        "segments": {
          "type": "array",
          "items": { "$ref": "#/definitions/Segment" }
        }
      }
    },
    "Segment": {
      "type": "object",
      "required": ["id", "index", "wcet"],
      "properties": {
        "id": { "type": "string" },
        "index": { "type": "integer", "minimum": 1 },
        "wcet": { "type": "number" },
        "acet": { "type": "number" },
        "required_resources": { "type": "array", "items": { "type": "string" } },
        "mapping_hint": { "type": ["string", "null"] }
      }
    }
  }
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
  name: fixed_priority
  params:
    policy: rm

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
- 实时任务必须提供 `deadline`，时间确定性任务必须提供 `period`
- 引用完整性：`required_resources`、`type_id`、`bound_core_id` 必须指向已定义实体
