# Phlogiston integration baseline

This branch begins from committed `atproto-community` revision
`b3b7c6b4bdd8057e077215868ae42fef5aac9b7a` plus the bounded PCV0/PCV1
implementation paths copied from the pre-existing dirty checkout on
2026-09-22. The source checkout was not modified.

Included paths are the community model, authority writer, observer/AppView,
policy worker, Lexicon publisher, `community-live` reference-client candidate,
their focused configuration/deployment validators, and their tests. Unrelated
untracked product-direction, roadmap, attention-research, worker-prompt, and
campaign-document files were not copied.

This commit is custody for the integration input, not a claim that the copied
work was previously accepted, published, or deployed. The full Python baseline
under the restricted sandbox reached 1,161 passing tests; 97 failures and 50
setup errors were all in suites requiring local INET or Unix sockets, which
the sandbox refused with `EPERM`. Those suites must be rerun outside that
restriction before this baseline or any derivative is accepted.
