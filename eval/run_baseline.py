#!/usr/bin/env python3
"""
Step 0 — Baseline: invokes TS pipeline, saves to eval/out_baseline/.
Run: npm run eval:baseline  (or python eval/run_baseline.py)
"""
import subprocess
import sys

def main():
    r = subprocess.run(
        ["npm", "run", "eval:baseline"],
        cwd=".",
    )
    sys.exit(r.returncode)

if __name__ == "__main__":
    main()
