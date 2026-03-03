# 23-RTOS Sim 全栈 UML（Mermaid + PlantUML）

## 0. 代码映射表（绘图取证）

| 维度 | 参与者 | 角色说明 | 代码锚点 |
| --- | --- | --- | --- |
| 入口层 | CLI `cmd_run` | 加载配置、驱动 build/run、导出 events/metrics/audit | `rtos_sim/cli/main.py:199` |
| 入口层 | UI `RunController` + `SimulationWorker` | UI 触发运行、后台线程推进仿真并回传事件批次 | `rtos_sim/ui/controllers/run_controller.py:24`, `rtos_sim/ui/worker.py:16` |
| IO 层 | `ConfigLoader` | YAML/JSON -> `ModelSpec` 校验与迁移 | `rtos_sim/io/loader.py:30` |
| Core 层 | `SimEngine` | build 插件、run/step 循环、事件与运行态管理 | `rtos_sim/core/engine.py:86` |
| 调度/协议 | `IScheduler` / `IResourceProtocol` | 调度决策、资源请求/释放与阻塞唤醒 | `rtos_sim/schedulers/base.py:16`, `rtos_sim/protocols/base.py:31` |
| ETM/Overhead | `IExecutionTimeModel` / `IOverheadModel` | 执行时间估计与调度/迁移开销注入 | `rtos_sim/etm/base.py:8`, `rtos_sim/overheads/base.py:8` |
| 事件链路 | `EventBus` + `SimEvent` | 统一事件发布与序列化 envelope | `rtos_sim/events/bus.py:15`, `rtos_sim/events/types.py:28` |
| 指标/分析 | `CoreMetrics` + `build_audit_report` | 事件消费聚合指标 + 审计规则判定 | `rtos_sim/metrics/core.py:12`, `rtos_sim/analysis/audit.py:224` |

> PlantUML 对应源码：`docs/uml-src/23-fullstack-component.puml`、`docs/uml-src/23-sim-runtime-sequence.puml`、`docs/uml-src/23-core-runtime-class.puml`、`docs/uml-src/23-runtime-state-machine.puml`、`docs/uml-src/23-runtime-activity.puml`、`docs/uml-src/23-core-package.puml`、`docs/uml-src/23-cli-ui-deployment.puml`、`docs/uml-src/23-cli-ui-research-usecase.puml`、`docs/uml-src/23-runtime-timing.puml`

## 0.1 UML 资产治理约定
- `docs/uml-src/*.puml` 为 UML 权威源文件。
- `docs/uml-src/png` 与 `docs/uml-src/svg` 为可再生产物，用于展示与导出，不作为权威事实源。
- 当源码与导出图不一致时，以 `.puml` 为准重新生成图件。

## 1. L1 全栈架构关系图（Mermaid）

```mermaid
flowchart LR
    subgraph Entry["入口层"]
        CLI["CLI\nrtos-sim run\ncmd_run()"]
        UI["UI\nRunController / SimulationWorker"]
    end

    subgraph IO["配置与模型"]
        Loader["ConfigLoader"]
        Spec["ModelSpec"]
    end

    subgraph Core["仿真内核"]
        Engine["SimEngine"]
        SchFactory["create_scheduler()"]
        ProFactory["create_protocol()"]
        EtmFactory["create_etm()"]
        OhFactory["create_overhead_model()"]
        Scheduler["IScheduler impl"]
        Protocol["IResourceProtocol impl"]
        ETM["IExecutionTimeModel impl"]
        Overhead["IOverheadModel impl"]
    end

    subgraph Stream["事件与分析"]
        Bus["EventBus"]
        Metrics["CoreMetrics"]
        Relations["build_model_relations_report()"]
        Audit["build_audit_report()"]
    end

    subgraph Artifacts["导出产物"]
        EventsJsonl["artifacts/events.jsonl"]
        MetricsJson["artifacts/metrics.json"]
        AuditJson["artifacts/audit.json"]
        UIPanel["UI Gantt / Metrics 面板"]
    end

    CLI --> Loader
    UI --> Loader
    Loader --> Spec
    CLI --> Engine
    UI --> Engine
    Spec --> Engine

    Engine --> SchFactory --> Scheduler
    Engine --> ProFactory --> Protocol
    Engine --> EtmFactory --> ETM
    Engine --> OhFactory --> Overhead

    Engine --> Bus
    Engine -->|events / metric_report| CLI
    Bus --> Metrics
    Engine --> UIPanel

    Spec --> Relations
    CLI --> Audit
    Relations --> Audit

    CLI --> EventsJsonl
    CLI --> MetricsJson
    CLI --> AuditJson

    Audit --> AuditJson

    Truth["真相源：EventBus 事件流 + 导出产物链路"]:::truth
    Bus -.-> Truth
    Metrics -.-> Truth
    Audit -.-> Truth

    classDef truth fill:#f6f8fa,stroke:#64748b,color:#0f172a;
```

