# ClangIR で PolyBench を回す最短手順

この文書では、`cmake + Ninja` 方針を使わず、`clang/test/CIR/Lowering/basic.cpp` のように `clang` を直接呼び出して PolyBench を扱う方針に統一する。

前提:

- `llvm-project` は `~/toy/oss/llvm-project`
- ClangIR 対応ビルドは `~/toy/oss/llvm-project/build-mlir`
- PolyBench は `~/toy/oss/llvm-test-suite/SingleSource/Benchmarks/Polybench`
- この文書と補助スクリプトは `~/toy/oss/llvm-project/agent-clangir-doc-and-script/polybench` に置く

## 方針

PolyBench の各ベンチは単独の `.c` では完結せず、少なくとも次を一緒に渡す必要がある。

- ベンチ本体の `.c`
- `utilities` への `-I`
- ベンチ固有ヘッダのあるディレクトリへの `-I`

加えて、ClangIR 経由で通すには `-fclangir` を付ける。IR を見たいだけなら `-emit-cir` または `-emit-llvm -S` を足す。

注意:

- この `llvm-test-suite` 版では `polybench.h` の末尾に `polybench.c` の実装が埋め込まれている
- そのため、`utilities/polybench.c` を別 translation unit として追加すると二重定義になる
- 直接 `clang` で呼ぶときは、ベンチ本体だけを渡せばよい

このローカル環境では `-std=c99` の strict C モードだと `posix_memalign` の宣言が見えず、`polybench.h` / `polybench.c` の `xmalloc` 実装で失敗する。したがって、既定の C dialect は `gnu99` にする。

strict C99 を維持したい場合は、代わりに `-D_POSIX_C_SOURCE=200112L` を追加する。

`cmake + Ninja` を使う利点は test-suite の既定フラグを自動で拾うことだが、PolyBench を ClangIR に通すだけなら、直接 `clang` を呼ぶ方が短く、失敗点も見やすい。

## 補助スクリプト

毎回パスとフラグを手で並べるのは面倒なので、`agent-clangir-doc-and-script/polybench/run_clangir_polybench.py` を使う。

このスクリプトは次をやる。

- `utilities/benchmark_list` から benchmark 名を解決する
- `clang` 直接呼び出しのコマンドを組み立てる
- `binary`, `llvm`, `cir` の 3 形態を出力する
- 必要なら build 後にそのまま実行する
- `--time`, `--dump-arrays`, dataset macro, extra flag を付けられる

## スクリプトの基本例

一覧を見る:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py --list
```

`atax` を build して実行する:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py atax --run
```

`atax` を timing 付きで実行する:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py atax --run --time
```

`atax` の LLVM IR を出す:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py atax --emit llvm
```

`atax` の CIR を出す:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py atax --emit cir
```

全 benchmark を build する:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py --all
```

全 benchmark を build し、失敗があっても継続する:

```bash
python3 agent-clangir-doc-and-script/polybench/run_clangir_polybench.py --all --keep-going
```

## よく使うオプション

- `--emit binary|llvm|cir`
  - 実行ファイル、LLVM IR、CIR のどれを出すか
- `--run`
  - `binary` を作ったあとそのまま起動する
- `--time`
  - `-DPOLYBENCH_TIME` を付ける
- `--dump-arrays`
  - `-DPOLYBENCH_DUMP_ARRAYS` を付ける
- `--dataset mini|small|medium|large|extralarge`
  - dataset macro を付ける
- `--disable-fma`
  - `-DFMA_DISABLED=1 -ffp-contract=off` を付ける
- `--std gnu99`
  - 既定値。`posix_memalign` 宣言可視性の都合で、この環境ではこれが無難
- `--extra-cflag FLAG`
  - 手で追加フラグを足す
- `--output-dir DIR`
  - 出力先を変える。既定値は `agent-clangir-doc-and-script/polybench/output`
- `--print-cmd`
  - 実行前に clang コマンドを表示する

## この方針で固定する理由

この文書では、以後 `PolyBench を ClangIR で回す` とは次を意味する。

- `clang` を直接呼ぶ
- `-fclangir` を明示する
- 必要なら `-emit-cir` / `-emit-llvm -S` を付ける
- include path と必要な補助フラグを自前で制御する

## FMA の既定値

補助スクリプトは、現在は既定で FMA を有効にする。

理由:

- `symm.c` に小さい patch を当てたあと、`--all --emit cir --allow-fma --keep-going` は全件通った
- `doitgen` と `heat-3d` は FMA 無効化より有効化の方が通る
- そのため、このローカル環境では `allow-fma` を既定にする方が自然

旧挙動に戻したい場合だけ `--disable-fma` を使う。

つまり `cmake + Ninja` は使わない。最短で見たいのは `ClangIR を通るか`, `どの IR が出るか`, `そのまま実行できるか` の 3 点であり、この用途では直接 `clang` の方が単純。
