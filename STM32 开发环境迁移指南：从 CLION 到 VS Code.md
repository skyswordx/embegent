# STM32 开发环境迁移指南：从 CLION 到 VS Code

## 前言

我们之前的 CLION 开发流是：**CMake +** **Ninja** **+ ARM-GCC + OpenOCD**。 VS Code 同样完美支持这套工具链，而且更加轻量、免费且插件生态丰富。迁移的核心在于**“显式配置”**——我们需要手动告诉 VS Code 这些工具在哪里。

---

## 第一步：安装核心插件 (The "Holy Trinity")

VS Code 本体只是个编辑器，变成 IDE 全靠插件。请在扩展商店 (Extensions) 搜索并安装以下“三剑客”：

1. **C/C++** **Extension Pack** (Microsoft)
    
    1. _作用：_ 提供代码高亮、智能补全 (IntelliSense)、跳转定义等基础 C/C++ 功能。
        
2. **CMake Tools** (Microsoft)
    
    1. _作用：_ 接管构建系统。它能自动识别 `CMakeLists.txt`，提供底部的构建状态栏，一键调用 CMake 和 Make/Ninja。
        
3. **Cortex-Debug** (marus25)
    
    1. _作用：_ 嵌入式调试神器。替代了 CLION 的调试面板，支持 OpenOCD/J-Link，能查看寄存器 (SVD) 和 FreeRTOS 任务状态。
        

---

## 第二步：配置环境变量 (最关键的一步)

**这是与 CLION 最大的不同。** CLION 内部集成了工具，而 VS Code 默认去系统的 `PATH` 环境变量里找。如果找不到，就会报错。

请确保以下工具的 `bin` 目录已添加到 Windows 的 **系统****环境变量** **Path** 中：

1. **交叉编译器 (****`arm-none-eabi-gcc`****)**: 也就是你的 GCC 路径。
    
2. **构建工具 (****`ninja`****)**: 既然用 CMake，推荐搭配 Ninja 速度最快。
    
3. **构建大脑 (****`cmake`****)**: 生成构建规则。
    
4. **调试服务 (****`openocd`****)**: 用于连接 DAP-Link/ST-Link。
    

**如何添加系统****环境变量****Path？**

**如果自检发现没有的话，只需要找上述4个工具所在目录的****bin****文件夹，把该文件夹的地址复制，然后按Win，搜索编辑系统****环境变量****，进去之后按下环境变量，在里面找到名字为"Path"的变量，点击它之后，将该地址粘贴进去，一路点击确定即可，之后****重启****VSCODE，再次自检即可。**

> **自检方法：** 重启 VS Code，打开终端 (Terminal)，输入以下命令。如果有版本号输出，说明配置成功；如果提示“无法识别”，请检查环境变量。
> 
> Bash
> 
> ```Plain
> arm-none-eabi-gcc --version
> ninja --version
> openocd --version
> ```

---

## 第三步：导入工程与编译 (CMake配置)

1. **打开工程：**
    
    1. 在 VS Code 中点击 `文件` -> `打开文件夹`，选择包含 `CMakeLists.txt` 的根目录（通常是 CubeMX 生成的那个目录）。
        
2. **选择工具链 (Kit)：**
    
    1. VS Code 打开后，CMake Tools 会自动扫描。
        
    2. 没有弹出可以Ctrl+Shift+P 输入CMake Select a Kit选择
        
    3. **关键点：** 必须选择 **`GCC ... arm-none-eabi`** (例如 `GCC 13.3.1 arm-none-eabi`)。
        
    4. _避坑：千万不要选 Visual Studio 或 MinGW，那是给电脑写软件用的。_
        
3. **编译 (Build)：**
    
    1. 点击底部状态栏的 **齿轮图标 (Build)**，或者按快捷键 **`F7`**。
        
    2. 看到 `[100%] Built target ...` 即表示编译成功。
        

---

## 第四步：配置烧录与调试 (`launch.json`)

VS Code 不会自动生成调试配置，我们需要手动创建一个 `.vscode/launch.json` 文件。

**场景：** 我们希望支持 **DAP-Link** 和 **ST-Link** 双模切换。 **操作：** 在项目根目录新建 `.vscode/launch.json`，复制以下内容：

JSON

```Plain
{
    "version": "0.2.0",
    "configurations": [
        /* === 配置 1: DAP-Link (无线/有线) === */
        {
            "name": "DAP-Link",
            "type": "cortex-debug",
            "request": "launch",
            "servertype": "openocd",
            "cwd": "${workspaceFolder}",
            "executable": "${command:cmake.launchTargetPath}", 
            "device": "STM32F407IGH6", /* 你的芯片型号 */
            "configFiles": [
                "interface/cmsis-dap.cfg",
                "target/stm32f4x.cfg"
            ],
            "runToEntryPoint": "main",
            "svdFile": "${workspaceFolder}/STM32F407.svd" /* 选填，看寄存器用 */
        },
        /* === 配置 2: ST-Link === */
        {
            "name": "ST-Link",
            "type": "cortex-debug",
            "request": "launch",
            "servertype": "openocd",
            "cwd": "${workspaceFolder}",
            "executable": "${command:cmake.launchTargetPath}",
            "device": "STM32F407IGH6",
            "configFiles": [
                "interface/stlink.cfg",
                "target/stm32f4x.cfg"
            ],
            "runToEntryPoint": "main",
            "svdFile": "${workspaceFolder}/STM32F407.svd"
        }
    ]
}
```

