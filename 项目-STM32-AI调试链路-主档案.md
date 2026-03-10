---
项目名称: STM32 AI 调试链路
开始时间: 2026-03
结束时间: 进行中
担任角色: 独立开发者
技术栈: [Python, MCP, JSON-RPC, OpenOCD, GDB, CMake, STM32, VS Code]
优先级: 旗舰候选
标签: [嵌入式, 调试工具链, AI工作流, STM32, Agent]
---

# 项目档案：STM32 AI 调试链路

## 1. 信息概况

### 1.1 项目背景

- **项目目标：** 在现有 `VS Code + CMake + OpenOCD` 开发环境基础上，快速实现一套可被 AI Agent 调用的 STM32 自动化链路，将 `build → flash → debug → monitor` 串成统一 CLI 与 MCP 接口。
- **核心痛点：** 现有嵌入式开发流虽然已经能在 VS Code 内完成编译、下载和调试，但仍然偏向“人手点击 IDE”；一旦希望让 AI 参与自动化排错、回归验证或辅助调试，就缺少稳定、可脚本化、可复用的工具接口。
- **切入方式：** 不重新发明编译与调试体系，而是复用已有的 `CMake Tools`、`OpenOCD`、`arm-none-eabi-gdb` 和 `launch.json` 配置，把它们收束为命令行能力，再向上封装为 MCP Server。
- **预期成果：** 形成一个可在 Windows + VS Code 环境下快速落地的嵌入式 AI Tool-use 原型，支持断点、单步、寄存器读取、堆栈回溯、串口监视，以及针对不同客户端的 JSON-RPC 双帧适配。

### 1.2 为什么现在做

- **已有基础成熟：** 当前已经具备 `OpenOCD` 环境、`CMake` 插件、以及兼容 `ST-Link / DAPLink` 的 VS Code 调试配置，技术前置条件基本具备。
- **复用价值高：** 该链路不仅能服务于当前 RM/STM32 项目，还能迁移到后续电赛、手套、控制器等一系列 MCU 项目中。
- **对简历与能力表达有帮助：** 这是一个兼具工程落地、工具链理解、调试深度和 AI 接口设计的项目，适合作为“我如何把 AI 真的接入嵌入式开发流”的真实案例。

### 1.3 项目边界

- **本项目先做：**
  - 面向 STM32 + OpenOCD + GDB 的最小闭环。
  - 面向本地单机的 CLI 与 MCP Server。
  - 面向 `ST-Link / DAPLink` 的探针配置切换。
  - 面向串口日志、断点调试、寄存器与回溯的常用能力。
- **本项目暂不做：**
  - 不追求替代 VS Code 图形调试体验。
  - 不一开始兼容 J-Link、PyOCD、Ozone 等多套调试后端。
  - 不先做复杂 GUI，而是先做可验证的终端工具链。
  - 不一开始追求多板卡并发调试。

---

## 2. MVP 目标定义

### 2.1 最小可行版本

第一阶段只要求打通以下能力：

- `build`：调用当前工程的 CMake 构建流程，产出 ELF。
- `flash`：复用 OpenOCD 配置完成下载与复位。
- `debug-start`：启动 OpenOCD + GDB 会话，连接目标。
- `monitor`：读取串口输出，用于辅助判断运行状态。
- `breakpoint-set / step / continue`：完成最基础的调试控制。
- `register-read / backtrace`：支持读取寄存器与堆栈回溯。

### 2.2 成功标准

- 可以对一个现有 STM32 工程，在命令行中稳定执行 `build → flash → debug → monitor`。
- 可以在不打开 VS Code 调试面板的情况下，完成至少 1 次断点命中与单步执行。
- 可以通过 MCP 调用上述能力，让 Agent 以工具调用而非文本建议的方式参与调试。
- 可以在至少 2 类客户端接入方式下正常收发 JSON-RPC 消息。

---

## 3. 技术方案概览

### 3.1 总体架构

采用“三层结构”推进，尽量降低耦合：

1. **底层执行层**：直接调用 `cmake`、`openocd`、`arm-none-eabi-gdb`、串口监视模块。
2. **CLI 编排层**：把构建、烧录、调试、日志监视封装成稳定子命令，统一输入输出格式。
3. **MCP 接口层**：把 CLI 能力暴露为 MCP Tools，供 AI Agent 直接调用。

### 3.2 关键设计原则

- **复用优先：** 先吃透 VS Code 已经验证过的配置，不绕过现有生态重写一套构建/调试系统。
- **单会话优先：** MVP 阶段默认同一时刻只维护一个活跃调试会话，降低状态同步难度。
- **文本协议先行：** CLI 输出统一做结构化文本/JSON，方便人看也方便 Agent 消费。
- **兼容层外置：** JSON-RPC 双帧适配做成独立传输层，不污染核心业务逻辑。

### 3.3 推荐技术选型

- **主语言：** Python
- **原因：**
  - 适合快速封装 CLI、串口和进程管理。
  - 便于实现 MCP Server 与 JSON-RPC 协议适配。
  - 易于在 Windows 环境下创建隔离虚拟环境并复现。
