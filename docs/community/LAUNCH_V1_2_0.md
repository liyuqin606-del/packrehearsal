# PackRehearsal 1.2.0 community launch kit

Status: publish only after the v1.2.0 GitHub release, PyPI page, live demo,
checksums, and clean-install verification are public.

This kit borrows the structure—not the wording—of effective developer-tool
launch posts: start with a recognizable failure, show the exact mechanism,
make the project immediately testable, state limits, and ask one specific
question. Never request coordinated votes or copy the same body across
communities.

## Verified facts allowed in every post

- Apache-2.0 and published on PyPI.
- Python 3.11+; zero runtime dependencies.
- Static scan does not execute project code, extract archives, contact a
  registry, or call an OpenAI API.
- `python.artifact-set-mismatch` compares wheel and sdist name, version,
  `Requires-Python`, dependencies, license metadata, and extras.
- The bundled demo is a real `report-v1` emitted by the CLI from two synthetic
  archives. It disagrees on `Requires-Python`, `Requires-Dist`, and license.
- The demo finding is HIGH and can be converted into a deterministic,
  human-reviewed `codex-task-v1` brief.
- Python suite: 298 passed, one Windows-only junction test skipped locally.
  WebUI contract suite: six passed. Sites worker suite: four passed.
- The project does not claim adoption, accuracy, time saved, endorsement by
  OpenAI, or vulnerability detection.

Canonical links:

- Repository: https://github.com/liyuqin606-del/packrehearsal
- Try the local-only WebUI: https://packrehearsal-release-gate.lylylyqlyq.chatgpt.site/
- PyPI: https://pypi.org/project/packrehearsal/
- Release: https://github.com/liyuqin606-del/packrehearsal/releases/tag/v1.2.0
- Rule catalog: https://github.com/liyuqin606-del/packrehearsal/blob/v1.2.0/docs/RULES.md
- Codex workflow: https://github.com/liyuqin606-del/packrehearsal/blob/v1.2.0/docs/CODEX_WORKFLOW.md

## 1. Hacker News — Show HN

Title:

> Show HN: PackRehearsal – catch wheel/sdist drift before PyPI

Submit the repository URL. Suggested first comment:

> I built this after focusing on a release failure that ordinary source checks
> miss: two artifacts produced for one Python tag can describe different
> install contracts.
>
> In the bundled fixture the wheel says Python >=3.11, alpha>=1, MIT; the sdist
> says Python >=3.12, alpha>=2, Apache-2.0. PackRehearsal reads the archives
> without extracting or executing them and emits one deterministic HIGH
> finding with the differing fields and both artifact hashes.
>
> Try it without installing anything: open the WebUI and click “Load drift
> demo”. Or run:
>
> `pip install packrehearsal==1.2.0`
>
> `packrehearsal scan . --artifact dist/pkg.whl --artifact dist/pkg.tar.gz`
>
> The same evidence can become a bounded Codex repair brief, but the scanner—not
> the model—defines the finding and verification command. Human review remains
> required.
>
> Current limit: this comparison is metadata-focused. It does not prove runtime
> behavior or package safety. Which additional cross-artifact field would catch
> a failure you have actually shipped?

HN rule: do not ask anyone to upvote. Be present to answer technical questions.

## 2. Reddit — r/Python

Title:

> I built a static gate for the “sdist is fine, wheel is different” class of release bugs

Body:

> A Python repository can be green while the files uploaded for one release
> disagree with each other. That is especially awkward because users install
> the artifacts, not the source tree we reviewed.
>
> PackRehearsal 1.2.0 now accepts a wheel and sdist in the same scan and compares:
>
> - distribution name and version
> - `Requires-Python`
> - `Requires-Dist`
> - license metadata
> - provided extras
>
> The included demo intentionally makes the wheel and sdist disagree. The CLI
> returns one HIGH finding with field-level evidence; the WebUI renders the
> same signed-by-content report locally and can export a bounded Codex task.
>
> Quick try: `pip install packrehearsal==1.2.0`
>
> Then:
>
> `packrehearsal scan . --artifact dist/pkg.whl --artifact dist/pkg.tar.gz`
>
> No project code is executed on the static path, archives are not extracted,
> and there is no API key or runtime dependency. This is not a sandbox,
> vulnerability scanner, or proof that installation succeeds.
>
> Live demo: https://packrehearsal-release-gate.lylylyqlyq.chatgpt.site/
>
> Source: https://github.com/liyuqin606-del/packrehearsal
>
> I would particularly value examples of real wheel/sdist drift that this field
> set would still miss.

## 3. Discussions on Python.org — Packaging

Title:

> Feedback requested: static wheel/sdist metadata parity gate

Body:

> I am looking for packaging-maintainer feedback on a deliberately narrow rule
> added to PackRehearsal 1.2.0.
>
> When a scan receives at least one wheel and one sdist associated with the same
> project, `python.artifact-set-mismatch` compares normalized name/version plus
> `Requires-Python`, `Requires-Dist`, license metadata, and `Provides-Extra`.
> A difference is a HIGH release finding. All evidence comes from bounded,
> non-extracting archive inspection.
>
> The immediate motivation is the familiar situation where an sdist contains
> or declares one thing while the wheel users install contains or declares
> another. The rule intentionally does not infer runtime equivalence.
>
> Reproducer and demo:
> https://github.com/liyuqin606-del/packrehearsal/releases/tag/v1.2.0
>
> Rule behavior:
> https://github.com/liyuqin606-del/packrehearsal/blob/v1.2.0/docs/RULES.md
>
> I would appreciate review of two choices: should requirement strings be
> compared after deeper PEP 508 semantic normalization, and which metadata
> differences should be warnings rather than release blockers?

