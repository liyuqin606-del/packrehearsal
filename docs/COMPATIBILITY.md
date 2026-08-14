# Compatibility policy

PackRehearsal follows Semantic Versioning from 1.0.0 onward.

## Stable throughout 1.x

- documented CLI command names, required arguments, and exit-code meanings;
- report, baseline, and receipt schema version 1;
- published rule IDs and finding fingerprint format;
- top-level Python names listed in `packrehearsal.__all__`;
- the default static-scan boundary: no project-code execution, network access,
  or archive extraction.

Compatible 1.x releases may add optional CLI flags, optional Python parameters,
new rules, new ecosystems, and new output formats. New rules can add findings;
use severity thresholds and reviewed baselines rather than assuming a fixed
finding count.

## Not a compatibility promise

- exact human-readable wording, colors, or finding order;
- modules and names below `packrehearsal` that are not exported at the package
  top level;
- trusted build-tool output and registry behavior outside PackRehearsal;
- performance within documented hard resource limits.

## Breaking changes

Removing or renaming a stable command, exit code, schema field, rule ID, or
top-level Python export requires a new major version. A security fix may reject
input that an older release accepted when accepting it would violate a stated
safety boundary; such changes are documented in the changelog.
