import asyncio
import json
import os
import signal
import sys
import tempfile

from backend.config import ROOT


class ExecutionError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


async def isolated(payload, settings):
    env = {
        **os.environ,
        "GRIDPILOT_DATA_DIR": str(settings.data_dir),
        "GRIDPILOT_AGENT_CALLABLE": settings.agent_callable,
        "GRIDPILOT_SOLVE_CALLABLE": settings.solve_callable,
        "GRIDPILOT_VALIDATE_CALLABLE": settings.validate_callable,
    }
    # File output prevents an adapter's accidental huge logs/JSON from growing API memory.
    with tempfile.TemporaryFile() as output:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "backend.worker",
            cwd=ROOT,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=output,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode()), timeout=settings.timeout_seconds
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ExecutionError(
                "execution_timeout", "Investigation exceeded configured time limit"
            ) from None
        output.seek(0)
        raw = output.read(2_000_001)
    if process.returncode or len(raw) > 2_000_000:
        raise ExecutionError(
            "worker_failed", "Worker exited unsuccessfully or returned an oversized result"
        )
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ExecutionError(
            "invalid_worker_output", "Worker did not return protocol JSON"
        ) from None
    if not envelope.get("ok"):
        raise ExecutionError(envelope["error"]["code"], envelope["error"]["message"])
    return envelope["result"]
