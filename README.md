# Synthetic recap design catalog

This repository contains independently authored, public, declarative examples
for validating a versioned recap layout catalog. Catalog files describe safe
ordering and title choices; they contain no executable code, prompts, user
content, meeting content, credentials, or private assets.

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
for each schema, 100 repository files, and 2 MiB for all repository files
combined. Catalog runtime limits remain stricter: 4 KiB pointer, 32 KiB
manifest, 64 KiB per design, depth 8, and 512 KiB per release.

Published release files are immutable. Add a new release directory and update
the pointer rather than editing or deleting an existing release.

## Temporary governance

The personal-account POC protects `main` with pull requests and the required
validation workflow. It temporarily requires zero approvals and has no
CODEOWNERS file until migration to an organization-owned repository.

## Contribution boundary

Submit only newly authored synthetic JSON and repository tooling. Do not submit
Internal Designer content, private source material, private links, customer or
employee data, secrets, screenshots, generated assets, or content copied from
another repository.
