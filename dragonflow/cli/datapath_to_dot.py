#!/bin/python3

import argparse
import hashlib
import sys

from dragonflow.controller.common import constants as df_contants
from dragonflow.controller import datapath_layout

DF_TABLE_NAMES = {
    str(getattr(df_contants, attr)): attr
    for attr in dir(df_contants) if attr.endswith('_TABLE')
}


def fix_name_for_dot(name):
    return name.replace('-', '_')


class DatapathApp(object):
    LEGACY_APP = 'dragonflow_legacy'
    _table_attrs = 'cellborder="1" cellspacing="0"'

    def __init__(self, name, type=None):
        self.name = fix_name_for_dot(name)
        self.type = type if type else self.name
        self.entries = set()
        self.exits = set()

    def _get_ports_repr(self, ports, direction):
        ret = []
        if ports:
            ret.append(f'          <table border="0" {self._table_attrs}>')
            for port in sorted(ports):
                ret.append(f'            <tr><td port="{direction}_{port}">'
                           f'{port}</td></tr>')
            ret.append('          </table>')
        return ret

    def to_string(self):
        ret = [f'  {self.name} [',
               '    shape=plaintext',
               '    label=<',
               f'    <table {self._table_attrs}>',
               f'      <th><td colspan="2">{self.name}</td></th>',
               '      <tr><td>In</td><td>Out</td></tr>',
               '      <tr>',
               '        <td cellpadding="0">', ]
        ret.extend(self._get_ports_repr(self.entries, 'in'))
        ret.append('        </td><td cellpadding="0">')
        ret.extend(self._get_ports_repr(self.exits, 'out'))
        ret.extend(['        </td>',
                    '      </tr>',
                    '    </table>',
                    '  >];', ])
        return '\n'.join(ret)


class DatapathEdge(object):

    def __init__(self, exit_app, exit_id, entry_app, entry_id, virtual=False):
        self.exit_app = fix_name_for_dot(exit_app)
        self.exit_id = exit_id
        self.entry_app = fix_name_for_dot(entry_app)
        self.entry_id = entry_id
        m = hashlib.md5()
        m.update(exit_app.encode())
        m.update(exit_id.encode())
        d = m.hexdigest()
        self.color = f'#{d[:6]}'
        self.virtual = virtual

    def to_string(self):
        virtual = 'style=dashed, ' if self.virtual else ''
        return (f'  {self.exit_app}:out_{self.exit_id}:e'
                f' -> {self.entry_app}:in_{self.entry_id}:w'
                f' [{virtual}color="{self.color}"]')


def add_legacy_app(table_id, apps):
    name = DF_TABLE_NAMES[table_id]
    app = DatapathApp(name)
    app.entries.add(table_id)
    app.exits.add(table_id)
    apps[name] = app


def add_virtual_edges(legacy_app, entry_id, edges):
    for exit_id in legacy_app.exits:
        if int(exit_id) > int(entry_id):
            edge = DatapathEdge(DF_TABLE_NAMES[entry_id], entry_id,
                                DF_TABLE_NAMES[exit_id], exit_id, True)
            edges.add(edge)


def expand_legacy(legacy_app, add_virt, apps, edges):
    # Fix the edges
    new_apps = {}
    new_edges = set()
    for entry_id in legacy_app.entries:
        add_legacy_app(entry_id, new_apps)
        if add_virt:
            add_virtual_edges(legacy_app, entry_id, new_edges)
    for exit_id in legacy_app.exits:
        add_legacy_app(exit_id, new_apps)

    for edge in edges:
        if edge.entry_app == DatapathApp.LEGACY_APP:
            edge.entry_app = DF_TABLE_NAMES[edge.entry_id]
        if edge.exit_app == DatapathApp.LEGACY_APP:
            edge.exit_app = DF_TABLE_NAMES[edge.exit_id]

    edges.extend(new_edges)
    apps.update(new_apps)


def get_cli_args():
    default_dp_path = '/etc/dragonflow/dragonflow_datapath_layout.yaml'
    parser = argparse.ArgumentParser(
        description='Print Dragonflow datapath layout to dot syntax')
    parser.add_argument('-i', '--infile', help='Input file to parse. '
                        f'(default: {default_dp_path})',
                        default=default_dp_path)
    parser.add_argument('-o', '--outfile',
                        help='Output to file (instead of stdout)')
    parser.add_argument('-n', '--no_virt',
                        help='Do not print virtual edges',
                        action='store_true')
    parser.epilog = '''Note: After successfully creating the odt file, it may
        be converted to jpg/svg/etc. using the 'dot' command line tool.
        Use 'dot -Tsvg -O <input-file.dot>' or refer to the dot man page
        from the Graphviz package.'''
    return parser.parse_args()


def get_outfile(file_path):
    if file_path:
        return open(file_path, 'w')
    else:
        return sys.stdout


def parse_layout(layout, apps, edges):
    for vertex in layout.vertices:
        app = DatapathApp(vertex.name, vertex.type)
        apps[app.name] = app

    for edge in layout.edges:
        item = DatapathEdge(edge.exitpoint.vertex, edge.exitpoint.name,
                            edge.entrypoint.vertex, edge.entrypoint.name)
        assert (edge.exitpoint.direction == 'out')
        apps[item.exit_app].exits.add(edge.exitpoint.name)

        assert (edge.entrypoint.direction == 'in')
        apps[item.entry_app].entries.add(edge.entrypoint.name)

        edges.append(item)


def print_dot_file(apps, edges, outfile):
    print('digraph datapath_layout {', file=outfile)
    for app in apps.values():
        print(app.to_string(), file=outfile)
    for edge in edges:
        print(edge.to_string(), file=outfile)
    print('}', file=outfile)


def main():
    args = get_cli_args()
    outfile = get_outfile(args.outfile)
    layout = datapath_layout.get_datapath_layout(args.infile)
    apps = {DatapathApp.LEGACY_APP: DatapathApp(DatapathApp.LEGACY_APP)}
    edges = list()

    parse_layout(layout, apps, edges)
    legacy = apps.pop(DatapathApp.LEGACY_APP)
    expand_legacy(legacy, not args.no_virt, apps, edges)

    print_dot_file(apps, edges, outfile)


if __name__ == '__main__':
    main()
