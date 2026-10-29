#!/usr/bin/env python3
"""Memory exposure: which topic entries Codex actually shows the model.

Codex 0.157 injects $CODEX_HOME/memories/memory_summary.md (our MEMORY.md) into the
developer prompt, keeping only the first and last WINDOW characters and replacing the
middle with "…N tokens truncated…". Observed in request bodies of jobs 303129, 303133
and 303198. This script reproduces that window offline and, with --bodies, checks the
reproduction against the logged Ollama request bodies of a job.

Prints counts only. Topic names are memory content; --details writes them to a local
(git-ignored) file.
"""
import argparse
import glob
import json
import os
import re
import sys

WINDOW = 5000
SLUG = re.compile(r"g\d{3}-[a-z0-9-]+")
TRUNC = re.compile(r"…\d+ tokens truncated…")
STOP = {"the", "and", "of", "a", "to", "in", "for", "with", "v1", "v2", "task", "tier"}


def visible(src):
    if len(src) <= 2 * WINDOW:
        return src
    return src[:WINDOW] + "\n" + src[-WINDOW:]


def injected_excerpt(job_dir):
    for f in sorted(glob.glob(os.path.join(job_dir, "ollama/tmp/*/*_body.json"))):
        text = open(f, errors="ignore").read()
        if "MEMORY_SUMMARY BEGINS" not in text:
            continue
        for s in _strings(json.loads(text)):
            m = re.search(r"MEMORY_SUMMARY BEGINS =+\n(.*?)\n=+ MEMORY_SUMMARY ENDS", s, re.S)
            if m:
                return m.group(1)
    return None


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def name_tokens(name):
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) > 2 and t not in STOP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True, help="memory dir with MEMORY.md")
    ap.add_argument("--tasks", nargs="*", default=[], help="task names for same-family tagging")
    ap.add_argument("--bodies", help="job dir whose logged request bodies to check against")
    ap.add_argument("--details", help="write visible topic slugs (local only)")
    a = ap.parse_args()

    src = open(os.path.join(a.memory, "MEMORY.md")).read()
    vis = visible(src)
    all_slugs = set(SLUG.findall(src))
    vis_slugs = set(SLUG.findall(vis)) & all_slugs
    out = {"memory": a.memory, "memory_md_chars": len(src), "truncated": len(src) > 2 * WINDOW,
           "slugs_in_memory_md": len(all_slugs), "slugs_visible": len(vis_slugs), "per_task": {}}
    for task in a.tasks:
        toks = name_tokens(task)
        same = lambda s: bool(toks & name_tokens(s))
        out["per_task"][task] = {"same_family_in_memory_md": sum(map(same, all_slugs)),
                                 "same_family_visible": sum(map(same, vis_slugs)),
                                 "other_family_visible": sum(not same(s) for s in vis_slugs)}
    if a.bodies:
        got = injected_excerpt(a.bodies)
        if got is None:
            out["bodies_check"] = "no memory summary in bodies"
        else:
            head, _, tail = got.partition(TRUNC.search(got).group(0)) if TRUNC.search(got) else (got, "", "")
            out["bodies_check"] = ("match" if src.startswith(head.rstrip("\n")) and
                                   src.rstrip().endswith(tail.strip()) and
                                   set(SLUG.findall(got)) & all_slugs == vis_slugs else "MISMATCH")
    if a.details:
        with open(a.details, "w") as f:
            json.dump(sorted(vis_slugs), f, indent=1)
    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
