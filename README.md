# STM32 AI 调试链路

面向 STM32 嵌入式开发的 `CLI + MCP` 工具链原型。这个组件的目标不是替代 IDE，而是把已经能在 `VS Code + CMake + OpenOCD + ST-LINK + GDB` 里跑通的编译、烧录、调试、监视流程，收敛成可被 AI Agent 和人类共同使用的稳定接口。

## 产品目标

这个组件要解决的问题是：

- 让嵌入式调试能力从“人手点 IDE”变成“可脚本化、可回放、可审计”
- 让 Agent 不只会给建议，而是真的能执行 `build -> flash -> debug -> monitor`
- 让调试证据能被结构化保存，避免模型基于不完整或未经验证的信息胡乱推断
- 为后续 MCP 和 JSON-RPC 多客户端兼容打下可靠的 CLI 基础

一句话描述：

> 把 STM32 真机调试链路封装成 Agent 可调用、也适合人类验收的工程化组件。

## 当前真实能力

截至 2026-03-11，CLI 已具备这些命令：

- `doctor`
- `build`
- `flash`
- `monitor`
- `svd fetch`
- `debug start`
- `debug stop`
- `debug step`
- `debug continue`
- `debug registers`
- `debug peripheral-read`
- `debug backtrace`

### 已完成的真实验证

在真实工程 `D:/Musii-SnapShot/eediy/stm32h750vbt6` 上，以下链路已经跑通：

- `build`
- `flash --backend openocd`
- `flash --backend stlink`
- `debug start --backend openocd`
- `debug start --backend stlink`
- `debug registers`
- `debug backtrace`
- `debug step`
- `debug continue`
- `debug stop`
- `svd fetch --chip STM32H750VBT6`

真实现象包括：

- 能成功产出 ELF
- 能通过 `STM32_Programmer_CLI` 完成烧录，且 verify 在多数情况下通过
- 能启动 `ST-LINK_gdbserver`
- 能在 `Reset_Handler` 停住并读取寄存器
- 能单步把 PC 从启动汇编的上一行推进到下一行
- 能 `continue` 后重新接回，看到程序进入 `FreeRTOS prvIdleTask`
- 能自动下载 `STM32H750.svd` 并登记到工程画像里

这说明它现在已经不只是“概念原型”，而是可以驱动真实板卡做单步调试，并开始沉淀适合 Agent 使用的语义化上下文的 CLI MVP。

同时也要明确一个当前阻塞项：

- `flash --backend stlink` 存在间歇性 verify mismatch
- 已在真实板卡上复现过“同一 ELF、同一块板子，前一次通过、后一次失败、再下一次又通过”
- 至少一例失败发生在 `0x080018A4`，`STM32_Programmer_CLI` 报 `0x18 != 0x2C`
- 但随后用 OpenOCD 对同一地址读回，板上内容与 ELF 一致，说明当前更像“verify 读回/判定异常”，而不是“代码没烧进去”

因此当前主线不是继续堆功能，而是先把烧录可信度问题收口。

## 需求边界

### 当前范围内

- 面向 STM32 工程
- 复用现有 `CMakePresets.json`、`OpenOCD`、`ST-LINK_gdbserver`
- 支持 `OpenOCD` 和 `ST-LINK` 两种后端
- 支持单活动调试 session
- 支持构建、烧录、启动调试、单步、继续、寄存器读取、回溯、串口监视
- 支持把调试状态写入 `.stm32-agent/session.json`
- 支持自动拉取 CMSIS-SVD
- 支持基于本地 SVD 做外设寄存器字段解析

### 当前不承诺

- 不承诺替代 VS Code 图形调试体验
- 不承诺一开始支持多板卡并发调试
- 不承诺一开始支持 J-Link、PyOCD、Ozone
- 不承诺一开始支持完整断点管理、变量观察、表达式求值、RTOS 感知
- 不承诺一开始就把原始终端输出直接变成高质量 Agent 上下文

### 设计边界

- CLI 是第一层，MCP 只是暴露层
- 业务层负责 `build/flash/debug/monitor/svd`
- transport 层负责 JSON-RPC framing
- 人类验收结果和硬件真实证据，优先级高于模型推断

## 核心设计原则

- 优先复用现有工程配置，不重写整套嵌入式工具链
- 单 session 优先，先把状态管理做对
- 输出先做到“可读、可证据化”，再进一步“可结构化、可喂给模型”
- 日志、session、证据都要落盘，方便回放和人工审计
- 避免让 Agent 直接消费未经筛选的原始噪声输出

## 功能说明

### 构建与烧录

- `build` 支持普通 CMake 构建
- `build` 支持 `configure_preset / build_preset`
- `flash` 支持 `openocd` 后端
- `flash` 支持 `stlink` 后端
- `OpenOCD` 配置同时兼容工程内相对路径和 OpenOCD 脚本路径

### 调试会话