**代码锚点（L1）**
- `rtos_sim/cli/main.py:199`
- `rtos_sim/cli/main.py:239`
- `rtos_sim/cli/main.py:249`
- `rtos_sim/io/loader.py:30`
- `rtos_sim/core/engine.py:153`
- `rtos_sim/core/engine.py:161`
- `rtos_sim/events/bus.py:15`
- `rtos_sim/metrics/core.py:32`
- `rtos_sim/analysis/audit.py:224`
- `rtos_sim/ui/controllers/run_controller.py:24`
- `rtos_sim/ui/worker.py:16`

## 2. L2 仿真执行时序图（Mermaid）

```mermaid
sequenceDiagram
    autonumber
    participant CLI as CLI cmd_run
    participant Loader as ConfigLoader
    participant Engine as SimEngine
    participant Runtime as engine_runtime.advance_once
    participant Release as engine_release.process_releases
    participant Scheduler as IScheduler
    participant Protocol as IResourceProtocol
    participant Bus as EventBus
    participant Metrics as CoreMetrics
    participant Audit as build_audit_report

    CLI->>Loader: load(config)
    Loader-->>CLI: ModelSpec
    CLI->>Engine: build(spec)
    CLI->>Engine: run(until)

    loop while now < horizon
        Engine->>Runtime: _advance_once(horizon)
        Runtime->>Release: process_releases(now)
        Release->>Bus: JobReleased / SegmentReady
        Release->>Scheduler: on_release() / on_segment_ready()

        Runtime->>Scheduler: schedule(now, snapshot)
        Scheduler-->>Runtime: Decision[]
        Runtime->>Engine: _apply_dispatch(job, segment, core)
        Engine->>Protocol: request(segment, resource, core, priority)

        alt granted
            Protocol-->>Engine: granted=True
            Engine->>Bus: ResourceAcquire
            Engine->>Bus: SegmentStart
        else blocked(reason=resource_busy/system_ceiling_block)
            Protocol-->>Engine: granted=False
            alt resource_acquire_policy == atomic_rollback && partial-hold
                Engine->>Protocol: release(acquired resources)
                Engine->>Bus: ResourceRelease(reason=acquire_rollback)
            end
            Engine->>Bus: SegmentBlocked
        end

        Runtime->>Engine: _complete_finished_segments(now)
        Engine->>Bus: SegmentEnd
        Engine->>Protocol: release(resource)
        Protocol-->>Engine: wakeup candidates
        Engine->>Bus: ResourceRelease + SegmentUnblocked
        Engine->>Bus: JobComplete (all subtasks done)

        Runtime->>Runtime: _check_deadline_miss(now)
        alt now > absolute_deadline
            Runtime->>Bus: DeadlineMiss
            alt abort_on_miss = true
                Runtime->>Engine: _abort_job(job_id)
                Engine->>Bus: Preempt(reason=abort_on_miss)
                Engine->>Bus: ResourceRelease(reason=cancel_segment)
            end
        end

        Bus-->>Metrics: consume(event)
    end

    CLI->>Engine: events / metric_report()
    CLI->>Audit: build_audit_report(events, scheduler, relations)
    Audit-->>CLI: audit report
    CLI->>CLI: write events.jsonl / metrics.json / audit.json
```

