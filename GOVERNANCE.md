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
an updated changelog, a PackRehearsal self-scan, and a signed or checksummed
evidence receipt when release infrastructure supports it.

## Conflicts of interest

Maintainers disclose material affiliations when evaluating rules targeting a
specific registry, tool, or vendor. Sponsorships, vendors, and tool providers do
not control rule severity, safety defaults, or release decisions.
