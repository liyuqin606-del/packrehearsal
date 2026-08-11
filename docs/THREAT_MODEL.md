# Threat model

## Assets

- maintainer workstation and CI credentials;
- repository integrity;
- confidentiality of untracked files and package contents;
- correctness of findings and release receipts;
- bounded CPU, memory, disk, and wall-clock use.

## Inputs

Static mode treats manifests, repository paths, configuration, and artifact
archives as untrusted. Trusted rehearsal treats the selected revision as trusted
code but still treats its output archive as untrusted data.

## Defenses in static mode

- no subprocesses;
- no network clients;
- no archive extraction;
- resolve and validate every user path;
- reject absolute archive paths, `..`, NUL bytes, device nodes, and links;
- cap archive bytes, member count, member bytes, total expanded bytes, and
  compression ratio;
- hash member content through bounded streams;
- do not log environment variable values;
- atomic report writes and refusal to replace symlinks;
- deterministic parsing and explicit malformed-input findings.

The bundled GitHub Action also ignores repository configuration so an
untrusted pull request cannot raise archive limits, disable rules, or broaden
the scan. It starts Python in isolated mode before inserting the action's own
source path, preventing repository files from shadowing imported modules. A
baseline can suppress findings, so the action rejects baseline input on pull-
request events. Non-PR baselines must still be protected and reviewed.

## Trusted rehearsal boundary

Package build tools run project-controlled code even when flags such as
`--ignore-scripts` reduce common lifecycle hooks. A build backend, compiler,
configuration file, or toolchain wrapper can execute arbitrary code.

Therefore trusted rehearsal:

1. requires an explicit CLI flag;
2. displays the command before running it;
3. uses a temporary output location and restricted environment;
4. starts one shared deadline before source preflight/copy and kills the process
   group where supported when time or captured-output limits are exceeded;
5. disables network by policy where the selected tool supports it;
6. is forbidden for unreviewed fork pull requests and `pull_request_target`;
7. makes no claim of operating-system sandboxing.

The disposable source copy also has built-in, non-configurable ceilings for
entry count, individual-file size, total logical bytes, and allocated bytes.
Each subprocess stream retains at most 1 MiB; excess output terminates the
process group instead of consuming unbounded temporary disk.

## Residual risks

- malicious parsers in the Python standard library or runtime;
- decompression work below configured limits can still be expensive;
- unusual archive encodings may display paths differently in downstream tools;
- a trusted build has the user's privileges;
- rules can have false negatives or false positives;
- a receipt is unsigned, self-consistent evidence that can bind separately
  retained artifact bytes; it proves neither authorship nor package safety.

Security reports that demonstrate a boundary bypass are handled under
[`SECURITY.md`](../SECURITY.md).
