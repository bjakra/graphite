# Graphite patches

Each directory `NNNN-short-name/` is one logical patch (one feature/fix), applied in
lexical order. The number defines the order; dependencies must have lower numbers.

```
patches/
  0001-graphite-identity/
    patch.toml          metadata (below)
    build_make.patch    changes to project build/make (git format-patch output)
  skip.list             ids excluded from builds, one per line: "<id>  # reason"
```

## patch.toml

```toml
title = "Short title"
description = """
What the patch does and WHY. This text is shown when the patch fails during a
build and is the main input for whoever (human or AI) has to port it to a new
GrapheneOS version. Mention the behaviour, not the lines.
"""
required = true        # false = build may continue without it (asks / --skip-optional)
skip_impact = "What the user loses if it is skipped."
category = "root"      # free text: branding, root, ui, privacy, build, ...
depends = []           # ids of patches that must be applied first
enabled = true         # false = never applied
notes = "Porting hints: where the hook lives, upstream discussions, test steps."

[[change]]             # one per patched file; several may target the same project
project = "frameworks/base"          # path in src/ (as in the repo manifest)
file = "frameworks_base.patch"       # in this directory
```

## Patch files

* Preferably `git format-patch` output (may contain several commits); plain unified
  diffs with `a/` `b/` prefixes work too.
* Paths are relative to the **project** root (e.g. `services/core/...` for
  frameworks/base), not to `src/`.
* Don't hand-edit hunks. Use `tools/patchctl export` / `tools/patchctl fix`.

## Workflow

```bash
tools/patchctl new 0300-feature --title "..." [--required]
# commit in src/<project> (any number of commits)
tools/patchctl export 0300-feature --project <project> --new
tools/patchctl list | info <id>
./build.sh --only patch            # apply everything to src/
./update.sh validate               # will it survive the next GrapheneOS release?
```

`--new` takes commits without a `Graphite-Patch:` trailer. After a `./build.sh --only patch`
the commits in `src/` carry the trailer, and further commits for the same patch are exported
with `tools/patchctl export <id> --project <p> --new` (it rewrites the whole patch file from all
commits carrying the id + new ones).

Projects that need *new* repositories (e.g. a root manager app) get a local manifest in
`manifests/` instead of a giant patch.
