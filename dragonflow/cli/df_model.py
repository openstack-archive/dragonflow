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

import abc
import re
import six

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
    @abc.abstractmethod
    def output_model(self, model_):
        pass


class PlaintextPrinter(ModelPrinter):
    def output_model(self, model_):
        print('\n-------------\n{}\n-------------'.format(model_.name))
        for field in model_.fields:
            if field.restrictions:
                print('{name} - {type} {restriction}, {to_many}'.format(
                    name=field.name, type=field.type,
                    restriction=field.restrictions, to_many=field.to_many))
            else:
                print('{name} - {type}, {to_many}'.format(
                    name=field.name, type=field.type, to_many=field.to_many))


class DfModelParser(object):
    def _stringify_field_type(self, field):
        if field is six.string_types:
            return 'String', None
        elif isinstance(field, field_types.EnumField):
            field_type = type(field).__name__
            restrictions = []
            restrictions.extend(field._valid_values)
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
                field_type, restrictions = \
                    self._stringify_field_type(field.items_types[0])
            else:
                to_many = False
                field_type, restrictions = self._stringify_field_type(field)

            field_type = re.sub('Field$', '', field_type)
            current_model.add_field(ModelField(key, field_type,
                                               to_many, restrictions))
        return current_model

    def parse_models(self, printer):
        for model in model_framework.iter_models_by_dependency_order(False):
            printer.output_model(self._process_model(model))


if __name__ == "__main__":
    printer = PlaintextPrinter()
    parser = DfModelParser()
    parser.parse_models(printer)
