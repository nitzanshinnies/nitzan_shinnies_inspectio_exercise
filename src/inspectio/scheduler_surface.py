"""
Assignment-mandated surface (§25). Wired to `WorkerRuntime` by worker `main`.

PDF mapping (README must duplicate):
  send          <- boolean send(Message)
  new_message   <- void newMessage(Message)
  wakeup        <- void wakeup()
"""

from __future__ import annotations

import asyncio
import logging

from inspectio.models import Message
from inspectio.worker.runtime import WorkerRuntime

_runtime: WorkerRuntime | None = None
log = logging.getLogger("inspectio.scheduler_surface")


def configure_runtime(runtime: WorkerRuntime) -> None:
    """Called once from worker `main` after `WorkerRuntime` is constructed."""
    global _runtime
    _runtime = runtime


def require_runtime() -> WorkerRuntime:
    if _runtime is None:
        msg = "scheduler not configured; worker main must call configure_runtime"
        raise RuntimeError(msg)
    return _runtime


def send(message: Message) -> bool:
    """Sync entry for tests; async worker code uses `WorkerRuntime.async_send`."""
    rt = require_runtime()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(rt.async_send(message))
    raise RuntimeError(
        "scheduler_surface.send cannot block the running event loop; "
        "await WorkerRuntime.async_send from async code"
    )


def new_message(message: Message) -> None:
    task = asyncio.get_running_loop().create_task(
        require_runtime().dispatch_new_message(message)
    )
    task.add_done_callback(_log_task_exception)


def wakeup() -> None:
    task = asyncio.get_running_loop().create_task(require_runtime().wakeup_due())
    task.add_done_callback(_log_task_exception)


def _log_task_exception(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.exception("scheduler task failed", exc_info=exc)
