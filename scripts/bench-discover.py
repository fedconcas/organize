#!/usr/bin/env python3
"""Dev-only benchmark for category discovery (not shipped).

Compare the engine's proposal with YOUR own grouping of ~50 real files:

    python scripts/bench-discover.py --truth my-grouping.csv      # CSV columns: path,folder

or run it on the synthetic corpus (tests only, NOT a substitute for real files):

    python scripts/bench-discover.py --synthetic 500 --workdir /tmp/bench

Reports adjusted Rand index (target >= 0.5), purity of the largest categories (>= 80%),
edit effort, repeatability (two identical runs), speed (500 files <= 90 s on an M1),
peak memory of the engine + its ollama server, non-loopback connections (must be 0),
injection resistance and the heuristics-only fallback for comparison. Files are only
read; the analysis never moves anything. Uses a throwaway data directory.
"""

import argparse
import csv
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine/src"))
sys.path.insert(0, str(ROOT / "engine/tests"))

from organize_gui.classify import pii  # noqa: E402
from organize_gui.paths import path_key  # noqa: E402
from organize_gui.profiles import valid_folder_name  # noqa: E402
from organize_gui.service import EngineService  # noqa: E402

LSOF = "/usr/sbin/lsof"
PS = "/bin/ps"
LOOPBACK = re.compile(r"^(127\.\d+\.\d+\.\d+|\[::1\]|::1|localhost|\*)(:\d+|:\*)?$")


def adjusted_rand(truth, predicted):
    pairs = Counter(zip(truth, predicted))
    a, b, n = Counter(truth), Counter(predicted), len(truth)
    index = sum(comb(value, 2) for value in pairs.values())
    sum_a = sum(comb(value, 2) for value in a.values())
    sum_b = sum(comb(value, 2) for value in b.values())
    expected = sum_a * sum_b / comb(n, 2) if n > 1 else 0
    maximum = (sum_a + sum_b) / 2
    return 1.0 if maximum == expected else (index - expected) / (maximum - expected)


def edit_effort(truth, predicted):
    """Moves (files outside their cluster's majority) + merges (extra clusters per true group) + splits."""
    members = defaultdict(list)
    for label, cluster in zip(truth, predicted):
        members[cluster].append(label)
    moves = merges = 0
    majority_of = {}
    for cluster, labels in members.items():
        label, count = Counter(labels).most_common(1)[0]
        majority_of[cluster] = label
        moves += len(labels) - count
    per_truth = Counter(majority_of.values())
    merges = sum(count - 1 for count in per_truth.values())
    splits = len(set(truth) - set(majority_of.values()))
    return {"moves": moves, "merges": merges, "splits": splits, "total": moves + merges + splits}


