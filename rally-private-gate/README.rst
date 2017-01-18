==========================
Rally Private Gate Project
==========================

Overview
--------

One of the requirements for the Dragonflow project is to test the code for performance
bottlenecks on a regular basis. After a number of consultations, we decided to use
rally as a platform for this task.

Rally has the following functionality that is relevant for our task:

  1. Running tests and generating report for the test.
  2. Trend report that can be used to compare results of a number of tests.

In addition, rally service can be installed on a stand alone server and use same
database to save results of the tasks and connect to multiple openstack servers.
