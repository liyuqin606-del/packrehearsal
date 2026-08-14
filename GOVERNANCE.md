# Governance

PackRehearsal currently uses a benevolent-maintainer model suitable for an early
project.

## Roles

- **Maintainer:** triages issues, reviews pull requests, cuts releases, and owns
  security response. Maintainers have repository write access.
- **Contributor:** submits issues, tests, documentation, or code. Contribution
  does not imply repository authority.

[Yuqin Li (`@liyuqin606-del`)](https://github.com/liyuqin606-del) is the
founding primary maintainer and repository owner. Additional maintainers may be
added after sustained, reviewable contributions and explicit consent.

## Decisions

Routine changes use pull-request review. Decisions that alter safety defaults,
receipt formats, or rule severity require a public design issue and a documented
rationale. Security embargoes are the only normal exception to public-first
discussion.

## Releases

Only maintainers may publish packages or tags. A release requires passing CI,
an updated changelog, a PackRehearsal self-scan, a clean installation check,
checksums, and GitHub build-provenance attestations. The tag workflow builds and
publishes assets so release bytes remain tied to reviewed source.

## Compatibility

For 1.x, documented CLI commands and exit codes, schema version 1, and published
rule IDs are stable. Security hardening, false-positive fixes, and additive
rules may ship in minor or patch releases. Breaking public behavior requires a
new major version and a changelog migration note.

## Conflicts of interest

Maintainers disclose material affiliations when evaluating rules targeting a
specific registry, tool, or vendor. Sponsorships, vendors, and tool providers do
not control rule severity, safety defaults, or release decisions.
