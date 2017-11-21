================================
Creating release notes with Reno
================================

Release notes for Dragonflow are generated semi-automatically from source with
Reno.

Reno allows you to add a release note. It creates a yaml structure for you to
fill in. The items are explained `here <https://docs.openstack.org/reno/latest/user/usage.html#editing-a-release-note>`_. If an item is not needed, it can be
removed from the structure.

Basic Usage
-----------

To create a new release note, run:

::

    tox -e venv -- reno new <my-new-feature>

This creates a release notes file. You can identify the file with the output:

::

    Created new notes file in releasenotes/notes/asdf-1a11d0cca0cb76fa.yaml

You can now edit this file to fit your release notes needs.

Don't forget to add this file to the commit with `git add`.

The release notes are built automatically by the gate system. There is a tox
environment to generate all the release notes manually. To do so, run:

::

    tox -e releasenotes

Easy enough!

For more information, see the `reno usage documentation <https://docs.openstack.org/reno/latest/user/usage.html>`_.