- **核心依赖建议：**
  - `typer` 或 `argparse`：CLI
  - `pyserial`：串口监视
  - `subprocess`：调起 `cmake/openocd/gdb`
  - `pydantic`：结构化参数与返回值
  - MCP Python SDK 或基于 JSON-RPC 直接封装

---

## 4. 分阶段推进计划

### 4.1 Phase 0：环境与接口梳理

- 整理当前 VS Code 可用工程的 `CMakeLists.txt`、`launch.json`、OpenOCD 配置。
- 抽取出 `ST-Link` 和 `DAPLink` 共性参数。
- 明确从 VS Code 迁移到 CLI 时哪些字段必须保留。

### 4.2 Phase 1：CLI 闭环打通

- 实现 `build / flash / debug-start / monitor` 四个核心子命令。
- 统一工程输入形式，例如：
  - 工程根路径
  - 目标芯片
  - 探针类型
  - OpenOCD interface/target config
  - 串口号与波特率
- 让命令行版本先可独立工作。

### 4.3 Phase 2：调试能力封装

- 实现 GDB 会话管理。
- 支持：
  - 断点设置与删除
  - 单步、继续、暂停
  - 寄存器读取
  - 堆栈回溯
  - 表达式求值
- 解决多进程生命周期管理：OpenOCD 与 GDB 退出时的清理逻辑。

### 4.4 Phase 3：MCP Server 封装

- 将 CLI 子命令映射为 MCP Tools。
- 设计 tool schema，保证 Agent 调用参数简洁明确。
- 输出适合模型消费的错误信息，例如“OpenOCD 未连接目标板”“ELF 未生成”“断点未命中”等。

### 4.5 Phase 4：双帧兼容与隔离环境

- 实现 JSON-RPC 双帧适配层：
  - `Content-Length` 风格消息封包
  - `newline-delimited JSON` 风格消息封包
- 提供可切换的 transport 适配器，提升跨客户端兼容性。
- 使用 `venv` 或固定依赖环境，降低复现成本。

---

## 5. 难点预判

### 5.1 调试状态管理

- **难点：** `OpenOCD`、`GDB`、串口监视三类进程都可能长时间驻留，且彼此存在依赖关系。
- **风险：** 进程退出不彻底会导致端口占用、会话残留、重复连接失败。
- **策略：** 先约束为“单活动会话 + 显式启动/停止命令 + 统一进程表管理”。

### 5.2 GDB 交互稳定性

- **难点：** 如果直接解析普通终端输出，结构不稳定；如果引入 MI 模式，复杂度会上升。
- **策略：** MVP 阶段优先验证两条路径：
  - 路径 A：普通 GDB 命令 + 规则化输出解析
  - 路径 B：GDB/MI 结构化输出
- **建议：** 如果想尽快做出第一个可用版本，先用普通命令流；如果想给 Agent 更稳定的数据结构，再逐步切到 MI。

### 5.3 跨客户端传输兼容

- **难点：** 不同客户端对 JSON-RPC 传输包装的容忍度不同。
- **策略：** 将 framing 层从业务层完全剥离，做成 adapter，不把兼容逻辑散落在 tool handler 内。

### 5.4 Windows 路径与环境问题

- **难点：** 当前工作环境是 Windows，路径、编码、OpenOCD 与 LaTeX/脚本工具一样，都可能出现中文路径兼容问题。
- **策略：**
  - 项目源码与运行目录尽量放在纯英文路径。
  - 对外暴露的配置文件使用正斜杠路径规范。
  - 记录一份环境检查清单，减少后续迁移踩坑。

---

## 6. 可复用资产

- **现有调试资产：** [STM32 开发环境迁移指南：从 CLION 到 VS Code](STM32%20开发环境迁移指南：从%20CLION%20到%20VS%20Code.md)
- **可直接复用内容：**
  - `launch.json` 中 `ST-Link / DAPLink` 双配置思路
  - `CMake Tools` 的目标选择与构建逻辑
  - `OpenOCD interface/target config` 组合方式
- **后续建议沉淀：**
  - 一份标准化工程模板
  - 一份标准化 probe 配置模板
  - 一份标准化 MCP tool schema

---

## 7. 产出物规划

- **文档产出：**
  - 主档案
  - 实施路线与接口设计
  - 调试踩坑记录
  - 环境搭建说明
- **工程产出：**
  - CLI 工具原型
  - MCP Server 原型
  - 示例 STM32 工程配置
- **面试/简历产出：**
  - “复用 VS Code/OpenOCD 工作流，构建 AI Agent 可调用的 STM32 自动化调试链路”这类真实且可展开的项目表述

---

## 8. 当前 TODO

- [ ] 选定一个最小示例 STM32 工程作为验证对象
- [ ] 从现有 `launch.json` 中抽出 probe 与 target 的可配置项
- [ ] 明确 CLI 子命令接口与输入参数
- [ ] 先用命令行打通 `build → flash → monitor`
- [ ] 再补 `debug-start / breakpoint / step / backtrace`
- [ ] 最后再封装 MCP 和 JSON-RPC 双帧适配

