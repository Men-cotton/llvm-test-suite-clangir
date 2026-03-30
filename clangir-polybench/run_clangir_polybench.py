#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path


HOME = Path.home()
DEFAULT_LLVM_PROJECT = HOME / "toy/oss/llvm-project"
DEFAULT_CLANG = DEFAULT_LLVM_PROJECT / "build-mlir/bin/clang"
DEFAULT_POLYBENCH_ROOT = (
    HOME / "toy/oss/llvm-test-suite/SingleSource/Benchmarks/Polybench"
)
DEFAULT_OUTPUT_DIR = DEFAULT_LLVM_PROJECT / "agent-clangir-doc-and-script/polybench/output"

DATASET_MACROS = {
    "mini": "MINI_DATASET",
    "small": "SMALL_DATASET",
    "medium": "MEDIUM_DATASET",
    "large": "LARGE_DATASET",
    "extralarge": "EXTRALARGE_DATASET",
}


def load_benchmarks(polybench_root: Path) -> dict[str, Path]:
    benchmark_list = polybench_root / "utilities/benchmark_list"
    if not benchmark_list.is_file():
        raise FileNotFoundError(f"benchmark list not found: {benchmark_list}")

    benchmarks: dict[str, Path] = {}
    for line in benchmark_list.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("./"):
            line = line[2:]
        source = polybench_root / line
        name = source.stem
        benchmarks[name] = source
    return benchmarks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Direct clang driver for PolyBench with ClangIR."
    )
    parser.add_argument("benchmarks", nargs="*", help="Benchmark names such as atax, gemm, 2mm")
    parser.add_argument("--all", action="store_true", help="Select all benchmarks")
    parser.add_argument("--list", action="store_true", help="List available benchmarks")
    parser.add_argument(
        "--emit",
        choices=("binary", "llvm", "cir"),
        default="binary",
        help="Output kind",
    )
    parser.add_argument("--run", action="store_true", help="Run after building binary output")
    parser.add_argument("--time", action="store_true", help="Define POLYBENCH_TIME")
    parser.add_argument(
        "--dump-arrays", action="store_true", help="Define POLYBENCH_DUMP_ARRAYS"
    )
    parser.add_argument(
        "--dataset",
        choices=tuple(DATASET_MACROS),
        help="Select a PolyBench dataset macro",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory",
    )
    parser.add_argument(
        "--clang",
        type=Path,
        default=DEFAULT_CLANG,
        help="Path to clang built with ClangIR",
    )
    parser.add_argument(
        "--polybench-root",
        type=Path,
        default=DEFAULT_POLYBENCH_ROOT,
        help="Path to SingleSource/Benchmarks/Polybench",
    )
    parser.add_argument(
        "--opt-level",
        default="3",
        help="Optimization level without the leading dash, default: 3",
    )
    parser.add_argument(
        "--std",
        default="gnu99",
        help="C language standard passed as -std=..., default: gnu99",
    )
    parser.add_argument(
        "--extra-cflag",
        action="append",
        default=[],
        help="Extra compiler flag, may be repeated",
    )
    parser.add_argument(
        "--allow-fma",
        action="store_true",
        help="Compatibility no-op. FMA is enabled by default.",
    )
    parser.add_argument(
        "--disable-fma",
        action="store_true",
        help="Add -ffp-contract=off and -DFMA_DISABLED=1",
    )
    parser.add_argument(
        "--print-cmd", action="store_true", help="Print the clang command before execution"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands but do not execute them",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue even if a benchmark fails",
    )
    return parser.parse_args()


def select_benchmarks(args: argparse.Namespace, benchmarks: dict[str, Path]) -> list[tuple[str, Path]]:
    if args.list:
        for name in sorted(benchmarks):
            print(name)
        return []

    if args.all:
        selected = sorted(benchmarks.items())
    else:
        if not args.benchmarks:
            raise SystemExit("specify benchmark names, --all, or --list")
        missing = [name for name in args.benchmarks if name not in benchmarks]
        if missing:
            raise SystemExit(f"unknown benchmark(s): {', '.join(missing)}")
        selected = [(name, benchmarks[name]) for name in args.benchmarks]

    return selected


def common_flags(args: argparse.Namespace, bench_dir: Path) -> list[str]:
    flags = [
        f"-O{args.opt_level}",
        f"-std={args.std}",
        "-fclangir",
        "-Wno-error=incompatible-pointer-types",
        "-I",
        str(args.polybench_root / "utilities"),
        "-I",
        str(bench_dir),
        "-DFP_ABSTOLERANCE=1e-5",
    ]

    if args.disable_fma:
        flags.extend(["-DFMA_DISABLED=1", "-ffp-contract=off"])
    if args.time:
        flags.append("-DPOLYBENCH_TIME")
    if args.dump_arrays:
        flags.append("-DPOLYBENCH_DUMP_ARRAYS")
    if args.dataset:
        flags.append(f"-D{DATASET_MACROS[args.dataset]}")

    flags.extend(args.extra_cflag)
    return flags


def build_command(
    args: argparse.Namespace, name: str, source: Path
) -> tuple[list[str], Path]:
    bench_dir = source.parent
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.emit == "binary":
        output = args.output_dir / name
        cmd = [
            str(args.clang),
            *common_flags(args, bench_dir),
            str(source),
            "-lm",
            "-o",
            str(output),
        ]
    elif args.emit == "llvm":
        output = args.output_dir / f"{name}.ll"
        cmd = [
            str(args.clang),
            *common_flags(args, bench_dir),
            "-emit-llvm",
            "-S",
            str(source),
            "-o",
            str(output),
        ]
    else:
        output = args.output_dir / f"{name}.cir"
        cmd = [
            str(args.clang),
            *common_flags(args, bench_dir),
            "-emit-cir",
            str(source),
            "-o",
            str(output),
        ]

    return cmd, output


def run_command(cmd: list[str], print_cmd: bool, dry_run: bool) -> int:
    if print_cmd or dry_run:
        print(" ".join(shlex.quote(part) for part in cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd).returncode


def run_binary(binary: Path, print_cmd: bool, dry_run: bool) -> int:
    cmd = [str(binary)]
    if print_cmd or dry_run:
        print(" ".join(shlex.quote(part) for part in cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd).returncode


def main() -> int:
    args = parse_args()

    if not args.clang.is_file():
        raise SystemExit(f"clang not found: {args.clang}")
    if not args.polybench_root.is_dir():
        raise SystemExit(f"polybench root not found: {args.polybench_root}")
    if args.run and args.emit != "binary":
        raise SystemExit("--run is only valid with --emit binary")

    benchmarks = load_benchmarks(args.polybench_root)
    selected = select_benchmarks(args, benchmarks)
    if args.list:
        return 0

    failures: list[str] = []

    for name, source in selected:
        cmd, output = build_command(args, name, source)
        rc = run_command(cmd, args.print_cmd, args.dry_run)
        if rc != 0:
            failures.append(f"{name}: compile failed with exit code {rc}")
            if not args.keep_going:
                break
            continue

        if args.run:
            rc = run_binary(output, args.print_cmd, args.dry_run)
            if rc != 0:
                failures.append(f"{name}: run failed with exit code {rc}")
                if not args.keep_going:
                    break

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