## 4. V2EX — 分享创造

标题：

> 做了一个发布前门禁：同一版本的 wheel 和 sdist 说法不一致就直接拦截

正文：

> 最近把一个很具体的 Python 发包坑做成了工具：仓库和 CI 都是绿的，
> 但最后上传到 PyPI 的 wheel / sdist 可能不是同一份“安装契约”。
>
> PackRehearsal 1.2.0 会同时读取两个制品，比较包名、版本、Python 版本
> 约束、依赖、许可证和 extras。演示里 wheel 是 `>=3.11 + alpha>=1 + MIT`，
> sdist 则是 `>=3.12 + alpha>=2 + Apache-2.0`，结果会产生一个 HIGH 阻断项。
>
> 默认扫描不解压、不执行项目代码、不联网，也不调用模型。检查结果可以
> 转成一个边界明确的 Codex 修复任务，但是否修改、合并和发布仍由维护者决定。
>
> 在线直接体验：
> https://packrehearsal-release-gate.lylylyqlyq.chatgpt.site/
>
> 源码：
> https://github.com/liyuqin606-del/packrehearsal
>
> PyPI：`pip install packrehearsal==1.2.0`
>
> 目前只比较静态发布证据，不保证运行时正确，也不是安全扫描器。想请教做过
> Python 发包的朋友：你实际遇到过哪些 wheel/sdist 不一致，但上面这些字段还
> 抓不到？

## 5. DEV Community — technical article

Title:

> Your wheel and sdist can disagree even when CI is green

Opening:

> We review repositories, but users install archives. That gap matters when the
> wheel and source distribution built for one tag declare different Python
> versions, dependencies, extras, or licensing metadata.

Sections:

1. A concrete mismatch: show the three differing fields from the bundled demo.
2. Why source-only checks do not answer the artifact question.
3. The two-artifact command and deterministic HIGH finding.
4. Turning evidence into a bounded Codex task without letting the model invent
   the release problem.
5. Honest limits: metadata parity is not runtime validation or security proof.
6. One feedback request: missing cross-artifact evidence.

Sources to cite:

- https://github.com/pypa/setuptools/discussions/3748
- https://github.com/pypa/setuptools/issues/3184
- https://pypackaging-native.github.io/key-issues/unexpected_fromsource_builds/

Disclosure:

> This article was drafted with Codex assistance. Every command, count, and
> project claim was checked against the linked public release and repository.

## 6. OpenAI Developer Community — Codex update

Title:

> PackRehearsal 1.2.0: one artifact mismatch, one bounded Codex task

Body:

> I added a cross-artifact gate after narrowing the maintainer problem further:
> before Codex proposes a packaging fix, a deterministic tool should establish
> whether the wheel and sdist actually disagree.
>
> Version 1.2.0 compares name, version, `Requires-Python`, dependencies, license
> metadata, and extras across both artifacts. The bundled example produces one
> HIGH finding for three exact fields. The WebUI then turns only that fingerprint
> into `codex-task-v1`, carrying both SHA-256 hashes, the remediation, and the
> rescan command.
>
> Try the complete flow without uploading a report: open the site and click
> “Load drift demo”.
>
> https://packrehearsal-release-gate.lylylyqlyq.chatgpt.site/
>
> The model still does not decide the evidence, weaken the rule, merge, or
> release. I would value feedback on the stop condition: what else must be in
> the task before you would let Codex repair this class of packaging drift?

## 7. X thread — ready when an authenticated account is available

1. `CI can be green while the wheel and sdist for one Python release describe different installs. PackRehearsal 1.2.0 now blocks that drift before PyPI.`
2. `The real demo: wheel => Python >=3.11, alpha>=1, MIT. sdist => Python >=3.12, alpha>=2, Apache-2.0. One HIGH finding, field-level evidence, both SHA-256 hashes.`
3. `Static path: no project-code execution, no extraction, no registry call, no model call, zero runtime dependencies.`
4. `That deterministic finding can become a bounded Codex task. The scanner defines scope; a human still reviews, merges, and releases.`
5. `Try it in one click: https://packrehearsal-release-gate.lylylyqlyq.chatgpt.site/  Source: https://github.com/liyuqin606-del/packrehearsal`

## 8. LinkedIn — ready when a connected account is available

> A release pipeline taught me to focus less on whether a repository is green
> and more on whether the actual artifacts agree.
>
> PackRehearsal 1.2.0 adds a static wheel/sdist parity gate for Python packages.
> It compares identity, compatibility, dependencies, license metadata, and
> extras, then records exact evidence before any Codex repair is requested.
>
> The important boundary is deliberate: AI can help edit, but it should not
> invent what failed or silently decide that a release is safe.
>
> The project is Apache-2.0, available on PyPI, and the demo runs locally in the
> browser without uploading a report.
>
> Live demo: https://packrehearsal-release-gate.lylylyqlyq.chatgpt.site/
> Repository: https://github.com/liyuqin606-del/packrehearsal

## Publication ledger

Record only posts that are actually live.

| Platform | URL | Published at (UTC) | Notes |
|---|---|---|---|
| GitHub Discussion | pending | pending | Release announcement and feedback thread |
| Hacker News | pending | pending | Show HN; repository URL |
| Reddit r/Python | pending | pending | Self post |
| Python Packaging Discourse | pending | pending | Technical feedback request |
| V2EX 分享创造 | pending | pending | Chinese technical launch |
| DEV Community | pending | pending | Article; AI assistance disclosed |
| OpenAI Developer Community | pending | pending | Codex-boundary update |
| X | blocked: no authenticated session | — | Thread drafted above |
| LinkedIn | blocked: connector unavailable | — | Post drafted above |
