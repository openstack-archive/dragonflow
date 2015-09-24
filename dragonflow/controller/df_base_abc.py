from abc import ABCMeta

class DFlowAbc:
    __metaclass__ = ABCMeta

    # add_local_port virtual function,
    # any subclass must reimplement as it sees fit
    @abstractmethod
    def add_local_port(self, lport):
        pass

    # add_remote_port virtual function,
    # any subclass must reimplement as it sees fit
    @abstractmethod
    def add_remote_port(self, lport):
        pass

    # remove_local_port virtual function,
    # any subclass must reimplement as it sees fit
    @abstractmethod
    def remove_local_port(self, lport_id):
        pass

    # remove_remote_port virtual function,
    # any subclass must reimplement as it sees fit
    @abstractmethod
    def remove_remote_port(self, lport_id):
        pass

    # logical_switch_deleted virtual function
    # any subclass must reimplement as it sees fit
    @abstractmethod
    def logical_switch_deleted(self, lswitch_id):
        pass

    # logical_switch_updated virtual function,
    # any subclass must reimplement as it sees fit
    @abstractmethod
    def logical_switch_updated(self, lswitch):
        pass

