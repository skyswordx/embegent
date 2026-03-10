# STM32 AI 调试链路

一个面向 STM32 嵌入式开发的 `CLI + MCP` 工具链原型，目标是在现有 `VS Code + CMake + OpenOCD + GDB` 工作流基础上，快速打通可被 AI Agent 调用的自动化链路。

## 当前目标

- 复用已有工程配置打通 `build -> flash -> debug -> monitor`
- 将常用调试能力封装为稳定 CLI
- 再向上暴露为 MCP Tools
- 兼容 `Content-Length` 与换行分隔两类 JSON-RPC framing

## 计划中的目录结构

```text
.
├─ src/stm32_agent/
│  ├─ __init__.py
│  └─ cli.py
├─ tests/
├─ configs/examples/
│  └─ project.example.yaml
├─ 项目-STM32-AI调试链路-主档案.md
├─ 实施路线-STM32 AI 调试链路 MVP.md
├─ pyproject.toml
└─ .gitignore
```

## 第一阶段范围

- `build`
- `flash`
- `monitor`
- `debug start`
- `debug stop`
- `debug step`
- `debug continue`
- `debug registers`
- `debug backtrace`

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -U pip
.venv/Scripts/pip install -e .
stm32-agent --help
```

## 下一步

- 抽取一个现有 STM32 工程的 `launch.json` 作为配置样板
- 验证 OpenOCD 单命令烧录链路
- 起第一版 session manager
- 再接入 MCP Server

