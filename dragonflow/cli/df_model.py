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


class ModelField(object):
    def __init__(self, name, field_type,
                 to_many=False, restrictions=None):
        self.name = name
        self.type = field_type
        self.to_many = to_many
        self.restrictions = restrictions


class ModelClass(object):
    def __init__(self, name):
        self.name = name
        self.fields = []

    def add_field(self, field):
        self.fields.append(field)


@six.add_metaclass(abc.ABCMeta)
class ModelPrinter(object):
    def __init__(self, fh):
        self._output = fh

    def output_start(self):
        pass

    def output_end(self):
        pass

    @abc.abstractmethod
    def output_model(self, model_):
        pass


class PlaintextPrinter(ModelPrinter):
    def __init__(self, fh):
        super(PlaintextPrinter, self).__init__(fh)

    def output_model(self, model_):
        print('-------------', file=self._output)
        print('{}'.format(model_.name), file=self._output)
        print('-------------', file=self._output)
        for field in model_.fields:
            restriction_str = \
                ' {}'.format(field.restrictions) if field.restrictions else ''
            print('{} : {}{}, {}'.format(field.name, field.type,
                                         restriction_str,
                                         "Many" if field.to_many else "One"),
                  file=self._output)
        print('', file=self._output)


class UMLPrinter(ModelPrinter):
    def __init__(self, fh):
        super(UMLPrinter, self).__init__(fh)
        self._processed = set()
        self._dependencies = set()

    def output_start(self):
        print('@startuml', file=self._output)

    def output_end(self):
        for (dst, src, name, to_many) in self._dependencies:
            if src in self._processed:
                many_str = '+ ' if to_many else ''
                print('{} --{} {} : < {}'.format(dst, many_str, src, name),
                      file=self._output)
                print('@enduml', file=self._output)

    def output_model(self, model_):
        print('Object {}'.format(model_.name), file=self._output)
        for field in model_.fields:
            restriction_str = \
                ' {}'.format(field.restrictions) if field.restrictions else ''
            print('{} : {}{} {}'.format(model_.name, field.name,
                                        field.type, restriction_str),
                  file=self._output)
            self._dependencies.add((model_.name, field.type,
                                    field.name, field.to_many))
        self._processed.add(model_.name)


class DfModelParser(object):
    def _stringify_field_type(self, field):
        if field in six.string_types:
            return 'String', None
        elif isinstance(field, field_types.EnumField):
            field_type = type(field).__name__
            restrictions = list(field._valid_values)
            return field_type, restrictions
        elif isinstance(field, field_types.ReferenceField):
            model = field._model
            return model.__name__, None
        elif isinstance(field, fields.BaseField):
            return type(field).__name__, None
        else:
            try:
                return field.__name__, None
            except AttributeError:
                return type(field).__name__, None

    def _process_model(self, df_model):
        current_model = ModelClass(df_model.__name__)

        for key, field in df_model.iterate_over_fields():
            if isinstance(field, field_types.ListOfField):
                to_many = True
                field_type, restrictions = \
                    self._stringify_field_type(field.field)
            elif isinstance(field, fields.ListField):
                to_many = True
                types = field.items_types
                # We will only get the last type
                for field_type in types:
                    field_type, restrictions = \
                        self._stringify_field_type(field_type)
                if isinstance(field, field_types.EnumListField):
                    restrictions = list(field._valid_values)
            else:
                to_many = False
                field_type, restrictions = self._stringify_field_type(field)

            field_type = re.sub('Field$', '', field_type)
            current_model.add_field(ModelField(key, field_type,
                                               to_many, restrictions))
        return current_model

    def parse_models(self, printer):
        printer.output_start()
        for model in model_framework.iter_models_by_dependency_order(False):
            printer.output_model(self._process_model(model))
        printer.output_end()


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
    parser = DfModelParser()
    with smart_open(args.outfile) as fh:
        if args.uml:
            printer = UMLPrinter(fh)
        else:
            printer = PlaintextPrinter(fh)
        parser.parse_models(printer)


if __name__ == "__main__":
    main()
