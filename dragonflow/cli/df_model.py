#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import print_function

import abc
import argparse
import contextlib
import re
import six
import sys

from jsonmodels import fields

from dragonflow.db import field_types
from dragonflow.db import model_framework
from dragonflow.db.models import all  # noqa
from oslo_serialization import jsonutils


# TODO(snapiri) We still have to handle the following:
# Classes: HostRoute, AddressPair, DhcpParams, PortBinding
# Fields:  MacAddress, IpAddress, IpNetwork, PortRange
# Temporary solution:
#  Fields: we currently print them as strings.
#  Classes: added the mf.construct_nb_db_model annotation - we should probably
#   remove them and find a better solution (maybe turn into fields?)

MODEL_SCHEMA_VERSION="0.0.1"

@six.add_metaclass(abc.ABCMeta)
class ModelsPrinter(object):
    def __init__(self, fh):
        self._output = fh

    def _print(self, *args, **kwargs):
        print(*args, file=self._output, **kwargs)

    def output_start(self):
        """
        Called once on the beginning of the processing.
        Should be used for initializations of any kind
        """
        pass

    def output_end(self):
        """
        Called once on the end of the processing.
        Should be used for cleanup and leftover printing of any kind
        """
        pass

    def model_start(self, model_name):
        """
        Called once for every model, before any field.
        """
        pass

    def model_end(self, model_name):
        """
        Called once for every model, after all model processing is done.
        """
        pass

    def fields_start(self):
        """
        Called once for every model, before all fields.
        """
        pass

    def fields_end(self):
        """
        Called once for every model, after all fields.
        """
        pass

    @abc.abstractmethod
    def handle_field(self, field_name, field_type, is_required,
                     is_single=True, restrictions=None):
        """
        Called once for every field in a model.
        """
        pass

    def indexes_start(self):
        """
        Called once for every model, before all indexes.
        Not called if no indexes exist
        """
        pass

    def indexes_end(self):
        """
        Called once for every model, after all indexes.
        Not called if no indexes exist
        """
        pass

    @abc.abstractmethod
    def handle_index(self, index_name):
        """
        Called once for every index in a model.
        """
        pass

    def events_start(self):
        """
        Called once for every model, before all events.
        Not called if no events exist
        """
        pass

    def events_end(self):
        """
        Called once for every model, after all events.
        Not called if no events exist
        """
        pass

    @abc.abstractmethod
    def handle_event(self, event_name):
        """
        Called once for every event in a model.
        """
        pass


class PlaintextPrinter(ModelsPrinter):
    def __init__(self, fh):
        super(PlaintextPrinter, self).__init__(fh)

    def model_start(self, model_name):
        self._print('-------------')
        self._print('{}'.format(model_name))
        self._print('-------------')

    def model_end(self, model_name):
        self._print('')

    def fields_start(self):
        self._print('Fields')
        self._print('------')

    def handle_field(self, field_name, field_type, is_required,
                     is_single=True, restrictions=None):
        restriction_str = ' {}'.format(restrictions) if restrictions else ''
        self._print('{name} : {type}{restriction}{required}{multi}'.format(
            name=field_name, type=field_type, restriction=restriction_str,
            required=', Required' if is_required else '',
            multi=', Multi' if not is_single else ''))

    def indexes_start(self):
        self._print('Indexes')
        self._print('-------')

    def handle_index(self, index_name):
        self._print('{}'.format(index_name))

    def events_start(self):
        self._print('Events')
        self._print('------')

    def handle_event(self, event_name):
        self._print('{}'.format(event_name))


class UMLPrinter(ModelsPrinter):
    """PlantUML format printer"""
    def __init__(self, fh):
        super(UMLPrinter, self).__init__(fh)
        self._model = ''
        self._processed = set()
        self._dependencies = set()

    def output_start(self):
        self._print('@startuml')
        self._print('hide circle')

    def _output_relations(self):
        for (dst, src, name, is_single) in self._dependencies:
            if src in self._processed:
                connector_str = ' o-- ' if is_single else ' o-- "*"'
                self._print('{dest} {connector} {src} : {field_name}'.format(
                    dest=dst, connector=connector_str, src=src,
                    field_name=name))

    def output_end(self):
        self._output_relations()
        self._print('@enduml')

    def model_start(self, model_name):
        self._model = model_name
        self._print('class {} {{'.format(model_name))

    def model_end(self, model_name):
        self._print('}')
        self._processed.add(model_name)
        self._model = ''

    def handle_field(self, field_name, field_type, is_required,
                     is_single=True, restrictions=None):
        restriction_str = ' {}'.format(restrictions) if restrictions else ''
        name = '<b>{}</b>'.format(field_name) if is_required else field_name
        self._print('  +{name} : {type} {restriction}'.format(
            name=name, type=field_type, restriction=restriction_str))
        self._dependencies.add((self._model, field_type,
                                field_name, is_single))

    def indexes_start(self):
        self._print('  .. Indexes ..')

    def handle_index(self, index_name):
        self._print('  {}'.format(index_name))

    def events_start(self):
        self._print('  == Events ==')

    def handle_event(self, event_name):
        self._print('  {}'.format(event_name))


