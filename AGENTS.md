# Agent guide: Graphite

Graphite is GrapheneOS (pinned release tag) + patches in `patches/`, built for the Pixel 8 Pro
(`husky`). Read `README.md` for the full picture. This file covers the rules and the
standard tasks.

## Rules

1. **The source tree `src/` is disposable.** Every change that should last must end up as a
   patch in `patches/<id>/`. `build.sh` resets patched projects before each build.
2. **Never edit `PINNED_TAG` in `build.sh` by hand.** Use `./update.sh apply|rollback`.
3. **Don't start full OS builds (`./build.sh`, `./dev.sh build` without modules) unless the user
   asked.** They take hours on this machine (15 GiB RAM). Module builds (`./dev.sh build <module>`)
   are fine once the emulator/device out dir exists.
4. Keep patches small and single-purpose, and keep `patch.toml` `description` / `skip_impact`
   accurate, because future fixes depend on them. New features get a new patch id, not a
   bigger existing patch.
5. Don't modify GrapheneOS security features unless the patch is explicitly about that, and
   say so in its description.
6. Python tooling uses only the standard library. Keep it that way.

## Commands

```bash
tools/patchctl list                       # patches + state
tools/patchctl info <id>
./update.sh status | validate [TAG] [--only id,id]
tools/patchctl fix start|continue|finish|abort <id> --tag TAG
tools/patchctl refresh <id> --tag TAG     # for NEEDS_REFRESH (3-way applies cleanly)
./build.sh --only patch [--force]         # re-apply all patches to src/
./dev.sh build <module...>                # incremental module build (emulator target)
./dev.sh quick <module...>                # build + push + restart in running emulator
./dev.sh shell "<cmd>"                    # run a command in the AOSP build env
```

Exit codes of `patchctl validate`: 0 all good · 3 only optional patches broken · 2 required patch
or sanity check broken · 1 tool error.

## Task: fix a broken patch after an update validation

Input: `reports/validate-<TAG>/FIX_PROMPT.md` and `failures/<id>.md`.

1. Read `failures/<id>.md`. It contains the intent, the failing hunks, the new code, the
   3-way conflict, and upstream's diff of the file.
2. `tools/patchctl fix start <id> --tag <TAG>`: this creates worktrees under `work/fix-<id>/<project>`
   at the new revision, with earlier patches applied and this patch applied via `git am --3way`.
3. Resolve the conflicts in the worktree, keeping upstream's new logic and re-applying the
   patch's intent. Then `git -C work/fix-<id>/<project> add -A && tools/patchctl fix continue <id>`.
   Repeat until it reports "all pieces applied".
4. Optional, but do it for non-trivial Java/C++ changes when an out dir exists: compile-check by
   copying the change into `src/` and running `./dev.sh build <module>`.
5. `tools/patchctl fix finish <id>` writes `patches/<id>/<file>.patch`.
6. `./update.sh validate <TAG> --only <id>` must print `OK`. Then run a full `./update.sh validate <TAG>`
   (later patches may depend on this one).
7. If upstream now implements the feature itself, don't force the patch. Report it so the user can
   delete the patch or list it in `patches/skip.list`.

Fix broken patches in id order. If the change can't be ported faithfully, explain why and stop.
Don't silently drop functionality.

## Task: add a feature as a new patch

1. `tools/patchctl new NNNN-name --title "..." [--required]`. Pick NNNN after its dependencies.
   Number bands: 0001-0099 build/branding, 0100-0299 core/root, 0300-0599 features,
   0600-0899 apps/UI, 0900+ experiments.
2. Fill in `patch.toml`: description (what + why), `required`, `skip_impact`, `depends`.
3. Make the change in `src/<project>` as git commits (`git -C src/<project> commit`).
4. Test: `./dev.sh build <module>`, then `./dev.sh quick <module>` in the emulator if it is running.
5. `tools/patchctl export <id> --project <project> --new` for each project.
6. `./build.sh --only patch` must apply cleanly. `./update.sh validate` shows how it fares on the latest tag.

New repositories (apps, prebuilts) go into `manifests/<name>.xml` (a repo local manifest) and
are pulled in by `./build.sh` (sync step).

## Where things are

* `tools/graphite/patchctl.py`: the patch engine (apply/reset/validate/report/fix/export).
* `tools/lib/common.sh`: shared shell helpers (config, pin, jobs, build env).
* `graphite.conf`: device, variant, jobs, out dirs. `graphite.local.conf` (untracked) overrides it.
* `src/vendor/adevtool`: GrapheneOS' vendor/device generator. Device makefiles for Pixels live in
  `src/vendor/adevtool/config/mk/google_devices/` (Google no longer publishes device trees).
* Device out: `src/out/`. Emulator out: `src/out-emu/` (lunch `sdk_phone64_x86_64-cur-userdebug`).
* Logs: `logs/`. Reports: `reports/`. Snapshots and caches: `state/`.