**代码锚点（L2 时序）**
- `rtos_sim/cli/main.py:214`
- `rtos_sim/core/engine.py:193`
- `rtos_sim/core/engine_runtime.py:15`
- `rtos_sim/core/engine_release.py:16`
- `rtos_sim/core/engine_runtime.py:151`
- `rtos_sim/core/engine_dispatch.py:14`
- `rtos_sim/core/engine_dispatch.py:73`
- `rtos_sim/core/engine_dispatch.py:207`
- `rtos_sim/core/engine_dispatch.py:239`
- `rtos_sim/core/engine_runtime.py:202`
- `rtos_sim/core/engine_abort.py:15`
- `rtos_sim/events/types.py:12`

## 3. L2 核心接口/实现类图（Mermaid）

```mermaid
classDiagram
    class ISimEngine {
        <<interface>>
        +build(spec)
        +run(until)
        +step(delta)
        +pause()
        +resume()
        +stop()
        +reset()
    }
    class SimEngine
    SimEngine ..|> ISimEngine

    class IScheduler {
        <<interface>>
        +schedule(now, snapshot)
    }
    class PriorityScheduler
    class EDFScheduler
    class RMScheduler
    PriorityScheduler ..|> IScheduler
    EDFScheduler --|> PriorityScheduler
    RMScheduler --|> PriorityScheduler

    class IResourceProtocol {
        <<interface>>
        +configure(resources)
        +request(segment, resource, core, priority)
        +release(segment, resource)
    }
    class MutexResourceProtocol
    class PIPResourceProtocol
    class PCPResourceProtocol
    MutexResourceProtocol ..|> IResourceProtocol
    PIPResourceProtocol ..|> IResourceProtocol
    PCPResourceProtocol ..|> IResourceProtocol

    class IExecutionTimeModel {
        <<interface>>
        +estimate(...)
        +on_exec(...)
    }
    class ConstantExecutionTimeModel
    class TableBasedExecutionTimeModel
    ConstantExecutionTimeModel ..|> IExecutionTimeModel
    TableBasedExecutionTimeModel ..|> IExecutionTimeModel

    class IOverheadModel {
        <<interface>>
        +on_context_switch(...)
        +on_migration(...)
        +on_schedule(...)
    }
    class SimpleOverheadModel
    SimpleOverheadModel ..|> IOverheadModel

    class SchedulerRegistry {
        <<factory>>
        +create_scheduler(name, params)
    }
    class ProtocolRegistry {
        <<factory>>
        +create_protocol(name)
    }
    class ETMRegistry {
        <<factory>>
        +create_etm(name, params)
    }
    class OverheadRegistry {
        <<factory>>
        +create_overhead_model(name, params)
    }

    SchedulerRegistry ..> IScheduler
    ProtocolRegistry ..> IResourceProtocol
    ETMRegistry ..> IExecutionTimeModel
    OverheadRegistry ..> IOverheadModel

    SimEngine --> IScheduler
    SimEngine --> IResourceProtocol
    SimEngine --> IExecutionTimeModel
    SimEngine --> IOverheadModel
    SimEngine ..> SchedulerRegistry : build()
    SimEngine ..> ProtocolRegistry : build()
    SimEngine ..> ETMRegistry : build()
    SimEngine ..> OverheadRegistry : build()
```

