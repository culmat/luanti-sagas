# Releasing to ContentDB

Releases are GitOps: a tag starts them, CI checks and packages, a maintainer approves, ContentDB imports.

## Once

1. Create each package on ContentDB (`sagas`, `sagas_ruins`, `sagas_antiquity`, optionally `sagas_pack`)
   with the repository URL `https://github.com/culmat/luanti-sagas`, add screenshots from
   `avanti screenshot mods` (full-size PNGs in `mods/screenshots/`) and submit them for review.
2. Store a ContentDB token that is not limited to one package, and hand it to CI:
   ```sh
   avanti secrets setup                        # opens the token page, validates, stores locally
   avanti secrets push culmat/luanti-sagas     # environment "contentdb" with you as required reviewer
   ```

## Each release

```sh
git tag sagas_ruins-v0.1.0 && git push origin sagas_ruins-v0.1.0
```

The Release workflow lints, checks that the packs are rebuilt, attaches `sagas_ruins-0.1.0.zip` to a GitHub
release and then waits. After you approve the `contentdb` deployment, it commits the package folder
`mods/sagas_ruins/` as its own tree, tags it `cdb/sagas_ruins/0.1.0` and asks ContentDB to import that ref.
ContentDB sees exactly the package (dev files are left out by its `.gitattributes`), with the commit linked.

Release the core mod (`sagas-v…`) before or together with packs that need its newer features; packs
declare `depends = landmarks`.

## Why not a ContentDB webhook

ContentDB imports a repository root and binds a webhook to one package, so it cannot tell which of
several packages in this monorepo a tag is for (checked in ContentDB's source, 2026-10-11). The workflow
above needs no upstream change. Native support (a per-package subfolder and tag pattern) is a proposed
upstream feature, tracked in avanti-luanti's [upstream backlog](https://github.com/culmat/avanti-luanti/blob/main/docs/upstream.md).

If git import is unavailable, `avanti cdb release VERSION mods/<pkg> --zip dist/<pkg>-VERSION.zip`
uploads the zip from the GitHub release instead.
