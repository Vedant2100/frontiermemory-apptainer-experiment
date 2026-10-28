#!/usr/bin/env python3
"""Run the Harbor CLI with one Singularity exec-timeout correction.

Harbor 0.24.0's SingularityEnvironment.exec uses a hard 600 s HTTP timeout
when the caller passes no timeout_sec. The OpenHands SDK agent runs its whole
session in one such exec, so trials were cut at 600 s and then reported as an
AgentTimeoutError naming the task's 1200 s limit. This wrapper fills in a
generous timeout_sec for those calls only, so the trial's own asyncio timeout
(task.toml [agent] timeout_sec x multiplier) is the binding limit again.
Calls that pass an explicit timeout_sec are unchanged. Applies to A and B alike.
"""

from __future__ import annotations

import functools
import os
import sys

from harbor.environments.singularity.singularity import SingularityEnvironment

FALLBACK_EXEC_TIMEOUT_SEC = int(os.environ.get("HARBOR_SINGULARITY_EXEC_TIMEOUT_SEC", "7200"))

_original_exec = SingularityEnvironment.exec


@functools.wraps(_original_exec)
async def _exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
    if timeout_sec is None:
        timeout_sec = FALLBACK_EXEC_TIMEOUT_SEC
    return await _original_exec(self, command, cwd=cwd, env=env, timeout_sec=timeout_sec, user=user)


SingularityEnvironment.exec = _exec

if __name__ == "__main__":
    from harbor.cli.main import app

    sys.argv[0] = "harbor"
    sys.exit(app())
