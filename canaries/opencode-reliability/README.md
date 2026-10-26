# OpenCode reliability canary

This disposable Harbor task checks four runner behaviors before another benchmark comparison:

1. OpenCode creates new source and test files through Bash heredocs (the shared prompt also permits OpenCode's native write tool).
2. OpenCode runs a focused `unittest` suite.
3. Harbor's collector captures uncommitted and untracked code/tests in `model.patch` while excluding the OpenCode runtime under `/app/files` that Harbor uploads for setup.
4. A separate Apptainer verifier applies that patch, reruns the tests, and checks the greeting contract independently.

The task uses the existing cattrs SIF as both agent and separate verifier base, plus the already staged OpenCode 1.19.4 Node runtime/offline npm shims. Its custom test script is uploaded by Harbor. It does not modify cattrs source, the official FrontierMemory task, or its verifier, and it does not rebuild images. It is a harness canary, not a benchmark result.

To stage it for the existing Slurm runner, replace the `/path/to/frontier-memory-cattrs.sif` placeholder in `task.toml` with the absolute path to the existing agent SIF. Copy this directory to `build/opencode-frontiermemory-tasks/opencode-reliability-canary`, then copy the existing cattrs task's `environment/files` tree into the canary's `environment/files`. Run with `CONDITION=A`, `TASK_IDS=opencode-reliability-canary`, and the existing `slurm/run-opencode-frontiermemory-tasks.sbatch`. `TASK_ROOT` in that script defaults to `build/opencode-frontiermemory-tasks`.

The task prompt asks the agent to create `canary_greeting.py` and `test_canary_greeting.py` with Bash heredocs, run `python3 -m unittest -v test_canary_greeting.py`, inspect its diff, and leave its files uncommitted so collection is exercised.
