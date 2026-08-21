# PackRehearsal community launch plan

Research snapshot: 2026-08-21.

PackRehearsal should be introduced as a release-engineering tool with an
evidence-bounded Codex workflow, not as a generic AI coding demo. The strongest
message is: **inspect the bytes that will ship, turn only verified findings into
a bounded Codex maintenance task, and keep merge and release under human
control.**

## Priority communities

| Priority | Community | Why it fits | Recommended approach | Promotion risk |
|---:|---|---|---|---|
| 1 | [OpenAI Developer Community — Codex](https://community.openai.com/t/codex-how-to-a-measurable-engineering-loop-with-9-reusable-skills/1388595) | The Codex maintenance brief is a first-class project workflow. Existing posts show that independent OSS tools, runnable steps, limitations, and explicit feedback questions are welcome. | Publish a technical walkthrough of `scan -> evidence -> codex-brief -> human review`, with one real fixture and the WebUI screenshot. Ask where the maintenance boundary breaks in real repositories. | Low if the post is concrete, unofficial status is disclosed, and claims stay bounded. |
| 2 | [Python Packaging — Announcements](https://discuss.python.org/c/packaging/ann/36) | The category explicitly allows one-off announcements for new projects and tools directly related to packaging. | Lead with wheel/sdist metadata consistency and archive inspection. Ask packaging maintainers to test one real release candidate. Mention npm/Rust only after the Python evidence. | Low to medium; stay technical and avoid treating it as a traffic channel. |
| 3 | [Show HN](https://news.ycombinator.com/showhn.html) | PackRehearsal is non-trivial, runnable locally, and has a clear engineering story. The official guidelines favor things readers can try without signup. | Title: `Show HN: PackRehearsal – inspect package artifacts before Codex fixes them`. Include install command, exact safety boundary, current limitations, and remain available to answer questions. | Medium; do not post until a clean install and runnable demo are effortless. Never coordinate votes. |
| 4 | [OpenSSF Supply Chain Integrity](https://openssf.org/groups/supply-chain-integrity/) | The group focuses on provenance and decisions about code people maintain, produce, and use; its working groups are open to everyone. | Join the Slack or an open meeting first. Request design feedback on artifact integrity, receipts, attestations, and threat-model gaps rather than posting a launch ad. | Low if framed as contribution and review; high if dropped into Slack as drive-by promotion. |
| 5 | [Open Design Discussions](https://github.com/nexu-io/open-design/discussions) / [Discord](https://discord.gg/mHAjSMV6gz) | The Release Gate WebUI was implemented with Open Design's image-to-code and frontend-design skills; its community explicitly supports “show your work.” | Share a before/after image, Computer Modern typography rationale, responsive QA, and a short note about what the skill changed. Link the project as the implementation artifact. | Low; the design process is genuinely relevant to the community. |
| 6 | [r/opensource](https://www.reddit.com/r/opensource/) | The subreddit has an active `Promotional` flair and current project posts. | Use the promotional flair, disclose authorship, state Apache-2.0 and local-only behavior, then ask for one specific kind of feedback. Participate before and after posting; do not cross-post identical copy widely. | Medium; rules discourage drive-by and excessive self-promotion. |
| 7 | [V2EX /create](https://www.v2ex.com/go/create) and [/python](https://www.v2ex.com/go/python) | `/create` actively carries independent project launches; `/python` currently includes packaging and testing tools. | Chinese post: problem, one screenshot, three-command demo, actual limitations, and a request for Windows/macOS/Linux packaging maintainers to test. Choose one primary node rather than duplicating the same launch. | Medium; factual creator posts fit, but advertising language will be poorly received. |
| 8 | [Terminal Trove](https://terminaltrove.com/post/) | It is a focused directory for terminal tools and asks for license, install commands, audience, screenshots, and standout features. | Submit after PackRehearsal exists in a package repository; the form explicitly asks for package-manager install instructions. Reuse the Release Gate image and CLI safety facts. | Low, but it is a directory rather than a discussion community. |
| Later | [Lobsters](https://lobste.rs/about) | Highly relevant systems and tooling audience, but the community expects real participation and strongly dislikes write-only self-promotion. | Build a normal comment/submission history first. Prefer a technical “what we learned building bounded archive inspection” article over a bare repository link, and disclose authorship. | High for a new or promotional-only account. |

## Recommended launch sequence

1. **Feedback launch:** OpenAI Codex community, Python Packaging, and Open
   Design. Use different posts: maintenance workflow, packaging evidence, and
   visual implementation respectively.
2. **Technical launch:** Show HN after the public repository, immutable release,
   install path, WebUI preview, CI, and limitations are all immediately visible.
3. **Targeted distribution:** r/opensource and one V2EX node, with native copy
   and explicit authorship.
4. **Long-tail discovery:** Terminal Trove after package-registry availability;
   OpenSSF after participating in its supply-chain discussions.
5. **Relationship-first:** Lobsters only after genuine community participation.

Do not post the same marketing copy everywhere on one day. Stagger launches so
feedback from the first community can improve the demo, documentation, and
technical explanation for the next one.

## Launch copy skeleton

> PackRehearsal is an Apache-2.0, local-first release gate for Python, npm, and
> Rust packages. It statically compares manifests with the archive bytes that
> will actually ship, then turns only verified findings into a bounded Codex
> maintenance task. The default path is offline, does not execute project code,
> and never merges or releases automatically. v1.1 is available now; I am
> looking for maintainers willing to test it against a real release candidate
> and report false positives or missing gates.

Each platform-specific post should add one reproducible example, one known
limitation, and one concrete feedback question. Avoid star requests,
superlatives, coordinated voting, or claims that the tool makes a package
“safe.”
