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


@six.add_metaclass(abc.ABCMeta)
class ModelsPrinter(object):
    def __init__(self, fh):
        self._output = fh

    def output_start(self):
        pass

    def output_end(self):
        pass

    def model_start(self, model_name):
        pass

    def model_end(self, model_name):
        pass

    @abc.abstractmethod
    def handle_field(self, name_, type_, is_single=True, restrictions=None):
        pass


class PlaintextPrinter(ModelsPrinter):
    def __init__(self, fh):
        super(PlaintextPrinter, self).__init__(fh)

    def model_start(self, model_name):
        print('-------------', file=self._output)
        print('{}'.format(model_name), file=self._output)
        print('-------------', file=self._output)

    def model_end(self, model_name):
        print('', file=self._output)

    def handle_field(self, name_, type_, is_single=True, restrictions=None):
        restriction_str = \
            ' {}'.format(restrictions) if restrictions else ''
        print('{} : {}{}, {}'.format(name_, type_,
                                     restriction_str,
                                     "One" if is_single else "Many"),
              file=self._output)


class UMLPrinter(ModelsPrinter):
    def __init__(self, fh):
        super(UMLPrinter, self).__init__(fh)
        self._model = ''
        self._processed = set()
        self._dependencies = set()

    def output_start(self):
        print('@startuml', file=self._output)

    def output_end(self):
        for (dst, src, name, is_single) in self._dependencies:
            if src in self._processed:
                many_str = '* ' if is_single else '+ '
                print('{} --{} {} : < {}'.format(dst, many_str, src, name),
                      file=self._output)
        print('@enduml', file=self._output)

    def model_start(self, model_name):
        self._model = model_name
        print('class {} {{'.format(model_name), file=self._output)

    def model_end(self, model_name):
        print('}', file=self._output)
        self._processed.add(model_name)
        self._model = ''

    def handle_field(self, name_, type_, is_single=True, restrictions=None):
        restriction_str = \
            ' {}'.format(restrictions) if restrictions else ''

        print('  +{} {} {}'.format(name_, type_, restriction_str),
              file=self._output)
        self._dependencies.add((self._model, type_, name_, is_single))


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
            return type(field).__name__, None
        else:
            try:
                return field.__name__, None
            except AttributeError:
                return type(field).__name__, None

    def _process_model(self, df_model):
        model_name = df_model.__name__
        self._printer.model_start(model_name)

        for key, field in df_model.iterate_over_fields():
            if isinstance(field, field_types.ListOfField):
                is_single = False
                field_type, restrictions = \
                    self._stringify_field_type(field.field)
            elif isinstance(field, fields.ListField):
                is_single = False
                types = field.items_types
                # We will only get the last type
                for field_type in types:
                    field_type, restrictions = \
                        self._stringify_field_type(field_type)
                if isinstance(field, field_types.EnumListField):
                    restrictions = list(field._valid_values)
            else:
                is_single = True
                field_type, restrictions = self._stringify_field_type(field)

            field_type = re.sub('Field$', '', field_type)
            self._printer.handle_field(key, field_type,
                                       is_single, restrictions)
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
    parser = argparse.ArgumentParser(description="Print Dragonflow schema")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--plaintext', help='Plaintext output (default)',
                       action='store_true')
    group.add_argument('--uml', help='PlantUML format output',
                       action='store_true')
    parser.add_argument('-o', '--outfile',
                        help='Output to file (instead of stdout)')
    args = parser.parse_args()
    with smart_open(args.outfile) as fh:
        if args.uml:
            printer = UMLPrinter(fh)
        else:
            printer = PlaintextPrinter(fh)
        parser = DfModelParser(printer)
        parser.parse_models()


if __name__ == "__main__":
    main()
