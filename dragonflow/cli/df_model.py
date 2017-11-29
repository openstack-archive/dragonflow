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
import six
import sys

from jsonmodels import fields
from oslo_serialization import jsonutils

from dragonflow.db import field_types
from dragonflow.db import model_framework
from dragonflow.db.models import all  # noqa


STRING_TYPE = 'string'
NUMBER_TYPE = 'number'
FLOAT_TYPE = 'float'
BOOL_TYPE = 'boolean'
ENUM_TYPE = 'enum'
BASIC_TYPES = (STRING_TYPE, NUMBER_TYPE, FLOAT_TYPE, BOOL_TYPE, ENUM_TYPE)


@six.add_metaclass(abc.ABCMeta)
class ModelsPrinter(object):
    """Abstract base class for the different format printers.

    Every specific format printer should inherit from this class and
    implement the methods for the specific output format.

    All the models are handled one after the other, and it is guaranteed
    that if a model depends on another model, the dependant model will
    be handled _after_ the model it depends on.
    """

    def __init__(self, fh):
        """Basic constructor for the base class.

        :param fh: file handler of the output stream to write to
        :type fh: file object
        """
        self._output = fh

    def _print(self, *args, **kwargs):
        print(*args, file=self._output, **kwargs)

    def output_start(self):
        """Handler called once before any processing is done.

        This should be used for initialization or to print any prefix the
        specific output format requires.
        """
        pass

    def output_end(self):
        """Handler called once after all processing is done.

        This should be used for cleanup or to print any remaining data or
        suffixes the specific output format requires.
        """
        pass

    def model_start(self, model_name):
        """Handler called once per model, before processing the model.

        This should be used to clean/initialize any data specific for the
        handling of the model.

        :param model_name: the name of the model
        :type model_name: string
        """
        pass

    def model_end(self, model_name):
        """Handler called once per model, after processing the model.

        This should be used to cleanup or to print any remaining data or
        suffixes specific for the handling of the model.

        :param model_name: the name of the model
        :type model_name: string
        """
        pass

    def fields_start(self):
        """Handler called once per model, before processing the fields.

        This should be used to initialize any data specific for the
        handling of the model fields.
        """
        pass

    def fields_end(self):
        """Handler called once per model, after processing all the fields.

        This should be used to cleanup any data specific for the handling
        of the model fields.
        """
        pass

    @abc.abstractmethod
    def handle_field(self, field_name, field_type, is_required, is_embedded,
                     is_single, restrictions):
        """Handler called once per field in a model.

        This should be used to print the specific field.
        :param field_name: the name of the field
        :type field_name: string
        :param field_type: string - the type of the field (e.g. number)
        :type field_type: string
        :param is_required: True iff the field is a required field for the
        specific model
        :type is_required: bool
        :param is_embedded: True iff the field is not a reference to another
        object, but rather an object that is part of the model
        :type is_embedded: bool
        :param is_single: True iff the field is single-valued
        :type is_single: bool
        :param restrictions: representation of any restrictions on the field
        (e.g. list of possible values for enum)
        :type restrictions: string
        """
        pass

    def indexes_start(self):
        """Handler called once per model, before processing the indexes.

        The indexes are fields that are marked as indexes, thus are a subset
        of the list of model indexes.
        This should be used to initialize any data specific for the
        handling of the model indexes.
        In case there are no indexes for this model, this method will not be
        called.
        """
        pass

    def indexes_end(self):
        """Handler called once per model, after processing all the indexes.

        This should be used to cleanup any data specific for the handling
        of the model indexes.
        In case there are no indexes for this model, this method will not be
        called.
        """
        pass

    @abc.abstractmethod
    def handle_index(self, index_name):
        """Handler called once per index in a model.

        This should be used to print the specific index.
        :param index_name: the name of the index field
        :type index_name: string
        """
        pass

    def events_start(self):
        """Handler called once per model, before processing the events.

        This should be used to initialize any data specific for the
        handling of the model events.
        In case there are no events for this model, this method will not be
        called.
        """
        pass

    def events_end(self):
        """Handler called once per model, after processing all the events.

        This should be used to cleanup any data specific for the handling
        of the model events.
        In case there are no events for this model, this method will not be
        called.
        """
        pass

    @abc.abstractmethod
    def handle_event(self, event_name):
        """Handler called once per event in a model.

        This should be used to print the specific event.
        :param event_name: the name of the event
        :type event_name: string
        """
        pass