**代码锚点（L2 类图）**
- `rtos_sim/core/interfaces.py:12`
- `rtos_sim/core/engine.py:86`
- `rtos_sim/schedulers/base.py:16`
- `rtos_sim/schedulers/base.py:36`
- `rtos_sim/schedulers/registry.py:28`
- `rtos_sim/protocols/base.py:31`
- `rtos_sim/protocols/registry.py:27`
- `rtos_sim/etm/base.py:8`
- `rtos_sim/etm/registry.py:26`
- `rtos_sim/overheads/base.py:8`
- `rtos_sim/overheads/registry.py:32`

## 4. L2 运行时状态机图（Mermaid）

```mermaid
stateDiagram-v2
    [*] --> SegmentReady

    state "Segment Lifecycle" as SegmentLifecycle {
        SegmentReady --> SegmentRunning: dispatch granted
        SegmentRunning --> SegmentBlocked: request not granted
        SegmentBlocked --> SegmentUnblocked: release/cancel wakes waiter
        SegmentUnblocked --> SegmentReady: requeue ready set
        SegmentRunning --> SegmentFinished: complete/truncate
    }

    state "Job Lifecycle" as JobLifecycle {
        [*] --> JobReleased
        JobReleased --> JobActive: first segment ready
        JobActive --> JobCompleted: all subtasks completed
        JobActive --> DeadlineMiss: now > absolute_deadline
        DeadlineMiss --> Aborted: abort_on_miss=true
        DeadlineMiss --> JobActive: abort_on_miss=false
    }
```

**代码锚点（状态机）**
- `rtos_sim/core/engine_dispatch.py:88`
- `rtos_sim/core/engine_dispatch.py:92`
- `rtos_sim/core/engine_dispatch.py:269`
- `rtos_sim/core/engine_dispatch.py:273`
- `rtos_sim/core/engine_runtime.py:212`
- `rtos_sim/core/engine_runtime.py:223`
- `rtos_sim/core/engine_abort.py:24`
- `rtos_sim/core/engine.py:736`
- `rtos_sim/model/runtime.py:66`

## 5. L2 运行活动图（Mermaid）

```mermaid
flowchart TD
    Start(["cmd_run start"]) --> Load["ConfigLoader.load"]
    Load --> Build["SimEngine.build"]
    Build --> Horizon["resolve horizon / stop_at"]
    Horizon --> StepMode{"args.step ?"}

    StepMode -- yes --> StepLoop{{"while engine.now < stop_at"}}
    StepLoop --> StepAdvance["engine.step(delta or once)"]
    StepAdvance --> StepProgress{"progressed ?"}
    StepProgress -- yes --> StepLoop
    StepProgress -- no --> RunCall

    StepMode -- no --> RunCall["engine.run(until=stop_at)"]

    RunCall --> AdvanceLoop{{"while env.now < horizon"}}
    AdvanceLoop --> AdvanceOnce["_advance_once(horizon)"]
    AdvanceOnce --> Advanced{"progressed ?"}
    Advanced -- yes --> AdvanceLoop
    Advanced -- no --> Collect

    Collect["collect events + metrics"] --> NeedAudit{"args.audit_out ?"}
    NeedAudit -- no --> Done(["return 0"])
    NeedAudit -- yes --> Audit["build_audit_report"]
    Audit --> AuditPass{"audit.status == pass ?"}
    AuditPass -- yes --> Done
    AuditPass -- no --> Fail(["return 2"])
```

**代码锚点（活动图）**
- `rtos_sim/cli/main.py:199`
- `rtos_sim/cli/main.py:214`
- `rtos_sim/cli/main.py:222`
- `rtos_sim/cli/main.py:224`
- `rtos_sim/cli/main.py:227`
- `rtos_sim/cli/main.py:232`
- `rtos_sim/core/engine.py:198`
- `rtos_sim/core/engine.py:201`
- `rtos_sim/core/engine_runtime.py:15`
- `rtos_sim/cli/main.py:248`
- `rtos_sim/cli/main.py:250`
- `rtos_sim/cli/main.py:256`

## 6. L2 包依赖图（Mermaid）

