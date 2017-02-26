from dragonflow.db.models import legacy_models

# Remove those once we're done
NbObject = legacy_models.NbObject
NbDbObject = legacy_models.NbDbObject
UniqueKeyMixin = legacy_models.UniqueKeyMixin
Chassis = legacy_models.Chassis
LogicalSwitch = legacy_models.LogicalSwitch
Subnet = legacy_models.Subnet
LogicalPort = legacy_models.LogicalPort
LogicalRouter = legacy_models.LogicalRouter
LogicalRouterPort = legacy_models.LogicalRouterPort
SecurityGroup = legacy_models.SecurityGroup
SecurityGroupRule = legacy_models.SecurityGroupRule
Floatingip = legacy_models.Floatingip
QosPolicy = legacy_models.QosPolicy
Publisher = legacy_models.Publisher
AllowedAddressPairsActivePort = legacy_models.AllowedAddressPairsActivePort
Listener = legacy_models.Listener
OvsPort = legacy_models.OvsPort

table_class_mapping = legacy_models.table_class_mapping
