# embegent

面向 STM32 真机调试场景的 agent-friendly harness 原型。

它不是一个“把 OpenOCD、GDB、CMake 拼在一起”的脚本集合，而是在嵌入式 MCU 调试场景里，把工程、工具、状态、证据、上下文和输出协议整理成一套适合 Agent 长时间稳定工作的执行环境。

这份 README 的核心视角，不再是“有哪些命令”，而是：

- 为什么 `embegent` 本质上是一个 embedded harness。
- 为什么 token、memory、上下文分层是必要的外围 infra。
- 为什么 CLI 只是一个 renderer，而不是系统内部的真相格式。
- 为什么后续接 MCP / JSON-RPC 时，不应该再从终端文本反解析。

---

## Harness Engineering 视角

`embegent` 的设计核心，直接受到 OpenAI 官方文章
[Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
的启发。

这篇文章的核心观点，不是“让 Agent 多写代码”，而是：

- 真正的瓶颈通常不是模型不会做事，而是环境没有被设计成适合 Agent 工作。
- context 是稀缺资源，应该给 Agent 一张地图，而不是一份巨大的说明书。
- repository-local、结构化、可验证的知识，才是 agent runtime 的 system of record。
- 输出文本不是事实本身，结构化状态、约束和证据才是。
- 代码之外的 scaffolding、feedback loop、observability、memory 分层，才是 agent 系统能长期工作的关键。

`embegent` 可以理解为把这套 harness engineering 思想，映射到 STM32 真机调试场景中的一次工程化实践。

---

## 项目定位

`embegent` 关注的是一件事：

把一个真实 STM32 工程，变成 Agent 可操作、可观察、可验证、可复盘的本地执行环境。

它不重做固件工程，不重做 GDB Server，也不替代 IDE。它做的是：

- 复用已有 STM32 工程和构建链。
- 复用 OpenOCD、ST-LINK、arm-none-eabi-gdb、CMSIS-SVD 等现有基础设施。
- 把 `build / flash / debug / monitor / svd` 收口为稳定用例。
- 把运行时上下文压缩成 Agent 可以按层读取的 state / evidence。
- 把输出从“终端文本”升级为“结构化结果 + 渲染层”。

换句话说，`embegent` 不是一个 IDE 替代品，而是一个面向嵌入式 Agent 的执行 harness。

---

## 当前状态

当前仓库已经完成第一轮从原型脚本向 agent-friendly 分层架构的重构：

- `interfaces` 负责 CLI 参数接入与结果渲染。
- `application` 负责用例编排，并尽量返回结构化结果。
- `infrastructure` 负责和 OpenOCD、ST-LINK、GDB、SVD、进程、状态文件打交道。
- `agent` 负责把状态文件压缩成 Agent 友好的上下文。
- `contracts.py` 提供跨层共享的数据契约。

当前已经落地的关键结果：

- `doctor`、`svd fetch`、`build`、`flash`、`debug start/stop/continue/snapshot/peripheral-read` 都已经改成 application 返回结构化结果，由 interfaces 统一渲染。
- `monitor` 已切成“事件流 + 会话摘要”模式，实时输出由 interfaces 决定如何展示，application 不再直接 `typer.echo`。
- `.stm32-agent/` 目录中的状态文件已经作为 Agent 的本地 memory 基础层。
- README 已按真实结构、真实现状和真实约束重写，不再描述旧兼容层。

这意味着当前项目已经不是“命令能跑”的状态，而是“内部事实格式和展示格式已经分离”的状态。

---

## 目录结构

当前真实目录如下：

```text
embegent/
  assets/
  configs/
    examples/
      project.example.yaml
      smoke.example.yaml
      stlink.example.yaml
      stm32h750vbt6.openocd.yaml
  doc/
  src/stm32_agent/
    agent/
      context.py
    application/
      build.py
      doctor.py
      flash.py
      monitor.py
      projects.py
      svd.py
      verification.py
      debug/
        control.py
        session.py
        snapshot.py
    infrastructure/
      config.py
      process.py
      project.py
      svd.py
      tooling.py
      debug/
        gdb.py
      state/
        lock.py
        paths.py
        runtime.py
    interfaces/
      cli.py
      render.py
    contracts.py
  tests/
  workspaces/
    stm32h750vbt6/
```

---

## 分层职责

### 1. `interfaces`

对外适配层，当前主要是 CLI。

- `cli.py` 负责参数解析、路由和退出码。
- `render.py` 负责把 application 返回的结构化结果渲染成终端输出。

这一层不是业务事实层，而是展示和协议适配层。

### 2. `application`

用例层，负责组织一次操作应该怎么完成。

- `doctor.py`、`svd.py`、`build.py`、`flash.py` 返回结构化结果。
- `monitor.py` 负责产生监视事件流与结束摘要。
- `debug/session.py` 管理调试会话启动与停止。
- `debug/control.py` 管理继续执行、单步、寄存器和回溯采样。
- `debug/snapshot.py` 负责聚合 Agent 友好的调试快照。

这一层的目标是“编排”，不是“直接输出终端文本”。

### 3. `infrastructure`

基础设施层，负责和具体工具与文件系统交互。

- `config.py` / `tooling.py` / `process.py` 处理配置、可执行文件发现和命令执行。
- `debug/gdb.py` 处理 GDB 会话与寄存器、回溯、内存读取。
- `svd.py` 处理 CMSIS-SVD 下载、解析与寄存器字段摘要。
- `state/` 负责 `.stm32-agent/` 目录下的状态文件与锁管理。

### 4. `agent`

Agent 上下文投影层。

- `agent/context.py` 从状态文件构造低噪声、可压缩、可复核的运行时上下文。
- `contracts.py` 保持上下文结构与用例输出结构稳定。

---

## 为什么外围 Infra 很重要

在传统人类主导的调试流程里，人可以直接看：

- IDE 当前停在哪里
- GDB 输出的大段文本
- 串口一行一行滚出来的日志
- 口头约定、文档、聊天记录里的背景信息

但对 Agent 来说，如果这些信息没有被放进一个可访问、可验证、可按需展开的本地系统里，那么它们就几乎等于不存在。

所以外围 infra 在这里不是附属品，而是核心能力：

- 工程配置必须可发现。
- 调试状态必须可读。
- 证据必须可追溯。
- 输出必须可序列化。
- memory 必须分层。
- token 开销必须被主动管理。

这正是 harness engineering 在嵌入式场景里的价值。

---

## `.stm32-agent` 作为本地 Memory

每个 workspace 下会生成 `.stm32-agent/`，其中最关键的是四类文件：

- `project_profile.json`
  低频静态画像。记录 workspace、elf、backend、svd、本地配置等背景信息。
- `session_state.json`
  当前调试会话的最小导航信息。包括 session 状态、后端、锁状态、最近动作、关键寄存器摘要。
- `observation.json`
  最近几次调试观察结果的滑动窗口，例如 snapshot、registers、backtrace、peripheral-read、monitor。
- `verification_report.json`
  用于回放“做了什么、为什么认为成功、证据是什么”的验证记录。

这四类文件不是“多写几个 JSON”，而是在工作区里建立一套对 Agent 可见、可验证的 system of record。

---

## 推荐的 Token / Memory 分层

这是 `embegent` 下一阶段最重要的设计方向之一。

推荐把 Agent 在嵌入式调试中的 memory 分成 4 层：

### 1. Static Memory

低频、稳定、可长期复用。

典型来源：

- `project_profile.json`
- 板卡型号、芯片型号
- probe / backend 能力
- ELF 路径、SVD 路径
- 固定的调试约束和项目假设

适合做默认上下文，但必须保持紧凑。

### 2. Session Memory

当前会话的最小导航信息。

典型来源：

- `session_state.json`
- 当前 `status`
- `backend`
- `last_action`
- `sp/lr/pc/control`
- 当前 source location

这一层应该很小，因为它是每轮最可能被反复读取的热路径。

### 3. Working Memory

当前任务窗口内的观察结果。

典型来源：

- 最近 1 到 4 条 `observation`
- 最新一次 `ExecutionSnapshot`
- 当前外设摘要
- 最近一次 `build` / `flash` / `debug` 的摘要结果

这一层要能支撑单轮决策，但不能无限增长。

### 4. Evidence Store

大体积、低频、按需展开。

典型来源：

- `stdout` / `stderr`
- OpenOCD / GDB server 日志
- monitor 全量串口流
- 原始 backtrace、寄存器全文
- 完整构建日志

这一层不应默认进入 prompt，而应通过引用、路径、tail、filter 等方式按需读取。

### 建议的默认策略

对于后续 MCP / JSON-RPC 适配，更合理的默认策略是：

- 默认返回 `compact` 结果
- 仅在显式请求时返回 `verbose` / `evidence`
- 原始大文本优先落盘，再返回引用路径或摘要

这不是 OpenAI 官方给出的固定 schema，而是将 harness engineering 的原则映射到 STM32 调试场景后的推荐设计。

---

## 结构化返回结果

当前 CLI 看到的终端输出，并不是 application 直接打印的“事实本身”，而是 `interfaces/render.py` 对结构化结果做的渲染。

现在的主链路已经变成：

```text
CLI 参数
  -> application 用例
  -> contracts.py 中的数据模型
  -> interfaces/render.py
  -> 终端文本
```

### 已落地的一次性结果

`build`、`flash`、`doctor`、`svd fetch`、`debug start/stop/continue` 这类命令，现在都先返回结构化结果，再决定怎么显示。

目前已经落地的核心返回模型包括：

- `DoctorResult`
- `SvdFetchResult`
- `BuildResult`
- `FlashResult`
- `DebugCommandResult`
- `ExecutionSnapshot`
- `PeripheralReadResult`

其中 `BuildResult` / `FlashResult` 内部又复用了 `CommandRunResult`：

```json
{
  "command": ["cmake", "--build", "--preset", "Debug"],
  "cwd": "D:/.../workspaces/stm32h750vbt6",
  "stdout": "...",
  "stderr": "",
  "returncode": 0,
  "dry_run": false
}
```

`BuildResult` 大致会长这样：

```json
{
  "summary": "Build completed with CMake preset.",
  "build_dir": "D:/.../workspaces/stm32h750vbt6/build/Debug",
  "mode": "preset",
  "configured": true,
  "dry_run": false,
  "steps": [
    {
      "command": ["cmake", "--preset", "Debug"],
      "cwd": "D:/.../workspaces/stm32h750vbt6",
      "stdout": "...",
      "stderr": "",
      "returncode": 0,
      "dry_run": false
    },
    {
      "command": ["cmake", "--build", "--preset", "Debug"],
      "cwd": "D:/.../workspaces/stm32h750vbt6",
      "stdout": "...",
      "stderr": "",
      "returncode": 0,
      "dry_run": false
    }
  ]
}
```

`FlashResult` 大致会长这样：

```json
{
  "summary": "Flash completed with OpenOCD.",
  "backend": "openocd",
  "elf": "D:/.../build/Debug/stm32h750vbt6.elf",
  "dry_run": false,
  "command_result": {
    "command": ["openocd", "-f", "interface/stlink.cfg", "..."],
    "cwd": "D:/.../workspaces/stm32h750vbt6",
    "stdout": "...",
    "stderr": "",
    "returncode": 0,
    "dry_run": false
  }
}
```

### 已落地的流式结果

`monitor` 不适合被压成一次性静态结果，所以它现在是“事件流 + 会话摘要”两段式模型：

- `MonitorEvent`
  表示一条实时事件，可能是启动状态，也可能是一行串口输出。
- `MonitorResult`
  表示监视结束后的总结，例如端口、波特率、行数、是否中断、日志文件路径。

`MonitorEvent` 大致会长这样：

```json
{
  "kind": "line",
  "text": "[12:01:03] boot ok",
  "port": "COM6",
  "baudrate": 115200,
  "timestamp": "12:01:03"
}
```

`MonitorResult` 大致会长这样：

```json
{
  "summary": "Monitor session completed on COM6.",
  "port": "COM6",
  "baudrate": 115200,
  "duration": 5.0,
  "raw": false,
  "interrupted": false,
  "line_count": 42,
  "log_file": "D:/.../.stm32-agent/logs/monitor.log"
}
```

---

## 为什么后续不用再反解析终端文本

如果系统内部的真实输出只有终端文本，那么后续接 MCP 或 JSON-RPC 时，只能：

1. 调 CLI
2. 拿到一大段文本
3. 再用正则或额外解析把它拆回结构化字段

这条链路的问题是：

- 文本格式一改，协议层就跟着坏。
- 很难做稳定 schema。
- 很难控制 token。
- 很难分清摘要和证据。

现在的方向是反过来：

1. application 先返回 dataclass 结果
2. CLI 只是其中一个 renderer
3. MCP / JSON-RPC 可以直接消费 dataclass 转出来的 `dict`

所以终端文本现在只是“展示形式”，不再是“系统内部的事实格式”。

---

## 如何对接 MCP / JSON-RPC

未来接 MCP 或 JSON-RPC 时，推荐复用现有 application，而不是重新包一层 CLI 子进程。

更直接的接法是：

```text
MCP tool / JSON-RPC method
  -> 调 application.run_xxx(...)
  -> 拿到 contracts.py 的 dataclass
  -> to_dict() / asdict()
  -> 作为协议返回值
```

可以按下面的方式理解：

- CLI 适配
  `BuildResult -> render_build_result() -> 终端输出`
- MCP tool 适配
  `BuildResult -> result.to_dict() -> structured tool output`
- JSON-RPC 适配
  `BuildResult -> {"jsonrpc":"2.0","result": result.to_dict(), "id": ...}`

对 `monitor` 这种流式场景，则可以进一步拆成：

- CLI
  `MonitorEvent -> render_monitor_event()`
  `MonitorResult -> render_monitor_result()`
- JSON-RPC
  `MonitorEvent -> progress notification / event message`
  `MonitorResult -> final result`
- MCP
  `MonitorEvent -> streaming chunk / event callback`
  `MonitorResult -> structured completion payload`

这就是“后续接 MCP/JSON-RPC 时不需要再从终端文本反解析”的具体含义：协议层直接复用 use case 返回的数据模型，而不是把 CLI 当黑盒。

---

## 已支持命令

```bash
stm32-agent doctor
stm32-agent build
stm32-agent flash
stm32-agent monitor
stm32-agent svd fetch --chip STM32H750VBT6
stm32-agent debug start
stm32-agent debug step
stm32-agent debug continue
stm32-agent debug registers
stm32-agent debug backtrace
stm32-agent debug snapshot
stm32-agent debug peripheral-read --peripheral RCC --register CR
stm32-agent debug stop
```

---

## 快速开始

### 1. 安装

```bash
python -m pip install -e .
```

### 2. 使用示例配置

仓库中自带 OpenOCD 示例配置：

`configs/examples/stm32h750vbt6.openocd.yaml`

### 3. 典型链路

```bash
stm32-agent doctor -c "configs/examples/stm32h750vbt6.openocd.yaml"
stm32-agent build -c "configs/examples/stm32h750vbt6.openocd.yaml"
stm32-agent flash -c "configs/examples/stm32h750vbt6.openocd.yaml"
stm32-agent debug start -c "configs/examples/stm32h750vbt6.openocd.yaml"
stm32-agent debug snapshot -c "configs/examples/stm32h750vbt6.openocd.yaml" --watch RCC:CR
stm32-agent debug stop -c "configs/examples/stm32h750vbt6.openocd.yaml"
```

---

## 已完成的真实验证

当前仓库内已经做过的真机回归包括：

- `doctor`
- `build`
- `flash` on OpenOCD
- `monitor --serial-port COM1 --baudrate 115200 --duration 0.5` 的短时事件流回归
- `debug start -> debug snapshot --watch RCC:CR -> debug stop` on OpenOCD
- `debug start --backend stlink -> debug snapshot --watch RCC:CR -> debug stop` on ST-LINK
- `debug peripheral-read --peripheral RCC --register CR`
- `debug continue`
- `svd fetch --chip STM32H750VBT6`

仓库内的真机样例工程位于：

- `workspaces/stm32h750vbt6`

---

## 当前缺口

以下内容还没有完成，README 也明确按“现状”而不是“理想态”描述：

- MCP / JSON-RPC / VS Code adapter 还未实现。
- 当前主要面向单板、单 session 调试。
- `monitor` 虽然已经事件流模型化，但仍然是前台阻塞式会话，不是后台任务。
- `build` / `flash` 当前虽然已结构化，但默认返回里仍可能包含较大的 `stdout/stderr`，后续仍建议增加 `compact / verbose` 分档。
- `ST-LINK` 烧录链路上历史上出现过 `verify mismatch`，仍需继续收口。

---

## 下一步更合理的方向

- 引入 `compact / verbose / evidence` 三档返回策略，主动管理 token 开销。
- 继续把长时任务改造成后台任务或事件流适配，而不是仅限 CLI 前台阻塞。
- 为 `interfaces` 之外增加 MCP / JSON-RPC adapter，而不是把协议细节写回 use case。
- 进一步收紧 snapshot 和 observation schema，降低 Agent token 开销。
- 为 build / flash / monitor 的结构化结果增加更细的 machine-readable 字段和回归测试。

---

## 设计原则

- 先让真机链路可执行，再做协议层暴露。
- 先让状态文件可复核，再做 Agent 自动决策。
- 先保持 `interfaces -> application -> infrastructure` 边界清晰，再扩展能力。
- 不要求 Agent 看见全部日志，只要求 Agent 看见足够正确的上下文。
- 不把 README 写成巨大的命令手册，而把它写成 Agent 和人类都能快速定位系统结构的地图。