---

## 第五步：开始调试

1. 点击左侧侧边栏的 **“运行和调试”** 图标 (虫子+三角形)。
    
2. 在顶部的下拉菜单中，选择 **`DAP-Link`** **or STLINK**。
    
3. 按 **`F5`** 键。
    
4. VS Code 会自动执行：**编译 -> 启动 OpenOCD -> 烧录 -> 暂停在 main 函数**。
    

---

---

## 第六步：在STM32CUBEMX新建工程+VSCODE使用

1. 注意CUBEMX里面要选择CMAKE生成工程，其他选项跟使用keil的时候一模一样
    
2. 每次新建的工程，都需要重新配置一次cmake-config,只需要按下Ctrl+shift+P,选择Cmake-Config，然后选择
    

**`arm-none-eabi-gcc`****即可**

3. 然后就是复制知识库里面的launch.json内容即可。配置完成之后重启，就可以正常使用了，非常简单。
    

---

## 进阶技巧 (Master Class)

### 1. 工程管理规范

建议在 `.gitignore` 中把 `.vscode` 文件夹忽略掉（或者只保留 `launch.json`），因为每个人的编译器路径可能不同。让团队成员各自配置自己的环境，互不干扰。

2. ### 变量监视与修改 (Watch & Modify)
    

- **查看局部变量：** 左侧 **"变量 (Variables)"** 面板会自动显示当前函数内的局部变量值。
    
- **监视全局/特定变量：**
    
    - 局部变量面板里找不到全局变量？
        
    - _操作：_ 在代码中选中变量名 -> 右键 -> **添加到监视 (Add to Watch)**。或者在左侧 **"监视 (Watch)"** 面板点击 `+` 号手动输入。
        
    - _技巧：_ 支持结构体成员（如 `gimbal.pitch_angle`）和指针解引用（如 `*ptr`）。
        
- **实时修改变量值 (Live Tuning)：**
    
    - _场景：_ 调 PID 参数时，想试试把 P 也就是 `kp` 增大一点，但不想重新编译烧录。
        
    - _操作：_ 在变量面板或监视面板，双击变量的值 -> 输入新数值 -> 回车。
        
    - _效果：_ 芯片内存里的值立刻改变，下一刻电机就会按新参数运行。
        
- **十六进制查看：** 右键点击监视面板中的变量 -> **以十六进制显示 (Binary/Hex View)**。
    

---

3. ### 寄存器透视 (SVD - The X-Ray)
    

这是嵌入式开发比纯软件开发多出来的核心需求。

- **准备工作：**
    
    - 去 ST 官网下载 `STM32F407.svd` 文件（或从 Keil 的 pack 里找）。
        
    - 放在工程根目录。
        
    - 在 `launch.json` 中配置 `"svdFile": "${workspaceFolder}/STM32F407.svd"`。
        
- **使用方法：**
    
    - 启动调试后，左侧面板底部会出现 **CORTEX PERIPHERALS**。
        
    - 展开它，你会看到 `GPIOA`, `TIM1`, `CAN1` 等所有外设。
        
    - _实战：_ 展开 `GPIOA` -> `ODR`，你可以看到每一个 Pin 的高低电平状态。甚至可以直接点击那个位（Bit）来**手动翻转电平**（比如点灯测试）。
        

---

4. ### 内存查看 (Memory View)
    

当你需要查看 DMA 缓冲区、串口接收的原始字节流时。

- **操作：**
    
    - 按 `Ctrl+Shift+P` -> 输入 **`Cortex-Debug: View Memory`**。
        
    - 输入起始地址（例如 `0x20000000` 或直接输入数组名 `RxBuffer`）。
        
    - 输入读取长度（例如 `128`）。
        
- **效果：** 会弹出一个类似 Hex Editor 的界面，实时显示该段内存的原始数据。
    

---

5. ### FreeRTOS 任务监控 (RTOS Awareness)
    

如果不看 RTOS 状态，死机了都不知道是哪个任务爆栈了。

- **配置：** 在 `launch.json` 中添加 `"rtos": "FreeRTOS"`。
    
- **效果：**
    
    - 调试时底部会出现 **XRTOS** 面板。
        
    - **Threads:** 显示所有任务名称 (Task Name)。
        
    - **State:** 显示状态 (Running, Blocked, Suspended)。
        
    - **Stack Base / End:** 栈地址。
        
    - **Stack Usage:** (部分 OpenOCD 版本支持) 显示栈使用率，如果接近 100% 就要小心了。
        

  