class OASPrinter(ModelsPrinter):
    """OpenApiSchema format printer"""
    def __init__(self, fh):
        super(OASPrinter, self).__init__(fh)
        self._ref_base = '#/components/schemas'
        self._openapi_version = '3.0.0'
        self._required = list()
        self._base_types = ['string', 'number', 'float', 'boolean']
        self._models_obj = dict()
        self._model = dict()

    def output_start(self):
        info = dict()
        license = dict()
        paths = dict()
        schemas = dict()
        components = dict()
        self._models_obj['openapi'] = self._openapi_version
        self._models_obj['info'] = info
        info['title'] = 'DragonFlow Schema'
        info['description'] = 'jsonschma representation of the ' \
                              'DragonFlow model'
        info['license'] = license
        license['name'] = 'Apache 2.0'
        license['url'] = 'http://www.apache.org/licenses/LICENSE-2.0.html'
        info['version'] = MODEL_SCHEMA_VERSION
        self._models_obj['paths'] = paths
        self._models_obj['components'] = components
        components['schemas'] = schemas

    def output_end(self):
        jsonutils.dump(self._models_obj, self._output, indent=2)

    def model_start(self, model_name):
        self._required = list()
        self._model = dict()
        self._models_obj['components']['schemas'][model_name] = self._model
        self._model['type'] = 'object'

    def model_end(self, model_name):
        if len(self._required) > 0:
            self._model['required'] = self._required

    def fields_start(self):
        self._model['properties'] = dict()

    def fields_end(self):
        pass

    def _simple_field(self, field_type, restrictions):
        if field_type in self._base_types:
            return {'type': field_type}
        elif field_type == 'enum':
            return {field_type: list(restrictions)}
        else:
            return {'$ref': '{}/{}'.format(self._ref_base, field_type)}

    def _array_field(self, field_type, restrictions):
        return {'items': self._simple_field(field_type, restrictions),
                'type': 'array'}

    def handle_field(self, field_name, field_type, is_required,
                     is_single=True, restrictions=None):
        flds = self._model['properties']
        if is_single:
            flds[field_name] = self._simple_field(field_type, restrictions)
        else:
            flds[field_name] = self._array_field(field_type, restrictions)
        if is_required:
            self._required.append(field_name)

    def handle_index(self, index_name):
        pass

    def handle_event(self, event_name):
        pass


class DfModelParser(object):
    def __init__(self, printer):
        self._printer = printer

    def _stringify_field_type(self, field):
        if field in six.string_types:
            return 'string', None
        elif isinstance(field, field_types.EnumField):
            field_type = 'enum'
            restrictions = list(field._valid_values)
            return field_type, restrictions
        elif isinstance(field, field_types.ReferenceField):
            model = field._model
            return model.__name__, None
        elif isinstance(field, fields.StringField):
            return 'string', None
        elif isinstance(field, fields.IntField):
            return 'number', None
        elif isinstance(field, fields.FloatField):
            return 'float', None
        elif isinstance(field, fields.BoolField):
            return 'boolean', None
        elif isinstance(field, fields.BaseField):
            # TODO(snapiri) problematic fields flow get here
            # return type(field).__name__, None
            return 'string', None
        else:
            # TODO(snapiri) problematic classes flow get here
            return field.__name__, None

    def _process_field(self, key, field):
        if isinstance(field, field_types.ListOfField):
            is_single = False
            field_type, restrictions = \
                self._stringify_field_type(field.field)
        elif isinstance(field, fields.ListField):
            is_single = False
            field_type, restrictions = \
                self._stringify_field_type(field.items_types[0])
            if isinstance(field, field_types.EnumListField):
                restrictions = list(field._valid_values)
        elif isinstance(field, fields.EmbeddedField):
            is_single = True
            field_type, restrictions = \
                self._stringify_field_type(field.types[0])
        else:
            is_single = True
            field_type, restrictions = self._stringify_field_type(field)

        field_type = re.sub('Field$', '', field_type)
        self._printer.handle_field(key, field_type, field.required,
                                   is_single, restrictions)

    def _process_fields(self, df_model):
        self._printer.fields_start()
        for key, field in df_model.iterate_over_fields():
            self._process_field(key, field)
        self._printer.fields_end()

    def _process_indexes(self, df_model):
        model_indexes = df_model.get_indexes()
        if len(model_indexes) > 0:
            self._printer.indexes_start()
            for key in model_indexes:
                self._printer.handle_index(key)
            self._printer.indexes_end()

    def _process_events(self, df_model):
        model_events = df_model.get_events()
        if len(model_events) > 0:
            self._printer.events_start()
            for event in model_events:
                self._printer.handle_event(event)
            self._printer.events_end()

    def _process_model(self, df_model):
        model_name = df_model.__name__
        self._printer.model_start(model_name)

        self._process_fields(df_model)
        self._process_indexes(df_model)
        self._process_events(df_model)

        self._printer.model_end(model_name)

    def parse_models(self):
        self._printer.output_start()
        for model in model_framework.iter_models_by_dependency_order(False):
            self._process_model(model)
        self._printer.output_end()


@contextlib.contextmanager
def smart_open(filename=None):
    if filename and filename != '-':
        fh = open(filename, 'w')
    else:
        fh = sys.stdout

    try:
        yield fh
    finally:
        if fh is not sys.stdout:
            fh.close()


def main():
    parser = argparse.ArgumentParser(description='Print Dragonflow schema')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--plaintext', help='Plaintext output (default)',
                       action='store_true')
    group.add_argument('--uml', help='PlantUML format output',
                       action='store_true')
    group.add_argument('--json', help='OpenApiSchema JSON format output',
                       action='store_true')
    parser.add_argument('-o', '--outfile',
                        help='Output to file (instead of stdout)')
    args = parser.parse_args()
    with smart_open(args.outfile) as fh:
        if args.uml:
            printer = UMLPrinter(fh)
        elif args.json:
            printer = OASPrinter(fh)
        else:
            printer = PlaintextPrinter(fh)
        parser = DfModelParser(printer)
        parser.parse_models()


if __name__ == '__main__':
    main()
