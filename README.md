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
python -B -m unittest discover -s tests
python scripts/validate_catalog.py
```

For a pull-request or branch comparison, supply an existing base ref:

```text
python scripts/validate_catalog.py --base-ref origin/main
```

Published release files are immutable. Add a new release directory and update
the pointer rather than editing or deleting an existing release.

## Contribution boundary

Submit only newly authored synthetic JSON and repository tooling. Do not submit
Internal Designer content, private source material, private links, customer or
employee data, secrets, screenshots, generated assets, or content copied from
another repository.
