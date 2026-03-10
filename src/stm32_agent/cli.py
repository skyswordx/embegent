import typer

app = typer.Typer(help="STM32 AI 调试链路 CLI 原型。")
debug_app = typer.Typer(help="调试相关命令。")
app.add_typer(debug_app, name="debug")


@app.command()
def build() -> None:
    """构建当前 STM32 工程。"""
    typer.echo("TODO: build workflow")


@app.command()
def flash() -> None:
    """烧录 ELF 到目标板。"""
    typer.echo("TODO: flash workflow")


@app.command()
def monitor() -> None:
    """启动串口监视。"""
    typer.echo("TODO: monitor workflow")


@debug_app.command("start")
def debug_start() -> None:
    """启动 OpenOCD + GDB 调试会话。"""
    typer.echo("TODO: debug start")


@debug_app.command("stop")
def debug_stop() -> None:
    """停止当前调试会话。"""
    typer.echo("TODO: debug stop")


@debug_app.command("step")
def debug_step() -> None:
    """执行单步调试。"""
    typer.echo("TODO: debug step")


@debug_app.command("continue")
def debug_continue() -> None:
    """继续执行当前程序。"""
    typer.echo("TODO: debug continue")


@debug_app.command("registers")
def debug_registers() -> None:
    """读取寄存器。"""
    typer.echo("TODO: debug registers")


@debug_app.command("backtrace")
def debug_backtrace() -> None:
    """读取堆栈回溯。"""
    typer.echo("TODO: debug backtrace")


if __name__ == "__main__":
    app()

