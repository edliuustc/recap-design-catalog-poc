# Synthetic recap design catalog

This repository contains independently authored, public, declarative examples
for validating a versioned recap layout catalog. Catalog files describe safe
ordering, title choices, bounded presentation guidance, and optional synthetic
PNG references. They contain no executable code, user content, meeting content,
credentials, remote asset URLs, or private assets.

The canonical project location is
[recap-design-catalog-poc](https://github.com/edliuustc/recap-design-catalog-poc).

## Validate locally

Use Python 3 with no third-party packages:

```text
python -B -m unittest discover -s tests -p "test_*.py"
python scripts/validate_catalog.py
```

For a pull-request or branch comparison, supply an existing base ref:

```text
python scripts/validate_catalog.py --base-ref origin/main
```

The Python validator is authoritative. The JSON Schema files describe the
closed document shapes, while the validator also enforces cross-file identity,
hash, ordering, immutability, byte, and aggregate constraints.

Tooling limits are 128 KiB and depth 16 for each example, 256 KiB and depth 32
for each schema, 100 repository files, and 8 MiB for all repository files
combined. Catalog runtime limits remain stricter: 4 KiB pointer, 32 KiB
manifest, 64 KiB per design, 192 KiB per PNG, depth 8, and 4 MiB per release.

## Releases

- `v003` is the published `current` release. It retains the v1.1 Summit readiness design
  and strengthens its original layout description: horizontal gate cards with arrows,
  a two-column actions/questions section, restrained Fluent styling, native detail
  disclosure, and no KPI tiles.
- `v002` introduced the v1.1 Summit readiness design
  with required description/prompt/rules and one strict RGB PNG reference.
- `v002` is retained as `previous` for rollback.
- Publication updates both `current.json` and the validator's
  `PUBLISHED_RELEASE` gate in one reviewed change.

The exact LF-only v001 manifest migration from bootstrap commit
`c4213d051263810bbdfa0793d2d8f2192258ed50` is the sole historical
immutability exception. After that migration, release files are immutable. Add
a new release directory and update the pointer rather than editing or deleting
an existing release.

## Temporary governance

All changes to `main` must go through a pull request and require approval from
the repository owner before merging.

The production/team gate requires migration to the SOX Recap team organization
repository and a team CODEOWNERS entry. Independent code-owner approval must be
required. This catalog source must not be enabled before all conditions hold.

## Contribution boundary

Submit only newly authored synthetic JSON, original synthetic PNG references,
and repository tooling. Do not submit Internal Designer content, private source
material, private links, customer or employee data, secrets, screenshots, or
content copied from another repository.
