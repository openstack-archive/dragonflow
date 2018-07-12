==============================
Contributors & Reviewers Guide
==============================

In this document, we try to guide contributors to know what should be included
in the patch.
This guide is also helpful for reviewers covering what to look for when
accepting a patch for Dragonflow.

Checklist
=========

The following items are expected for every patch:

# Commit message:
  A title explaining what is done. The body of the commit message should
  concisely explain *what this change does* (if not trivial and covered by
  the title) and *why this change is done* (if not obvious). Triviality and
  obviousness are left to the reviewer's discretion.

# Tests:
  Every change must be covered by tests. Unit tests are often the bare
  minimum and good enough, but a fullstack or tempest test will also do
  in a pinch.

# Documentation:
  Every non-trivial function (say, longer than 10 lines, but left to the
  reviewer's discretion) must contain a pydoc. If a feature's design is
  changed (e.g. flow structure), then the relevant spec or dev-ref must
  be added or updated.

# Referenced Bug:
  All but the most trivial changes should be linked with a Related-Bug,
  Partial-Bug, or Closes-Bug declaration. In case of extremely trivial
  fixes, TrivialFix may be stated instead, but it is at the reviewer's
  discretion whether the change is truly a Trivial Fix.

# Release Notes:
  For NB API changes, configuration changes, new drivers and new application
  relevant release note should be added. It is recommended to use reno, see
  TBD.


Spec & DevRef
=============

Spec should cover what the proposed feature is about, the impact it has
on the user, etc.  It is the high-level design document. In essence,
it should show the *spirit* of the implementation. It should convey
the general idea of what the feature does, how packets are handled,
and where the information comes from. The spec should also include
data-model changes, since this is the basis for the Dragonflow API.

DevRef should cover how the proposed feature is supported. It is a low-level
design document explaining how the feature is implemented. It should cover
design decisions too low level to be included in the spec. It should also
cover the southbound implementation, including the rationale. The general
guideline should be - if a new contributor reads this document, they should
be able to understand the code of the application.

The difference between a spec and a devref is difficult to formalize. In
essence, the spec should give a high-level design, while the dev-ref should
give a low-level design of the feature. The guiding thought is that the spec
should remain unchange unless there is a massive feature overhaul, but the
dev-ref may change due to bug fixes, since it covers the low-level specifics.

Note that when writing the dev-ref, that the code is also available. Rather
than explain the code, try to explain what the code is supposed to do, what is
the end result supposed to look like, and most importantly, why the code looks
that way.

Specs are usually reviewed and accepted before the implementation begins.
Dev-refs are usually reviewed and accepted as part of the implementation or
implementation change.

Bugs & Blueprints
=================

For any issue with existing implementation, a bug report is expected.

For any new feature request or existing feature enhancement bug report with
[RFE] tag is expected.
Blueprint creation is not required.

Bug report should have descriptive title and detailed description. It is not
a trivial task to submit a good bug-report, so we try to outline some
guidelines that may help:

* First explain the functionality issue
  We have seen many bug reports which were just a stack-trace dump, with no
  explanation of the effect it has on the user. It is difficult to understand
  if the e.g. exception is benign, or there's a real issue behind it. It is
  also helpful to explain what's the expected behaviour. It's possible we
  just mis-understood the feature.

* Explain how to reproduce
  It is very difficult to mark a bug as solved, if we don't know how you
  reached it. Reproduction steps go a long way to make a bug clear and easy to
  tackle.
  It is also very helpful to have a copy of the deployment configurations, e.g.
  a config file or (in the case of devstack) a local.conf file.

* One issue per bug
  We are not affraid of bug reports. And they are easier to manage if each bug
  is a single atomic issue we need to fix (There are some exceptions to this
  guideline, but they are usually very rare).