class PlaintextPrinter(ModelsPrinter):
    """ModelPrinter that prints to simple plaintext format.

    This printer prints the models in the most simple way.
    """
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

    def handle_field(self, field_name, field_type, is_required, is_embedded,
                     is_single, restrictions):
        restriction_str = ' {}'.format(restrictions) if restrictions else ''
        self._print('{name} : {type}{restriction}{required}{multi}'.format(
            name=field_name, type=field_type, restriction=restriction_str,
            required=', Required' if is_required else '',
            multi=', Multi' if not is_single else '',
            embedded=', Embedded' if is_embedded else ''))

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
    """ModelPrinter that prints to UML format.

    This printer prints the models in PlantUML format.
    """
    def __init__(self, fh):
        super(UMLPrinter, self).__init__(fh)
        self._model = ''
        self._processed = set()
        self._dependencies = set()

    def output_start(self):
        self._print('@startuml')
        self._print('hide circle')

    def _output_relations(self):
        for (dst, src, name, is_single, is_embedded) in self._dependencies:
            if src in self._processed:
                if is_embedded:
                    connector_str = ' *-- ' if is_single else '"1" *-- "*"'
                else:
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

    def handle_field(self, field_name, field_type, is_required, is_embedded,
                     is_single, restrictions):
        restriction_str = ' {}'.format(restrictions) if restrictions else ''
        name = '<b>{}</b>'.format(field_name) if is_required else field_name
        self._print('  +{name} : {type} {restriction}'.format(
            name=name, type=field_type, restriction=restriction_str))
        self._dependencies.add((self._model, field_type, field_name,
                                is_single, is_embedded))

    def indexes_start(self):
        self._print('  .. Indexes ..')

    def handle_index(self, index_name):
        self._print('  {}'.format(index_name))

    def events_start(self):
        self._print('  == Events ==')

    def handle_event(self, event_name):
        self._print('  {}'.format(event_name))


class OASPrinter(ModelsPrinter):
    """ModelPrinter that prints to JSON format

    This printer prints the models in JSON format.
    Specifically, it uses the OpenApiSchema format.
    """
    _OPENAPI_VERSION = '3.0.0'
    _MODEL_SCHEMA_VERSION = '0.0.1'
    _SCHEMA_BASE_PATH = '#/components/schemas'
    _INFO_TITLE = 'DragonFlow Schema'
    _INFO_DESC = 'jsonschma representation of the DragonFlow model'
    _LIC_NAME = 'Apache 2.0'
    _LIC_URL = 'http://www.apache.org/licenses/LICENSE-2.0.html'

    def __init__(self, fh):
        super(OASPrinter, self).__init__(fh)
        self._required = list()
        self._base_types = BASIC_TYPES
        self._models_obj = dict()
        self._model = dict()

    def output_start(self):
        info = dict()
        license = dict()
        paths = dict()
        schemas = dict()
        components = dict()
        self._models_obj['openapi'] = OASPrinter._OPENAPI_VERSION
        self._models_obj['info'] = info
        info['title'] = OASPrinter._INFO_TITLE
        info['description'] = OASPrinter._INFO_DESC
        info['license'] = license
        license['name'] = OASPrinter._LIC_NAME
        license['url'] = OASPrinter._LIC_URL
        info['version'] = OASPrinter._MODEL_SCHEMA_VERSION
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
        elif field_type == ENUM_TYPE:
            return {field_type: list(restrictions)}
        else:
            return {'$ref': '{}/{}'.format(OASPrinter._SCHEMA_BASE_PATH,
                                           field_type)}

    def _array_field(self, field_type, restrictions):
        return {'items': self._simple_field(field_type, restrictions),
                'type': 'array'}

    def handle_field(self, field_name, field_type, is_required, is_embedded,
                     is_single, restrictions):
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
        self._basic_types = BASIC_TYPES
        self._processed_models = set()
        self._all_models = set()

    def _stringify_field_type(self, field):
        if field in six.string_types:
            return STRING_TYPE, None
        elif isinstance(field, field_types.EnumField):
            field_type = ENUM_TYPE
            restrictions = list(field._valid_values)
            return field_type, restrictions
        elif isinstance(field, field_types.ReferenceField):
            model = field._model
            return model.__name__, None
        elif isinstance(field, fields.StringField):
            return STRING_TYPE, None
        elif isinstance(field, fields.IntField):
            return NUMBER_TYPE, None
        elif isinstance(field, fields.FloatField):
            return FLOAT_TYPE, None
        elif isinstance(field, fields.BoolField):
            return BOOL_TYPE, None
        elif isinstance(field, fields.BaseField):
            return STRING_TYPE, None
        else:
            return field.__name__, None

    def _process_field(self, key, field):
        if isinstance(field, field_types.ListOfField):
            is_single = False
            is_embedded = not isinstance(field,
                                         field_types.ReferenceListField)
            field_model = field.field
        elif isinstance(field, fields.ListField):
            is_single = False
            is_embedded = False
            field_model = field.items_types[0]
            if isinstance(field, field_types.EnumListField):
                restrictions = list(field._valid_values)
        elif isinstance(field, fields.EmbeddedField):
            is_single = True
            is_embedded = True
            field_model = field.types[0]
        else:
            is_single = True
            is_embedded = False
            field_model = field
        field_type, restrictions = self._stringify_field_type(field_model)

        if field_type not in self._basic_types:
            if isinstance(field_model, field_types.ReferenceField):
                model = field_model._model
            else:
                model = field_model
            self._all_models.add(model)
            # As we iterate over the models by their dependencies, if we did
            # not encounter this model, it is an embedded model (type)
            if model not in self._processed_models:
                is_embedded = True
        self._printer.handle_field(key, field_type, field.required,
                                   is_embedded, is_single, restrictions)

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
        self._processed_models.add(df_model)

    def _process_unvisited_model(self, model):
        model_name = model.__name__
        self._printer.model_start(model_name)
        self._process_fields(model)
        self._printer.model_end(model_name)

    def parse_models(self):
        self._printer.output_start()
        for model in model_framework.iter_models_by_dependency_order(False):
            self._process_model(model)
        # Handle unvisited models
        remaining_models = self._all_models - self._processed_models
        for model in remaining_models:
            self._process_unvisited_model(model)
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
