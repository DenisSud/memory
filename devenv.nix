{
  pkgs,
  lib,
  ...
}:

# Dev shell for this repo. The project's own tooling stays in charge — hatch
# owns the Python environments (CONTRIBUTING.md), pnpm the TypeScript packages,
# Docker the self-hosted server. Nothing here replaces a project command; it
# only puts the interpreters and tools those commands expect on PATH, so a
# fresh checkout needs no global installs.
let
  # [tool.hatch.envs] in pyproject.toml pins 3.10 / 3.11 / 3.12, matching the CI
  # matrix. nixpkgs dropped python310 (upstream EOL'd it in October 2026), so
  # the shell carries 3.11 and 3.12 only: `make test-py-3_10` cannot run here.
  pythons = [
    pkgs.python311
    pkgs.python312
  ];

  # Hatch envs are plain pip virtualenvs, so the interpreter loads manylinux
  # wheels straight from PyPI. NixOS gives those wheels no default search path
  # for anything the interpreter's own RPATH does not cover: `import mem0`
  # fails on numpy's `libstdc++.so.6` without this. glibc itself resolves
  # through the Nix interpreter, which is why only the extra runtimes need
  # listing here. Add to the list as wheels turn up more of them.
  runtimeLibs = with pkgs; [
    stdenv.cc.cc.lib # libstdc++, libgomp — numpy, faiss, torch
    zlib
    openssl
    libffi
    sqlite
    libxml2
    libxslt
    libpq # psycopg 3 (vector-stores)
  ];
in
{
  # ── Toolchain ───────────────────────────────────────────────────────
  packages = pythons ++ [
    pkgs.hatch # creates and installs the environments in pyproject.toml
    pkgs.uv # ad-hoc interpreter work; hatch keeps using its own installer

    # Lint, format and the pre-commit hooks come from nixpkgs, not the hatch
    # `dev` feature: PyPI's `ruff` is a manylinux executable, and NixOS cannot
    # run those (no /lib64/ld-linux) unless `programs.nix-ld` is enabled in the
    # system config. `hatch run lint` therefore still fails here — the `lint`,
    # `format` and `precommit` scripts below use these. nixpkgs ruff tracks the
    # latest 0.16.x patch while the env pins ==0.16.0; with lint selecting only
    # E4/E7/E9/F and the formatter in its stable style, the difference does not
    # show up in this repo's diffs.
    pkgs.ruff
    pkgs.isort
    pkgs.pre-commit

    pkgs.nodejs_22 # mem0-ts, cli/node, integrations (>=18)
    pkgs.pnpm_10 # packageManager: pnpm@10.x

    pkgs.git
    pkgs.gnumake # the repo's Makefile
    pkgs.jq
    pkgs.curl
    # Docker comes from the system: the daemon it needs is not provided here.
  ];

  # Unbuffered output and no pip nagging keeps logs close to CI.
  env.PYTHONUNBUFFERED = "1";
  env.PIP_DISABLE_PIP_VERSION_CHECK = "1";

  # ── Commands ────────────────────────────────────────────────────────
  # `devenv info` lists these. Names avoid shell builtins and coreutils
  # (`test`, `install`, `sort`), which PATH cannot shadow.
  scripts = {
    setup = {
      description = "Create the Python 3.11 dev env (hatch) and install git hooks";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        hatch env create dev_py_3_11
        pre-commit install
      '';
    };

    check = {
      description = "pytest tests/ in the 3.11 dev env; extra args are forwarded";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec hatch run dev_py_3_11:pytest tests/ "$@"
      '';
    };

    check-systemone = {
      description = "The System One gate tests only (PI-FORK.md); args forwarded";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec hatch run dev_py_3_11:pytest tests/systemone/ "$@"
      '';
    };

    check-3_12 = {
      description = "pytest tests/ in the 3.12 dev env (second CI version)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec hatch run dev_py_3_12:pytest tests/ "$@"
      '';
    };

    lint = {
      description = "ruff check (nixpkgs ruff: the PyPI binary cannot run here)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec ruff check "$@"
      '';
    };

    format = {
      description = "ruff format (nixpkgs ruff: the PyPI binary cannot run here)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec ruff format "$@"
      '';
    };

    sort-imports = {
      description = "isort mem0/ (profile black, as make sort)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec isort mem0/ "$@"
      '';
    };

    precommit = {
      description = "Run all system hooks (git commit runs them too)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT"
        exec pre-commit run --all-files "$@"
      '';
    };

    ts-install = {
      description = "pnpm install for the TypeScript SDK";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT/mem0-ts"
        exec pnpm install --frozen-lockfile "$@"
      '';
    };

    ts-check = {
      description = "TypeScript SDK unit tests (jest)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT/mem0-ts"
        exec pnpm test "$@"
      '';
    };

    server-up = {
      description = "Start the self-hosted dev stack (FastAPI + pgvector + Neo4j)";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT/server"
        exec docker compose up "$@"
      '';
    };

    server-down = {
      description = "Stop the self-hosted dev stack";
      exec = ''
        set -euo pipefail
        cd "$DEVENV_ROOT/server"
        exec docker compose down "$@"
      '';
    };

    doctor = {
      description = "Show the interpreters and tools this shell resolved";
      exec = ''
        set -u
        echo "python3.11  $(python3.11 --version)"
        echo "python3.12  $(python3.12 --version)"
        echo "hatch       $(hatch --version)"
        echo "uv          $(uv --version)"
        echo "ruff        $(ruff --version)   (hatch dev env pins 0.16.0)"
        echo "node        $(node --version)"
        echo "pnpm        $(pnpm --version)"
        docker version --format 'docker      {{.Client.Version}} / server {{.Server.Version}}' 2>/dev/null \
          || echo "docker      unreachable — needed by server-up and deploy/"
      '';
    };
  };

  # ── `devenv shell` greeting ─────────────────────────────────────────
  # Distinguish this shell from the system one and point at the long-form
  # commands it does not wrap (the whole Makefile and hatch CLI are available).
  enterShell = ''
    # Appended, not assigned: the shell's own entries stay in front.
    export LD_LIBRARY_PATH="${lib.makeLibraryPath runtimeLibs}:''${LD_LIBRARY_PATH:-}"

    echo "mem0 devenv — python $(python3.11 --version 2>&1 | cut -d' ' -f2) / $(python3.12 --version 2>&1 | cut -d' ' -f2), node $(node --version), pnpm $(pnpm --version)"
    echo "commands: setup · check · check-systemone · check-3_12 · lint · format · sort-imports"
    echo "          precommit · ts-install · ts-check · server-up · server-down · doctor   (devenv info)"
    echo "python envs: hatch shell dev_py_3_11  (created by 'setup')"
  '';

  # `devenv test` — stays cheap: proves the toolchain resolves without
  # triggering a multi-minute hatch env install. Run `check` for the suite.
  enterTest = ''
    set -euo pipefail
    cd "$DEVENV_ROOT"
    python3.11 --version
    python3.12 --version
    hatch --version
    hatch env show > /dev/null
    node --version
    pnpm --version
    echo "devenv toolchain ok"
  '';

  # Full option reference: https://devenv.sh/reference/options/
}
