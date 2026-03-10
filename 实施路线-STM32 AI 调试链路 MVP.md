# 实施路线：STM32 AI 调试链路 MVP

## 1. 核心思路

这个项目不要从“做一个很完整的 MCP Server”开始，而要从“把你当前 VS Code 里已经能跑通的事情抽成命令”开始。

最短路径是：

1. 先复用现有 `CMake + OpenOCD + GDB + launch.json` 配置。
2. 把它们抽成 CLI 子命令。
3. 让 CLI 先能稳定打通 `build → flash → debug → monitor`。
4. 最后再把 CLI 映射成 MCP Tools。

换句话说，**MCP 不是第一层，CLI 才是第一层。**

---

## 2. MVP 架构草图

```text
AI Agent
   ↓
MCP Server
   ↓
CLI Command Layer
   ↓
Project Adapter / Session Manager
   ├─ CMake Build
   ├─ OpenOCD Flash / GDB Server
   ├─ GDB Debug Control
   └─ Serial Monitor
```

### 2.1 为什么这样拆

- **CLI 可单测、可手调、可脱离 Agent 验证**
- **MCP 只做暴露能力，不承担核心逻辑**
- **将来就算不接 MCP，这套 CLI 也能独立提高日常开发效率**

---

## 3. 第一阶段建议接口

### 3.1 CLI 子命令

建议第一版只做下面这些：

- `stm32-agent build`
- `stm32-agent flash`
- `stm32-agent monitor`
- `stm32-agent debug start`
- `stm32-agent debug stop`
- `stm32-agent debug breakpoint-set`
- `stm32-agent debug continue`
- `stm32-agent debug step`
- `stm32-agent debug registers`
- `stm32-agent debug backtrace`

### 3.2 公共参数

建议每条命令都尽量复用这几类参数：

- `--workspace`
- `--build-dir`
- `--elf`
- `--probe`：`stlink` / `daplink`
- `--target-cfg`
- `--interface-cfg`
- `--serial-port`
- `--baudrate`

如果不想每次都手输，后面可以补一个项目级配置文件，例如：

```yaml
project_name: venom_f407
workspace: D:/xxx/project
build_dir: build
elf: build/robot.elf
probe: stlink
interface_cfg: interface/stlink.cfg
target_cfg: target/stm32f4x.cfg
serial_port: COM6
baudrate: 115200
```

---

## 4. 具体落地建议

## 4.1 build

直接复用 CMake 已有能力，不自己重新推导编译参数：

- 优先调用：
  - `cmake -S <workspace> -B <build_dir>`
  - `cmake --build <build_dir> --target all -j`
- 如果你当前工程高度依赖 VS Code 的 CMake Tools，也可以先做一层“兼容当前目录结构”的薄封装。

**输出要求：**

- 明确返回 ELF 路径
- 明确返回编译是否成功
- 出错时保留最后一段关键日志

## 4.2 flash

烧录层尽量不要依赖 VS Code 调试按钮，而是直接走 OpenOCD：

典型思路：

```text
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
  -c "program xxx.elf verify reset exit"
```

如果要兼容 `DAPLink`，只替换 interface 配置即可。

**建议：**

- 把 `interface_cfg + target_cfg + program command` 做成模板化配置。
- 第一版只支持单目标单 ELF。

## 4.3 monitor

用 `pyserial` 单独起串口监视，不和 OpenOCD/GDB 强绑定。

第一版支持：

- 打开串口
- 持续读取
- 保存日志到文件
- 提供最近 N 行输出接口

这对 AI 非常关键，因为很多时候模型不需要图形调试，只需要“最近串口输出发生了什么”。

## 4.4 debug start

建议采用“双进程管理”：

- 进程 1：启动 `openocd`，作为 GDB Server
- 进程 2：启动 `arm-none-eabi-gdb` 连接 `localhost:3333`

建议把会话信息记录到一个 session 文件中，例如：

```json
{
  "session_id": "debug-001",
  "openocd_pid": 1234,
  "gdb_pid": 5678,
  "gdb_port": 3333,
  "workspace": "D:/xxx/project"
}
```