- `debug start` 启动 `OpenOCD GDB Server` 或 `ST-LINK_gdbserver`
- 当前 session 写入 `.stm32-agent/session.json`
- 当前工程画像写入 `.stm32-agent/project_profile.json`
- 当前会话摘要写入 `.stm32-agent/session_state.json`
- 最近观测窗口写入 `.stm32-agent/observation.json`
- 最近验证记录写入 `.stm32-agent/verification_report.json`
- `debug step` 基于当前 session 执行单步
- `debug continue` 以异步继续执行并断开控制端，保持目标继续运行
- `debug registers` 读取当前 halted 状态的核心寄存器
- `debug peripheral-read` 结合本地 SVD 读取外设寄存器并解析字段
- `debug backtrace` 读取当前堆栈回溯
- `debug stop` 回收后台调试服务进程

### SVD 获取

- `svd fetch` 可按芯片型号自动从 [modm-io/cmsis-svd-stm32](https://github.com/modm-io/cmsis-svd-stm32) 拉取 CMSIS-SVD
- 默认下载到 `.stm32-agent/svd/`
- 成功后会把 SVD 位置写入 `project_profile.json`
- 如果网络失败、家族不支持或仓库中没有匹配文件，会明确提示用户手动处理
- 后续寄存器语义化读取默认优先复用这里下载的本地 SVD

### 串口监视

- `monitor` 支持串口读取
- 支持限时运行
- 支持日志落盘
- 适合做人类观察，也适合后续做 Agent 的“最近运行态观测”

## 人类验收方式

这个组件后续不能只靠模型说“看起来成功”，必须保留适合人类确认的验收路径。

建议的人类验收分 3 层：

### 1. 命令层验收

直接运行：

```bash
stm32-agent build --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --configure-preset Debug --build-preset Debug
stm32-agent flash --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --elf "D:/Musii-SnapShot/eediy/stm32h750vbt6/build/Debug/stm32h750vbt6.elf" --backend stlink
stm32-agent debug start --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --elf "D:/Musii-SnapShot/eediy/stm32h750vbt6/build/Debug/stm32h750vbt6.elf" --backend stlink
stm32-agent debug registers --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6"
stm32-agent debug step --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6"
stm32-agent debug continue --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6"
stm32-agent debug backtrace --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6"
stm32-agent debug stop --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6"
stm32-agent svd fetch --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --chip STM32H750VBT6
stm32-agent debug peripheral-read --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --peripheral RCC --register CR
```

### 2. 行为层验收

建议为具体固件定义至少一个肉眼可判的行为证据：

- LED 闪烁
- 串口 banner
- 某 GPIO 拉高/拉低
- 某任务进入稳定循环

这样“continue 后程序真的跑起来了”就不只是 GDB 视角的判断。

### 3. 证据层验收

每次关键验证应至少保留：

- `.stm32-agent/session.json`
- `.stm32-agent/logs/...`
- 一段 stdout 摘要
- 如果有串口输出，再附一段 monitor 日志
- 如果有外设寄存器解析，再保留一份 `observation.json` 相关窗口

## Agent 接入边界

当前组件已经能让 Agent 间接执行单步调试，但不应该让 Agent 直接消费全部原始终端输出。

更合理的做法是分成两层：

### 动作类接口

- `stm32_build`
- `stm32_flash`
- `stm32_debug_start`
- `stm32_debug_step`
- `stm32_debug_continue`
- `stm32_debug_registers`
- `stm32_debug_peripheral_read`
- `stm32_debug_backtrace`
- `stm32_debug_stop`
- `stm32_monitor`
- `stm32_svd_fetch`

### 语义类接口

- `stm32_get_execution_snapshot`
- `stm32_get_runtime_summary`
- `stm32_verify_expectation`
- `stm32_collect_failure_bundle`

动作类负责执行，语义类负责整理上下文和证据。后者对 Agent 更重要。

## 推荐的 Agent 上下文组织

为了让 Agent 能闭环测试，又不被噪声淹没，推荐把上下文拆成 4 层。

### 1. 静态上下文

适合低频、不常变化的信息：

- 芯片型号
- 工程路径
- ELF 路径
- RTOS/裸机
- 关键任务名
- 关键外设映射
- 调试后端
- SVD 本地路径和来源 URL

建议输出文件：`project_profile.json`

当前实现状态：

- 已自动落盘
- 当前字段以工程路径、ELF、backend、probe、串口、preset、SVD 路径为主
- 后续再补芯片型号自动推断、关键任务、关键模块标签等高层语义

### 2. 会话上下文

描述当前调试会话：

- session id
- backend
- 当前 halted/running 状态
- 当前 pc/lr/sp
- 当前源码文件和行号
- 最近一次命令

建议输出文件：`session_state.json`

当前实现状态：

- 已自动落盘
- 当前记录 session id、backend、running/halted/stopped、最近动作、源码位置和紧凑寄存器摘要

### 3. 观测上下文

保留最近窗口，而不是全量日志：

- 最近一次核心寄存器摘要
- 最近一次 peripheral register 语义化摘要
- 最近一次 backtrace
- 最近 N 条串口日志
- 最近 N 次 step 前后 PC 变化
- 关键变量或内存快照

建议输出文件：`observation.json`

当前实现状态：

- 已自动落盘
- 当前记录最近窗口内的 `monitor`、`debug_step`、`debug_registers`、`debug_peripheral_read`、`debug_backtrace` 事件
- 每条事件都尽量只保留摘要和有限 raw excerpt，避免 context 爆炸

### 4. 验证上下文

真正给 Agent 和人类做结论判断的层：

- 测试目标
- 预期行为
- 实际行为
- 判定结果
- 证据路径
- 是否经过人类确认

建议输出文件：`verification_report.json`

当前实现状态：

- 已自动落盘
- 当前按命令维度记录 `build/flash/svd_fetch/debug_start/debug_step/debug_continue/debug_registers/debug_peripheral_read/debug_backtrace/debug_stop`
- 每条记录都带 `summary + verification_status + evidence/state`

## 信息可信度分级

为了避免给模型错误信息，后续所有对 Agent 暴露的结果建议都带上可信度标签：

- `unverified`
- `cli_verified`
- `hardware_verified`
- `human_verified`

原则：

- 仅 CLI 本地逻辑判断，不代表硬件真的正确
- 真板执行过，才算 `hardware_verified`
- 人类看过现象并认可，才算 `human_verified`

## 当前已知问题与经验

- Windows 终端编码会影响工具输出回显，已增加安全降级回显逻辑
- `ST-LINK_gdbserver` 与 `OpenOCD` 的 continue 语义不完全一样，已改为更兼容的实现
- 单步和继续的真实性必须用真板验证，不能只靠 mock
- 如果不给 Agent 做“证据摘要层”，模型很容易被原始 GDB 文本误导
- 如果没有 SVD，外设寄存器只能停留在地址和值层面，难以形成高质量语义上下文

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -U pip
.venv/Scripts/pip install -e .
stm32-agent --help
```

示例配置：

- `configs/examples/stm32h750vbt6.openocd.yaml`
- `configs/examples/stlink.example.yaml`

示例：

```bash
stm32-agent svd fetch --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --chip STM32H750VBT6
stm32-agent debug peripheral-read --workspace "D:/Musii-SnapShot/eediy/stm32h750vbt6" --peripheral RCC --register CR
```

## 后续推进 Spec

后续推进按“先把当前能力打磨成可信调试基座，再暴露给 Agent”来排，不建议跳步。

### Phase 1：收口 ST-LINK 烧录可信度

目标：

- 回答清楚 `flash --backend stlink` 的 verify mismatch 到底是什么性质
- 在“调试能连上”之外，补上“板上代码与 ELF 一致”的可信证据

要做的事：

- 固化 `stlink/openocd` 对照烧录实验
- 固化失败样本的地址、期望值、读回值和二次读回结果
- 比较 `stlink` 烧录后与 `openocd` 烧录后同一地址附近的读回差异
- 检查 ELF / section / program header / 对齐 / padding，确认异常地址是否属于特殊区域
- 让失败的烧录验证也能落盘，不要只记录成功 case

### Phase 2：压缩成 Agent 友好的调试快照

目标：

- 不再要求 Agent 每轮分别读取寄存器、回溯、外设、observation 和 verification 文件

要做的事：

- 增加 `debug snapshot`
- 一次产出当前函数/文件/行号、`pc/lr/sp/control`、顶部 backtrace、关键外设摘要、最近 observation、当前 verification status
- 继续固化 `project_profile.json`、`session_state.json`、`observation.json`、`verification_report.json`
- 增加按需裁剪和窗口大小控制，避免把原始噪声直接喂给模型

### Phase 3：MCP 粗粒度暴露

目标：

- 在 flash 可信度和 snapshot 都稳定后，再把 CLI 暴露成 Agent 工具

要做的事：

- 优先只暴露粗粒度 tools
- 建议先暴露：`stm32_build`、`stm32_flash`、`stm32_debug_start`、`stm32_debug_snapshot`、`stm32_debug_step`、`stm32_debug_continue`、`stm32_debug_stop`
- 每个 tool 返回统一 schema
- 返回结果附带 `verification_status`
- 错误信息要适合模型消费，不要只抛原始日志

### Phase 4：JSON-RPC 与多客户端兼容

目标：

- 在核心链路可信后，再提升跨客户端兼容性和复现效率

要做的事：

- 支持 `Content-Length` framing
- 支持换行分隔 JSON framing
- transport 与 tool handler 解耦
- 补充隔离环境、日志轮转、workspace 级资源治理

## 当前推荐优先级

如果继续推进，建议下一步优先做：

1. 收口 `flash --backend stlink` 的 verify mismatch，并把失败证据结构化落盘
2. 做 `debug snapshot`，把多文件上下文压缩成单次可消费输出
3. 再暴露 MCP 粗粒度 tools

## 参考定位

这个组件未来对外更准确的描述应该是：

> 一个面向 STM32 真机调试的 Agent-ready CLI 组件，能够执行单步调试，并把嵌入式运行时信息整理成适合 Agent 和人类共同验收的证据化上下文。
