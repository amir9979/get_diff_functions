import networkx as nx
import javalang
import xmltodict
import tempfile
import os
from subprocess import run
from collections import OrderedDict
import numpy as np

class Convert():
    def __init__(self, file_name):
        self.node_count = 0
        self.file_name = file_name
        self.g = nx.DiGraph()

    def add_to_graph(self, data_dict, name, parent=None):
        node_ind = self.node_count
        self.node_count = self.node_count + 1
        attributes = self.get_attributes(data_dict, name)
        self.g.add_node(node_ind, **attributes)
        if parent is not None:
            self.g.add_edge(parent, node_ind)
        for k in data_dict.keys():
            if k.startswith('@'):
                continue
            if k == '#text':
                # self.g.add_node(self.node_count, text=data_dict[k], node_name='text')
                # self.g.add_edge(node_ind, self.node_count)
                # self.node_count = self.node_count + 1
                continue
            if type(data_dict[k]) == list:
                for item in data_dict[k]:
                    if type(item) == OrderedDict:
                        self.add_to_graph(item, k, self.node_count)
                    else:
                        self.g.add_node(self.node_count, text=k, node_name=k)
                        self.g.add_edge(node_ind, self.node_count)
                        self.node_count = self.node_count + 1
                continue
            self.add_to_graph(data_dict[k], k, node_ind)

    def get_attributes(self, data_dict, name):
        attributes = {'node_name': name}
        for k in data_dict.keys():
            if k.startswith('@'):
                attributes[k[1:]] = data_dict[k]
            if k == '#text':
                attributes['text'] = data_dict[k]
        return attributes

    def to_nx(self):
        with open(self.file_name) as f:
            data_dict = xmltodict.parse(f.read())
        self.add_to_graph(data_dict['unit'], 'unit')
        return self.g


def create_ast_by_srcml(source_file):
    f, srcml_file = tempfile.mkstemp(suffix='.srcml')
    os.close(f)
    src_bin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), r'..\externals\srcML 0.9.5\bin'))
    cmd = [os.path.join(src_bin_dir, r'srcml.exe'), '--position', '-l', 'Java', '--no-xml-declaration',
             '--no-namespace-decl', '-o', srcml_file, source_file]
    run(cmd, cwd=src_bin_dir)
    g = Convert(srcml_file).to_nx()
    os.remove(srcml_file)
    return g


def create_ast_by_javalang(source_file):
    g = nx.DiGraph()
    with open(source_file) as f:
        tokens = list(javalang.tokenizer.tokenize(f.read()))
        parser = javalang.parser.Parser(tokens)
        tree = parser.parse()
    for path, node in tree:
        attrs = {
            k: v for k, v in node.__dict__.items()
            if not isinstance(v, (javalang.ast.Node, list)) and
               v is not None and
               len(str(v)) > 0
        }
        attrs['type'] = node.__class__.__name__
        g.add_node(id(node), **attrs)
        if len(path) > 0:
            parents = path[-1]
            if not isinstance(path[-1], list):
                parents = [parents]
            for p in parents:
                g.add_edge(id(p), id(node))
    return g

if __name__ == '__main__':
    g = create_ast_by_srcml(r"C:\Temp\commons-lang\src\main\java\org\apache\commons\lang3\math\Fraction.java")
    g1 = create_ast_by_javalang(r"C:\Temp\commons-lang\src\main\java\org\apache\commons\lang3\math\Fraction.java")
    # g = Convert(r"C:\Users\User\Downloads\easy_srcml_visualization-master\easy_srcml_visualization-master\example\code2.srcml").to_nx()
    # nx.draw(g)
    A = nx.to_scipy_sparse_matrix(g1)
    X = [g1.nodes()[n]['type'] for n in g1.nodes()]
    n_values = len(set(X))
    X = np.eye(n_values)[X]

    A = A.todense()
    A[np.isnan(A)] = 0
    X[np.isnan(X)] = 0

    pass

