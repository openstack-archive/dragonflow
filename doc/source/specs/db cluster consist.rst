This work is licensed under a Creative Commons Attribution 3.0 Unported
License.
 
http://creativecommons.org/licenses/by/3.0/legalcode

===================
DB Consistency
===================
This blueprint describe the solution of keeping data consistency between Neutron db and Dragonflow db, also the same problem exists between Dragonflow db and df local controller cache. It tries to keep data consistency in the whole system and keep the system working steady.

===================
Problem Description
===================

We want to divide the problems into two parts, one part refers to the problems between Neutron db and Dragonflow db, while another refers to the problems between Dragonflow db and local controller cache.
The former part contains the problems below:
1.When Neutron plugin commit the db transaction first, and then to do db operation to Dragonflow db, if it happens to get some exceptions, the data of the two dbs is inconsistency which may cause some errors in the system like the object could not be found, etc;
2.When we deploy multi Neutron server nodes(of course multi Neutron plugins), if multi plugins happens to write the same object in Dragonflow db simultaneous in some cases, data of two databases will be inconsistency because of data rewrite;
The latter part contains the problems below:
1.When local controller tries to read\write data from\to Dragonflow db, if it happens to get some exceptions for example, because of lost database connection, the data between local controller cache and Dragonflow db will be inconsistency;
2.Similarly, if there are some problems for the subscribe\publish channel between local controller and Dragonflow db, local controller may lose some important data notifications send by Dragonflow db, so the two databases will be inconsistency again.

===========================================
Solution Description Between Neutron db and Dragonflow db
============================================

To solve the above problems between Neutron db and Dragonflow db, we have the following mechanism:
1.When initialize or restart the Neutron server cluster, once first Neutron server connects to Neutron db and DragonFlow db, it should do the data comparison between Neutron db and Dragonflow db, and then force to synchronize the data to Dragonflow db, while other Neutron servers will find the first Neutron server has done the data comparison and synchronize, so they will do nothing;
2.When df plugin receive a create object(router\network\subnet\port, etc) invoke, it commit the operation to Neutron db successfully, but failed to operate Dragonflow db, in this case, df plugin would attempt several times (could be configured) to commit the operation, if failed after all the attempts, plugin should rollback the previous commit, delete the previous data in Neutron db and report error to refuse the create object invoke;
3.When df plugin receive a update\delete object(router\network\subnet\port, etc) invoke, it commit the operation to Neutron db successfully, but failed to operate Dragonflow db, in this case, df plugin would attempt several times (could be configured) to commit the operation, if failed after all the attempts, plugin should report error to refuse the update\delete object invoke without rollback the previous commit, because the data should be update\delete in Neutron db and the data in Dragonflow db is dirty and unnecessary which would be handled by other mechanism like step4;
4.Optionally, we could develop and deploy a simple program to do the data comparison between Neutron db and Dragonflow db periodically, if the program find the different data between the db cluster, it should report warning to operation and maintenance system, the warning should contain the key info of founded different data;
5.When we deploy multi Neutron plugins, maybe we need db lock to avoid data rewrite by multi db client, the db lock could be provided by db cluster itself or 3rd software like zookeeper.

=====================================================
Solution Description Between Dragonflow db and Local Controller Cache
======================================================

To solve the above problems we have the following mechanism:
1.When initialize or restart the df local controller, it should fetch its interesting data from Dragonflow db according to its local ovsdb port, for example, if local controller find a vm port which belong to a tenant on local host by ovsdb monitor, it would fetch all the tenant data from Dragonflow db and update local cache, on the other hand, if local controller find a new vm port on local host but there are no related data in the Dragonflow db, it should update Dragonflow db and notify a new vm port online;
2.When local controller tries to do some db operations, such as create\update\delete\get, etc, if it failed to operate Dragonflow db, it would attempt several times (could be configured) to commit the operation, if failed after all the attempts, local controller should report error and give up this operation because it has been a isolated island;
3.When Dragonflow db driver find that the exception between local controller and Dragonflow db has been fixed, it should notify local controller the exception recover event, after receive the event, local controller would pull the data from Dragonflow db and compare with local controller cache, like step1 local controller would do the synchronize to update local cache data and update\notify new local host data to Dragonflow db;
4.Optionally, we could let local controller to synchronize the data between local cache and Dragonflow db periodically, however the interval should not be too short for performance consideration;

============
Conclusion
============



Our solution provides some mechanism which implements the data consistency between each data store in the whole system.