```mermaid
flowchart LR
    subgraph CLI[rtos_sim.cli]
        CLI_Main[main.py]
    end

    subgraph Core[rtos_sim.core]
        Core_Engine[engine.py]
        Core_Runtime[engine_runtime.py]
        Core_Dispatch[engine_dispatch.py]
        Core_Release[engine_release.py]
    end

    subgraph Events[rtos_sim.events]
        Events_Bus[bus.py]
        Events_Types[types.py]
    end

    subgraph Metrics[rtos_sim.metrics]
        Metrics_Core[core.py]
    end

    subgraph Schedulers[rtos_sim.schedulers]
        Sch_Base[base.py]
        Sch_Registry[registry.py]
    end

    subgraph Protocols[rtos_sim.protocols]
        Pro_Base[base.py]
        Pro_Registry[registry.py]
    end

    subgraph ETM[rtos_sim.etm]
        ETM_Base[base.py]
        ETM_Registry[registry.py]
    end

    subgraph Overheads[rtos_sim.overheads]
        Oh_Base[base.py]
        Oh_Registry[registry.py]
    end

    CLI_Main --> Core_Engine
    Core_Engine --> Events_Bus
    Core_Engine --> Metrics_Core
    Core_Engine --> Sch_Base
    Core_Engine --> Sch_Registry
    Core_Engine --> Pro_Base
    Core_Engine --> Pro_Registry
    Core_Engine --> ETM_Base
    Core_Engine --> ETM_Registry
    Core_Engine --> Oh_Base
    Core_Engine --> Oh_Registry

    Core_Dispatch --> Events_Types
    Core_Runtime --> Events_Types
    Core_Release --> Events_Types
```

**代码锚点（包图）**
- `rtos_sim/core/engine.py:15`
- `rtos_sim/core/engine.py:16`
- `rtos_sim/core/engine.py:17`
- `rtos_sim/core/engine.py:28`
- `rtos_sim/core/engine.py:29`
- `rtos_sim/core/engine.py:30`
- `rtos_sim/core/engine_dispatch.py:7`
- `rtos_sim/core/engine_runtime.py:8`
- `rtos_sim/core/engine_release.py:9`

## 7. L2 部署图（Mermaid）

```mermaid
flowchart LR
    UserCLI["CLI 用户"] --> CLIProc["CLI Process\nrtos-sim run"]

    subgraph Host["Host / Local Machine"]
        subgraph UIProc["UI Process (Main Thread)"]
            MainWindow["MainWindow"]
            RunCtrl["RunController"]
        end

        subgraph WorkerThread["SimulationWorker (QThread)"]
            Worker["SimulationWorker._execute"]
            WorkerEngine["SimEngine"]
        end

        ArtEvents["artifacts/events.jsonl"]
        ArtMetrics["artifacts/metrics.json"]
        ArtAudit["artifacts/audit.json"]
    end

    CLIProc --> WorkerEngine
    CLIProc --> ArtEvents
    CLIProc --> ArtMetrics
    CLIProc --> ArtAudit

    MainWindow --> RunCtrl
    RunCtrl --> Worker
    Worker --> WorkerEngine
    Worker -->|events_batch| MainWindow
    Worker -->|finished_report| MainWindow
    Worker -->|failed| MainWindow
```

**代码锚点（部署图）**
- `rtos_sim/cli/main.py:199`
- `rtos_sim/cli/main.py:242`
- `rtos_sim/cli/main.py:248`
- `rtos_sim/ui/app.py:154`
- `rtos_sim/ui/controllers/run_controller.py:24`
- `rtos_sim/ui/controllers/run_controller.py:63`
- `rtos_sim/ui/controllers/run_controller.py:64`
- `rtos_sim/ui/controllers/run_controller.py:65`
- `rtos_sim/ui/controllers/run_controller.py:66`
- `rtos_sim/ui/worker.py:16`
- `rtos_sim/ui/worker.py:58`
- `rtos_sim/ui/worker.py:92`
- `rtos_sim/ui/app.py:2025`

