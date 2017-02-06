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

from oslo_utils import encodeutils
import prettytable
import six
import textwrap

from dragonflow.common import exceptions


def get_list_table_columns_and_formatters(fields, objs, exclude_fields=(),
                                          filters=None):
    """Check and add fields to output columns.

    If there is any value in fields that not an attribute of obj,
    CommandError will be raised.
    If fields has duplicate values (case sensitive), we will make them unique
    and ignore duplicate ones.
    :param fields: A list of string contains the fields to be printed.
    :param objs: An list of object which will be used to check if field is
                 valid or not. Note, we don't check fields if obj is None or
                 empty.
    :param exclude_fields: A tuple of string which contains the fields to be
                           excluded.
    :param filters: A dictionary defines how to get value from fields, this
                    is useful when field's value is a complex object such as
                    dictionary.
    :return: columns, formatters.
             columns is a list of string which will be used as table header.
             formatters is a dictionary specifies how to display the value
             of the field.
             They can be [], {}.
    :raise: dragonflow.common.exceptions.CommandError.
    """

    if objs and isinstance(objs, list):
        obj = objs[0]
    else:
        obj = None
        fields = None

    columns = []
    formatters = {}

    if fields:
        non_existent_fields = []
        exclude_fields = set(exclude_fields)

        for field in fields:
            if field not in obj:
                non_existent_fields.append(field)
                continue
            if field in exclude_fields:
                continue
            field_title, formatter = make_field_formatter(field, filters)
            columns.append(field_title)
            formatters[field_title] = formatter
            exclude_fields.add(field)

        if non_existent_fields:
            raise exceptions.CommandError(
                non_existent_fields=non_existent_fields)

    return columns, formatters


def keys_and_vals_to_strs(dictionary):
    """Recursively convert a dictionary's keys and values to strings.

    :param dictionary: dictionary whose keys/vals are to be converted to strs
    """
    def to_str(k_or_v):
        if isinstance(k_or_v, dict):
            return keys_and_vals_to_strs(k_or_v)
        elif isinstance(k_or_v, six.text_type):
            return str(k_or_v)
        else:
            return k_or_v
    return dict((to_str(k), to_str(v)) for k, v in dictionary.items())


def _format_field_name(attr):
    """Format an object attribute in a human-friendly way."""
    # Split at ':' and leave the extension name as-is.
    parts = attr.rsplit(':', 1)
    name = parts[-1].replace('_', ' ')
    # Don't title() on mixed case
    if name.isupper() or name.islower():
        name = name.title()
    parts[-1] = name
    return ': '.join(parts)


def make_field_formatter(attr, filters=None):
    """Given an object attribute.

    Return a formatted field name and a formatter suitable for passing to
    print_list.
    Optionally pass a dict mapping attribute names to a function. The function
    will be passed the value of the attribute and should return the string to
    display.
    """

    filter_ = None
    if filters:
        filter_ = filters.get(attr)

    def get_field(obj):
        field = getattr(obj, attr, '')
        if field and filter_:
            field = filter_(field)
        return field

    name = _format_field_name(attr)
    formatter = get_field
    return name, formatter


def print_dict(dct, dict_property="Property", wrap=0):
    """Print a `dict` as a table of two columns.

    :param dct: `dict` to print
    :param dict_property: name of the first column
    :param wrap: wrapping for the second column
    """
    pt = prettytable.PrettyTable([dict_property, 'Value'])
    pt.align = 'l'
    for k, v in dct.items():
        # convert dict to str to check length
        if isinstance(v, dict):
            v = six.text_type(keys_and_vals_to_strs(v))
        if wrap > 0:
            v = textwrap.fill(six.text_type(v), wrap)
        # if value has a newline, add in multiple rows
        # e.g. fault with stacktrace
        if v and isinstance(v, six.string_types) and r'\n' in v:
            lines = v.strip().split(r'\n')
            col1 = k
            for line in lines:
                pt.add_row([col1, line])
                col1 = ''
        elif isinstance(v, list):
            val = str([str(i) for i in v])
            if val is None:
                val = '-'
            pt.add_row([k, val])
        else:
            if v is None:
                v = '-'
            pt.add_row([k, v])

    if six.PY3:
        print(encodeutils.safe_encode(pt.get_string()).decode())
    else:
        print(encodeutils.safe_encode(pt.get_string()))


def print_list(objs, fields, formatters=None, sortby_index=0,
               mixed_case_fields=None, field_labels=None):
    """Print a list or objects as a table, one row per object.

    :param objs: iterable of :class:`Resource`
    :param fields: attributes that correspond to columns, in order
    :param formatters: `dict` of callables for field formatting
    :param sortby_index: index of the field for sorting table rows
    :param mixed_case_fields: fields corresponding to object attributes that
        have mixed case names (e.g., 'serverId')
    :param field_labels: Labels to use in the heading of the table, default to
        fields.
    """
    formatters = formatters or {}
    mixed_case_fields = mixed_case_fields or []
    field_labels = field_labels or fields
    if len(field_labels) != len(fields):
        raise ValueError(_("Field labels list %(labels)s has different number "
                           "of elements than fields list %(fields)s"),
                         {'labels': field_labels, 'fields': fields})

    if sortby_index is None:
        kwargs = {}
    else:
        kwargs = {'sortby': field_labels[sortby_index]}
    pt = prettytable.PrettyTable(field_labels)
    pt.align = 'l'

    for o in objs:
        row = []
        for field in fields:
            data = '-'
            if field in formatters:
                data = formatters[field](o)
            else:
                if field in mixed_case_fields:
                    field_name = field.replace(' ', '_')
                else:
                    field_name = field.lower().replace(' ', '_')
                data = o.get(field_name, '')
            if data is None:
                data = '-'
            row.append(data)
        pt.add_row(row)

    if six.PY3:
        print(encodeutils.safe_encode(pt.get_string(**kwargs)).decode())
    else:
        print(encodeutils.safe_encode(pt.get_string(**kwargs)))