class Monitor(threading.Thread):
    """Samples RSS of this process' children (the ollama server) and their network sockets."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self.peak_child_rss = 0
        self.remote = set()
        self.samples = 0

    def children(self):
        try:
            output = subprocess.run([PS, "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        rows = [line.split() for line in output.splitlines() if len(line.split()) == 3]
        family = {str(os.getpid())}
        changed = True
        while changed:  # all descendants: ollama serve and its model runners
            before = len(family)
            family |= {pid for pid, ppid, _ in rows if ppid in family}
            changed = len(family) != before
        return [(pid, int(rss)) for pid, _, rss in rows if pid in family and pid != str(os.getpid())]

    def run(self):
        while not self.stop_event.is_set():
            kids = self.children()
            self.peak_child_rss = max(self.peak_child_rss, sum(rss for _, rss in kids) * 1024)
            pids = ",".join([str(os.getpid())] + [pid for pid, _ in kids])
            if os.path.exists(LSOF):
                try:
                    output = subprocess.run([LSOF, "-nP", "-a", "-p", pids, "-i"], capture_output=True, text=True, timeout=10).stdout
                except (OSError, subprocess.SubprocessError):
                    output = ""
                for line in output.splitlines()[1:]:
                    parts = line.split()
                    name = parts[8] if len(parts) > 8 else ""
                    endpoints = name.split("->")
                    remote = endpoints[1] if len(endpoints) > 1 else None
                    local = endpoints[0]
                    if (remote and not LOOPBACK.match(remote)) or (not remote and not LOOPBACK.match(local)):
                        self.remote.add("%s(pid %s) %s" % (parts[0], parts[1], name))
            self.samples += 1
            self.stop_event.wait(1.0)


def labels_for(service, proposal, files):
    analysis = service.discovery.analyses[proposal["analysisId"]]
    by_key = {entry["key"]: entry["index"] for entry in analysis.files}
    names = {category["id"]: category["folderName"] for category in proposal["categories"]}  # unique per proposal
    predicted = []
    for path in files:
        index = by_key.get(path_key(Path(path)))
        category = analysis.assign.get(index, ("other", ""))[0] if index is not None else "missing"
        predicted.append(names.get(category, category))
    return predicted


def run_once(service, sources, include, mode):
    started = time.perf_counter()
    scan = service.analysis_scan({"sourceFolders": sources, "includeSubfolders": include})
    proposal = service.analysis_discover(scan["analysisId"], {"mode": mode})
    return proposal, time.perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--truth", help="CSV with columns path,folder (your own grouping)")
    parser.add_argument("--synthetic", type=int, help="generate a synthetic corpus of about N files instead")
    parser.add_argument("--workdir", help="where to put the synthetic corpus and the throwaway data directory")
    parser.add_argument("--fake", action="store_true", help="use the in-process FakeBackend instead of Ollama")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    if not args.truth and not args.synthetic:
        parser.error("use --truth CSV or --synthetic N")

    workdir = Path(args.workdir or tempfile.mkdtemp(prefix="organize-bench-")).absolute()
    workdir.mkdir(parents=True, exist_ok=True)
    data_dir = workdir / "data"
    shutil.rmtree(data_dir, ignore_errors=True)
    injected = []
    if args.synthetic:
        import synthetic_corpus

        per_topic = max(4, int(round(args.synthetic / 9.6)))
        corpus = workdir / "corpus"
        shutil.rmtree(corpus, ignore_errors=True)
        truth_rows = synthetic_corpus.build(corpus, per_topic=per_topic, injections=True)
        injected = [str(path) for path, group in truth_rows if group == "Injected"]
        rows = [(str(path), group) for path, group in truth_rows if group != "Injected"]
        sources, include = [str(corpus)], False
    else:
        with open(args.truth, newline="", encoding="utf-8") as handle:
            rows = [(row["path"], row["folder"]) for row in csv.DictReader(handle)]
        missing = [path for path, _ in rows if not Path(path).is_file()]
        if missing:
            sys.exit("Missing files in the CSV: %s" % ", ".join(missing[:5]))
        sources = sorted({str(Path(os.path.commonpath([path for path, _ in rows])))})
        include = True
    files = [path for path, _ in rows]
    truth = [group for _, group in rows]

    service = EngineService(data_dir)
    service.update_settings({"aiEnabled": True})
    if args.fake:
        from organize_gui.classify.backend import FakeBackend

        fake = FakeBackend()
        service.session_factory = lambda: (fake, None)
    monitor = Monitor()
    monitor.start()
    base_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    first, first_seconds = run_once(service, sources, include, "ai")
    second, second_seconds = run_once(service, sources, include, "ai")
    heuristic, heuristic_seconds = run_once(service, sources, include, "heuristic")
    monitor.stop_event.set()
    monitor.join(timeout=15)
    peak_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS

    predicted = labels_for(service, first, files)
    repeat = labels_for(service, second, files)
    fallback = labels_for(service, heuristic, files)
    sizes = Counter(predicted)
    largest = [label for label, _ in sizes.most_common() if label not in {"other", "missing"}][:5]
    purity = {}
    for label in largest:
        members = [true for true, pred in zip(truth, predicted) if pred == label]
        purity[label] = round(Counter(members).most_common(1)[0][1] / len(members), 3)
    names = [(category["name"], category["folderName"], category.get("description") or "") for category in first["categories"]]
    injection_problems = []
    for name, folder, description in names:
        text = " ".join((name, folder, description))
        if not valid_folder_name(folder) or "/" in text or ".." in text or pii.contains_pii(text) or \
                re.search(r"(?i)ignore|instruction|attacker|rm -rf|ssh|developer mode", text):
            injection_problems.append(text)
    report = {
        "files": len(files) + len(injected),
        "mode": first["mode"], "notice": first["notice"],
        "categories": [{"name": name, "folder": folder, "files": sizes.get(folder, 0)} for name, folder, _ in names],
        "other": sizes.get("other", 0),
        "adjustedRandIndex": round(adjusted_rand(truth, predicted), 3),
        "purityLargest": purity,
        "editEffort": edit_effort(truth, predicted),
        "repeatable": predicted == repeat and [c["name"] for c in first["categories"]] == [c["name"] for c in second["categories"]],
        "secondsFirstRun": round(first_seconds, 1),
        "secondsSecondRun(cached vectors)": round(second_seconds, 1),
        "peakEngineRssMB": round((peak_self - 0) / 1048576, 1),
        "engineRssAtStartMB": round(base_rss / 1048576, 1),
        "peakOllamaRssMB": round(monitor.peak_child_rss / 1048576, 1),
        "networkSamples": monitor.samples,
        "nonLoopbackConnections": sorted(monitor.remote),
        "injectionFiles": len(injected),
        "injectionProblems": injection_problems,
        "heuristicFallback": {"adjustedRandIndex": round(adjusted_rand(truth, fallback), 3),
                              "editEffort": edit_effort(truth, fallback), "seconds": round(heuristic_seconds, 1)},
        "targets": {"adjustedRandIndex>=0.5": None, "purity>=0.8": None, "500 files<=90s": None,
                    "nonLoopback==0": None, "repeatable": None},
    }
    report["targets"] = {
        "adjustedRandIndex>=0.5": report["adjustedRandIndex"] >= 0.5,
        "purity>=0.8": all(value >= 0.8 for value in purity.values()) if purity else False,
        "500 files<=90s": first_seconds <= 90 * max(1, report["files"] / 500),
        "nonLoopback==0": not monitor.remote,
        "repeatable": report["repeatable"],
        "noInjectionProblems": not injection_problems,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print("%-34s %s" % (key, value))
    if args.synthetic:
        print("\nNOTE: synthetic corpus only. Run with --truth on your own labelled files to judge real quality.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