## 8. L2 用例图（Mermaid）

```mermaid
flowchart LR
    CLIUser["CLI 用户"]
    UIUser["UI 用户"]
    ResearchUser["研究审计用户"]

    UCValidate(("校验配置\nvalidate"))
    UCRun(("运行仿真并导出\nrun + events/metrics/audit"))
    UCBatch(("批量实验\nbatch-run"))
    UCCompare(("指标对比\ncompare"))
    UCInspect(("模型关系审查\ninspect-model"))
    UCMigrate(("迁移旧配置\nmigrate-config"))

    UIRun(("UI 启动/运行"))
    UIPause(("暂停/恢复/步进"))

    UCAuditSuite(("研究反例审计\nresearch_case_suite.py"))
    UCResearchReport(("研究报告生成\nresearch_report.py"))

    CLIUser --> UCValidate
    CLIUser --> UCRun
    CLIUser --> UCBatch
    CLIUser --> UCCompare
    CLIUser --> UCInspect
    CLIUser --> UCMigrate

    UIUser --> UIRun
    UIUser --> UIPause

    ResearchUser --> UCAuditSuite
    ResearchUser --> UCResearchReport

    UCRun --> UCResearchReport
    UCInspect --> UCResearchReport
```

**代码锚点（用例图）**
- `rtos_sim/cli/main.py:415`
- `rtos_sim/cli/main.py:424`
- `rtos_sim/cli/main.py:445`
- `rtos_sim/cli/main.py:457`
- `rtos_sim/cli/main.py:466`
- `rtos_sim/cli/main.py:477`
- `rtos_sim/ui/controllers/run_controller.py:44`
- `rtos_sim/ui/controllers/run_controller.py:77`
- `rtos_sim/ui/controllers/run_controller.py:84`
- `rtos_sim/ui/controllers/run_controller.py:91`
- `scripts/research_case_suite.py:142`
- `scripts/research_report.py:38`

## 9. L2 时间图（Mermaid Timeline）

```mermaid
timeline
    title RTOS Sim Runtime Timeline Skeleton
    section holder@0
        t=0.000 : JobReleased
        t=0.001 : ResourceAcquire(r0)
        t=0.001 : SegmentStart(seg0)
        t=0.450 : DeadlineMiss(abort_on_miss=true)
        t=0.450 : ResourceRelease(reason=cancel_segment)
    section waiter@0
        t=0.100 : JobReleased
        t=0.100 : SegmentBlocked(resource_busy)
        t=0.450 : SegmentUnblocked
        t=0.451 : SegmentStart(seg0)
        t=0.700 : SegmentEnd(seg0)
```

**代码锚点（时间图）**
- `rtos_sim/core/engine_release.py:86`
- `rtos_sim/core/engine_dispatch.py:132`
- `rtos_sim/core/engine_dispatch.py:188`
- `rtos_sim/core/engine_dispatch.py:92`
- `rtos_sim/core/engine_dispatch.py:273`
- `rtos_sim/core/engine_runtime.py:212`
- `rtos_sim/core/engine_abort.py:94`
- `rtos_sim/core/engine.py:630`

## 10. PlantUML 源码对应关系

- L1 组件图：`docs/uml-src/23-fullstack-component.puml`
- L2 运行时序：`docs/uml-src/23-sim-runtime-sequence.puml`
- L2 核心类图：`docs/uml-src/23-core-runtime-class.puml`
- L2 运行时状态机图：`docs/uml-src/23-runtime-state-machine.puml`
- L2 运行活动图：`docs/uml-src/23-runtime-activity.puml`
- L2 包依赖图：`docs/uml-src/23-core-package.puml`
- L2 部署图：`docs/uml-src/23-cli-ui-deployment.puml`
- L2 用例图：`docs/uml-src/23-cli-ui-research-usecase.puml`
- L2 时间图：`docs/uml-src/23-runtime-timing.puml`