这样后面 `debug stop`、`registers`、`backtrace` 都有状态可查。

---

## 5. GDB 能力的优先级排序

为了尽快做出能用的版本，建议优先顺序如下：

1. `target remote`
2. `monitor reset halt`
3. `load`
4. `break main`
5. `continue`
6. `next` / `step`
7. `info registers`
8. `bt`
9. `print <expr>`

先别急着一开始做条件断点、内存窗口、变量修改、RTOS 线程感知，这些都可以放在第二阶段。

---

## 6. MCP Tool 设计建议

建议第一版 MCP Tools 不要做太细，先做粗粒度工具：

- `stm32_build`
- `stm32_flash`
- `stm32_monitor_start`
- `stm32_monitor_tail`
- `stm32_debug_start`
- `stm32_debug_continue`
- `stm32_debug_step`
- `stm32_debug_get_registers`
- `stm32_debug_backtrace`
- `stm32_debug_stop`

### 6.1 为什么先做粗粒度

- Tool 数量少，模型更不容易选错
- 便于你先验证 Agent 是否真的有帮助
- 后续再根据使用频率拆出更细粒度工具

### 6.2 返回值建议

每个 Tool 尽量返回统一结构：

```json
{
  "ok": true,
  "summary": "Breakpoint hit at main",
  "data": {},
  "logs": []
}
```

这样 AI 更容易稳定消费。

---

## 7. JSON-RPC 双帧兼容策略

## 7.1 为什么要单独设计

不同客户端、脚手架或调试代理，对 JSON-RPC 的消息封装容忍度可能不同。为了降低后面接客户端时的反复返工，建议从一开始就把 framing 和业务逻辑拆开。

## 7.2 推荐做法

设计两个 adapter：

- `content_length_transport`
- `json_line_transport`

对上层 MCP/Tool Handler 暴露同样的接口：

- `read_message()`
- `write_message(obj)`

这样后续切换 transport 不需要改具体 tool 逻辑。

## 7.3 落地建议

- 第一版主跑 `stdio`
- 双帧兼容作为 transport 层附加能力
- 先把消息日志完整记录下来，便于排查不同客户端差异

---

## 8. 隔离环境建议

建议为这个项目单独维护一个 Python 虚拟环境：

- 固定 `python` 版本
- 固定 `pyserial / mcp sdk / typer` 等依赖版本
- 增加一个 `doctor` 命令检查：
  - `cmake`
  - `openocd`
  - `arm-none-eabi-gdb`
  - 串口是否存在
  - OpenOCD config 文件是否存在

这一步很值，因为嵌入式工具链最怕“代码没问题，环境有问题”。

---

## 9. 与你当前 VS Code 工作流的衔接建议

你当前不需要抛弃 VS Code，相反应该把它作为“金标准参考实现”：

- **VS Code 能跑通 = CLI 应该复现同样行为**
- **`launch.json` 是事实来源，不是临时参考**
- **一旦 CLI 跑通，MCP 只是在 CLI 外再包一层**

最稳的路径不是“摆脱 VS Code”，而是“把 VS Code 里已经成功的配置抽象成可编程接口”。

---

## 10. 最近一周可执行任务

- [ ] 选一个已经能在 VS Code 稳定编译下载的 STM32 工程
- [ ] 提取该工程 `.vscode/launch.json` 里的 probe/target 配置
- [ ] 手动验证一条 OpenOCD 命令能完成 `program verify reset exit`
- [ ] 手动验证 GDB 能连到 `localhost:3333`
- [ ] 整理出第一版 CLI 参数表
- [ ] 再决定是否直接引入 MCP SDK，还是先自己做薄的 JSON-RPC 封装

---

## 11. 参考资料

- MCP 官方文档（Overview）：https://modelcontextprotocol.io/docs/getting-started/intro
- MCP 官方文档（Transports）：https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- VS Code Cortex-Debug： https://github.com/Marus/cortex-debug
- OpenOCD 官方文档： https://openocd.org/pages/documentation.html
- 本地参考： [STM32 开发环境迁移指南：从 CLION 到 VS Code](STM32%20开发环境迁移指南：从%20CLION%20到%20VS%20Code.md)
