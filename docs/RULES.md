# Rule catalog

The executable registry exposed by `packrehearsal rules --format json` is the
source of truth. This document explains the rule families and severity policy.

## Severity

- **critical:** likely credential disclosure or a direct unsafe archive boundary;
- **high:** candidate package is likely unusable or leaks sensitive material;
- **medium:** material metadata or release inconsistency;
- **low:** compatibility or maintenance risk with a clear remediation;
- **info:** evidence useful to a maintainer but not a release gate.

## Common artifact rules

- required README and license material reaches the final package;
- no configured sensitive path reaches the artifact;
- individual and aggregate file sizes remain reviewable;
- archive paths are portable and safe;
- declared package version matches artifact metadata;
- internal monorepo dependency ranges accept the versions being released.

## npm

- `main`, `module`, `types`, `typings`, `browser`, and `bin` targets are present;
- package name and version are publishable values;
- workspace dependency protocols resolve to intended sibling packages;
- private workspaces are reported but are not treated as publish candidates.

## Python

- project name and version are present in `[project]` or supported metadata;
- wheel metadata agrees with the manifest;
- wheel and sdist metadata agree with each other on name, version,
  `Requires-Python`, dependencies, license expression, and extras;
- console-script modules are included;
- readme and license references exist in source;
- sdists retain referenced files, while wheels may embed the README description
  in `METADATA` and relocate license files under `.dist-info/licenses/`.

## Rust

- crate name, version, readme, and license metadata are present;
- declared `include` paths do not omit required metadata;
- path dependencies have publishable version constraints;
- workspace-inherited package fields resolve deterministically.

## False positives

Rules must document a concrete exception before they can block a release by
default. Use a severity override for project-specific policy, or baseline an
existing fingerprint. Disabling a rule should be a last resort and should be
reviewed like a code change.