6. ### 启动与控制 (The Cockpit)
    

- **进入调试模式：**
    
    - 确保左侧面板选中了正确的配置（如 `DAP-Link`）。
        
    - 按 **`F5`** 键启动。
        
    - _现象：_ 底部状态栏变为**橙色**，代码界面高亮停在 `main()` 函数首行。
        
- **控制条 (悬浮工具栏)：**
    
    - **继续 (F5):** 全速运行，直到遇到下一个断点。
        
    - **单步跳过 (F10):** 执行当前行。如果是函数，**不进入**函数内部，直接执行完该函数。
        
    - **单步调试 (F11):** **进入**函数内部，查看细节。
        
    - **单步跳出 (Shift+F11):** 快速执行完当前函数剩余代码，返回上一层调用。
        
    - **重启 (Ctrl+Shift+F5):** 不用重新烧录，直接复位芯片重新跑（调试逻辑 bug 时最常用）。
        
    - **停止 (Shift+F5):** 断开连接。
        

---

7. ### 断点 (Advanced Breakpoints)
    

别只会在行号左边点红点，VS Code 支持更高级的断点技巧。

- **普通断点：** 在行号左侧单击，出现🔴红点。
    
- **条件断点 (Conditional Breakpoint) ——** _**大师必修**_**：**
    
    - _场景：_ 电机只有在速度超过 8000 时才会出现震动，我不想手动按几千次 F5。
        
    - _操作：_ 右键点击红点 -> **编辑断点 (Edit Breakpoint)** -> 选择 **表达式 (Expression)**。
        
    - _输入：_ `motor_feedback.speed > 8000`
        
    - _效果：_ 程序全速运行，只有当该变量满足条件时，才会自动暂停。
        
- **命中次数断点 (Hit Count):**
    
    - _场景：_ 这个循环跑了 100 次后会死机。
        
    - _输入：_ `100`
        
    - _效果：_ 第 100 次执行到这一行时暂停。
        
- **日志断点 (Log Message):**
    
    - _操作：_ 选择 **日志消息**。
        
    - _输入：_ `Current Speed: {speed}`
        
    - _效果：_ **程序不会暂停**，但会在底部的“调试控制台”打印出变量值。这相当于**不需要重新编译代码的 printf**！
        

  

# 在Linux系统中使用此套编译链：

第一步第二步完全相同，下载三剑客并下载以下包

> arm-none-eabi-gcc --version ninja --version openocd --version

第三步唯一不同在于直接build即可，不需要额外配置，若失败检查程序本身可能存在问题

第四步相同，在.vscode中创建launch.json并修改为

> { "version": "0.2.0", "configurations": [ /* === 配置 1: DAP-Link (无线/有线) === */ { "name": "DAP-Link", "type": "cortex-debug", "request": "launch", "servertype": "openocd", "cwd": "${workspaceFolder}", "executable": "${command:cmake.launchTargetPath}", "device": "STM32F407IGH6", /* 你的芯片型号 */ "configFiles": [ "interface/cmsis-dap.cfg", "target/stm32f4x.cfg" ], "runToEntryPoint": "main", "svdFile": "${workspaceFolder}/STM32F407.svd" /* 选填，看寄存器用 */ }, /* === 配置 2: ST-Link === */ { "name": "ST-Link", "type": "cortex-debug", "request": "launch", "servertype": "openocd", "cwd": "${workspaceFolder}", "executable": "${command:cmake.launchTargetPath}", "device": "STM32F407IGH6", "configFiles": [ "interface/stlink.cfg", "target/stm32f4x.cfg" ], "runToEntryPoint": "main", "svdFile": "${workspaceFolder}/STM32F407.svd" } ] }

另外在该目录下创建tasks.json:

```Bash
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Flash (DAP-Link)",
            "type": "shell",
            "command": "openocd",
            "args": [
                "-f", "interface/cmsis-dap.cfg",
                "-f", "target/stm32f4x.cfg",
                "-c", "program ${command:cmake.launchTargetPath} verify reset exit"
            ],
            "problemMatcher": [],
            "group": {
                "kind": "build",
                "isDefault": false
            },
            "presentation": {
                "reveal": "always",
                "panel": "new"
            }
        },
        {
            "label": "Flash (ST-Link)",
            "type": "shell",
            "command": "openocd",
            "args": [
                "-f", "interface/stlink.cfg",
                "-f", "target/stm32f4x.cfg",
                "-c", "program ${command:cmake.launchTargetPath} verify reset exit"
            ],
            "problemMatcher": [],
            "group": {
                "kind": "build",
                "isDefault": false
            },
            "presentation": {
                "reveal": "always",
                "panel": "new"
            }
        }
    ]
}
```

完成以上配置就可以在ubuntu（至少22.04可行）系统中使用vscode进行烧录与调试

在左侧run and debug进行调试

ctrl+shift+P打开面板输入Tasks:Run Task 自动弹出Flash (DAP-Link) 或与Flash (ST-Link)，选择需要的即可。