===============
Reviewers Guide
===============

In this document, we try to guide reviewers in what to look for when
accepting a patch for Dragonflow. This guide is also helpful for new
contributors to know what's expected in a patch.

Checklist
=========

The following items are expected for every patch:

# Commit message:
  A title explaining what is done. The body of the commit message should
  concisely explain *what this change does* (if not trivial and covered by
  the title) and *why this change is done* (If not obvious). Triviality and
  obviousness are left to the reviewer's discretion

# Tests:
  Every change must be covered by a test. Unit tests are often the bare
  minimum and good enough, but a fullstack or tempest test will also do
  in a pinch.

# Documentation:
  Every non-trivial function (say, longer than 10 lines, but left to the
  reviewer's discretion) must contain a pydoc. If a feature's design is
  changed (e.g. flow structure), then the relevant spec or dev-ref must
  be updated.

# Referenced Bug:
  All but the most trivial changes should be linked with a Related-Bug,
  Partial-Bug, or Closes-Bug declaration. In case of extremely trivial
  fixes, TrivialFix may be stated instead, but it is at the reviewer's
  discretion whether the change is truly a Trivial Fix.
