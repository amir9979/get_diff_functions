import operator
import javalang
import os
import sys
import lizard
import shutil
import tempfile
import traceback
import pandas as pd
from collections import Counter
from functools import reduce
from subprocess import run
import networkx as nx
try:
    from .commented_code_detector import CommentFilter
    from .methodData import MethodData, SourceLine
    from .commented_code_detector import Halstead
    from .utils import get_java_exe_by_version
except:
    from methodData import MethodData, SourceLine
    from commented_code_detector import CommentFilter
    from commented_code_detector import Halstead
    from utils import get_java_exe_by_version


class SourceFile(object):
    def __init__(self, contents, file_name, indices=(), analyze_source_lines=True, delete_source=True,
                 analyze_diff=False):
        self.contents = contents
        self.changed_indices = indices
        self.file_name = file_name
        self.lizard_analysis = None
        self.methods = dict()
        self.osa_metrics = {}
        self.path_to_source, self.path_to_dir_source = None, None
        try:
            self.path_to_dir_source = tempfile.mkdtemp()
            f, self.path_to_source = tempfile.mkstemp(suffix='.java', dir=self.path_to_dir_source)
            os.close(f)
            if sys.version_info.major == 3:
                with open(self.path_to_source, 'w', encoding="utf-8") as f:
                    f.writelines(contents)
            else:
                with open(self.path_to_source, 'wb') as f:
                    f.writelines(map(lambda x: x.encode("UTF-8"), contents))
            self.lizard_analysis = lizard.analyze_file(self.path_to_source)
            self.lizard_values = {}
            for att in ['CCN', 'ND', 'average_cyclomatic_complexity', 'average_nloc', 'average_token_count', 'nloc',
                        'token_count']:
                try:
                    setattr(self, 'lizard_' + att, getattr(self.lizard_analysis, att))
                    self.lizard_values[att] = getattr(self.lizard_analysis, att)
                except:
                    setattr(self, 'lizard_' + att, None)
                    self.lizard_values[att] = 0
            if analyze_diff:
                self.osa_metrics = self.run_open_analyzer()
            if delete_source:
                self.remove_source()
            tokens = list(javalang.tokenizer.tokenize("".join(self.contents)))
            parser = javalang.parser.Parser(tokens)
            parsed_data = parser.parse()
            packages = list(map(operator.itemgetter(1), parsed_data.filter(javalang.tree.PackageDeclaration)))
            classes = list(map(operator.itemgetter(1), parsed_data.filter(javalang.tree.ClassDeclaration)))
            self.package_name = ''
            if packages:
                self.package_name = packages[0].name
            else:
                pass
            self.modified_names = list(map(lambda c: self.package_name + "." + c.name, classes))
            self.methods, self.used_lines = self.get_methods_by_javalang(tokens, parsed_data,
                                                                         analyze_source_lines=analyze_source_lines)
            self.used_changed_lines = set(self.changed_indices).intersection(self.used_lines)
            self.ast_graph = self.make_ast_graph(parsed_data, self.used_changed_lines)
            if analyze_source_lines:
                self.decls = SourceLine.get_decles_empty_dict()
                for k in self.decls:
                    self.decls[k] = sum(list(map(lambda m: self.methods[m].decls[k], self.methods)))
                self.halstead = Halstead(reduce(list.__add__, list(
                    map(lambda m: list(map(lambda s: s.halstead_line, m.source_lines)), self.methods.values())),
                                                [])).getValuesVector()
        except Exception as e:
            traceback.print_exc()
            raise

    def remove_source(self):
        if self.path_to_dir_source:
            shutil.rmtree(self.path_to_dir_source)
        else:
            os.remove(self.path_to_source)

    def get_methods_by_javalang(self, tokens, parsed_data, analyze_source_lines=True):
        def get_method_end_position(method, seperators):
            method_seperators = seperators[list(map(id, sorted(seperators + [method],
                                                               key=lambda x: (
                                                               x.position.line, x.position.column)))).index(
                id(method)):]
            assert method_seperators[0].value == "{"
            counter = 1
            for seperator in method_seperators[1:]:
                if seperator.value == "{":
                    counter += 1
                elif seperator.value == "}":
                    counter -= 1
                if counter == 0:
                    return seperator.position

        halstead_lines = CommentFilter().filterComments(self.contents)[0]
        used_lines = set(map(lambda t: t.position.line - 1, tokens))
        seperators = list(filter(lambda token: isinstance(token, javalang.tokenizer.Separator) and token.value in "{}",
                                 tokens))
        methods_dict = dict()
        for class_declaration in map(operator.itemgetter(1), parsed_data.filter(javalang.tree.ClassDeclaration)):
            class_name = class_declaration.name
            methods = list(map(operator.itemgetter(1), class_declaration.filter(javalang.tree.MethodDeclaration)))
            constructors = list(
                map(operator.itemgetter(1), class_declaration.filter(javalang.tree.ConstructorDeclaration)))
            for method in methods + constructors:
                if not method.body:
                    # skip abstract methods
                    continue
                method_start_position = method.position
                method_end_position = get_method_end_position(method, seperators)
                method_used_lines = list(
                    filter(lambda line: method_start_position.line - 1 <= line <= method_end_position.line, used_lines))
                parameters = list(
                    map(lambda parameter: parameter.type.name + ('[]' if parameter.type.children[1] else ''),
                        method.parameters))
                lizard_method = list(
                    filter(lambda f: f.start_line == method_start_position.line, self.lizard_analysis.function_list))
                if lizard_method:
                    lizard_method = lizard_method[0]
                else:
                    lizard_method = None
                method_data = MethodData(".".join([self.package_name, class_name, method.name]),
                                         method_start_position.line - 1, method_end_position.line,
                                         self.contents, halstead_lines, self.changed_indices, method_used_lines,
                                         parameters, self.file_name, method, tokens,
                                         analyze_source_lines=analyze_source_lines, lizard_method=lizard_method)
                methods_dict[method_data.id] = method_data
        return methods_dict, used_lines

    def get_changed_methods(self):
        return list(filter(lambda method: method.changed, self.methods.values()))

    def run_open_analyzer(self):
        results_dir = tempfile.mkdtemp(prefix='results_osa_')
        name_project = os.path.basename(self.path_to_dir_source)
        run([os.path.abspath(os.path.join(os.path.dirname(__file__), r'..\externals\java\OpenStaticAnalyzerJava.exe')),
             '-resultsDir=' + results_dir, '-projectName=' +
             name_project, '-projectBaseDir=' + self.path_to_dir_source, self.path_to_source])

        directory_path = os.path.join(results_dir, name_project, "java")
        directory_path = os.path.abspath(os.path.join(directory_path, os.listdir(directory_path)[0], name_project))

        STATIC = ['PDA', 'LOC', 'CLOC', 'PUA', 'McCC', 'LLOC',  # File
                  # 'TONS',  # Component
                  'LDC', 'TLLOC', 'CCL',
                  'NOS',
                  'NLE', 'CI', 'CD', 'NOI', 'NUMPAR', 'CC', 'LLDC', 'NII', 'CCO',
                  'CLC', 'TCD',
                  'NL', 'TLOC', 'CLLC', 'TCLOC', 'DLOC', 'NLM', 'DIT', 'NPA', 'TNLPM',
                  'TNLA', 'NLA', 'AD', 'TNLPA', 'NM', 'TNG', 'NLPM', 'TNM', 'NOC', 'NOD', 'NOP', 'NLS', 'NG',
                  'TNLG',
                  'CBOI',
                  'RFC', 'NLG', 'TNLS', 'TNA', 'NLPA', 'NOA', 'WMC', 'NPM', 'TNPM', 'TNS', 'NA', 'LCOM5', 'NS',
                  'CBO',
                  'TNLM',
                  'TNPA']  # 'MI','HPL','HDIF','MIMS','HPV','MISEI','MISM',
        x = pd.read_csv(directory_path + "-Class.csv", low_memory=False)
        x_sum = x.agg({i: 'sum' for i in STATIC if i in list(x.columns)})
        y = pd.read_csv(directory_path + "-Method.csv", low_memory=False)
        y_sum = y.agg({i: 'sum' for i in STATIC if i not in list(x.columns)})
        static_results = pd.concat([x_sum, y_sum], axis=0).to_dict()
        # region PMD_RULES
        PMD_RULES = ['PMD_ABSALIL', 'PMD_ADLIBDC', 'PMD_AMUO', 'PMD_ATG', 'PMD_AUHCIP', 'PMD_AUOV', 'PMD_BII', 'PMD_BI',
                     'PMD_BNC', 'PMD_CRS', 'PMD_CSR', 'PMD_CCEWTA', 'PMD_CIS', 'PMD_DCTR', 'PMD_DUFTFLI', 'PMD_DCL',
                     'PMD_ECB', 'PMD_EFB', 'PMD_EIS', 'PMD_EmSB', 'PMD_ESNIL', 'PMD_ESI', 'PMD_ESS', 'PMD_ESB',
                     'PMD_ETB', 'PMD_EWS', 'PMD_EO', 'PMD_FLSBWL', 'PMD_JI', 'PMD_MNC', 'PMD_OBEAH', 'PMD_RFFB',
                     'PMD_UIS', 'PMD_UCT', 'PMD_UNCIE', 'PMD_UOOI', 'PMD_UOM', 'PMD_FLMUB', 'PMD_IESMUB', 'PMD_ISMUB',
                     'PMD_WLMUB', 'PMD_CTCNSE', 'PMD_PCI', 'PMD_AIO', 'PMD_AAA', 'PMD_APMP', 'PMD_AUNC', 'PMD_DP',
                     'PMD_DNCGCE', 'PMD_DIS', 'PMD_ODPL', 'PMD_SOE', 'PMD_UC', 'PMD_ACWAM', 'PMD_AbCWAM', 'PMD_ATNFS',
                     'PMD_ACI', 'PMD_AICICC', 'PMD_APFIFC', 'PMD_APMIFCNE', 'PMD_ARP', 'PMD_ASAML', 'PMD_BC',
                     'PMD_CWOPCSBF', 'PMD_ClR', 'PMD_CCOM', 'PMD_DLNLISS', 'PMD_EMIACSBA', 'PMD_EN', 'PMD_FDSBASOC',
                     'PMD_FFCBS', 'PMD_IO', 'PMD_IF', 'PMD_ITGC', 'PMD_LI', 'PMD_MBIS', 'PMD_MSMINIC', 'PMD_NCLISS',
                     'PMD_NSI', 'PMD_NTSS', 'PMD_OTAC', 'PMD_PLFICIC', 'PMD_PLFIC', 'PMD_PST', 'PMD_REARTN',
                     'PMD_SDFNL', 'PMD_SBE', 'PMD_SBR', 'PMD_SC', 'PMD_SF', 'PMD_SSSHD', 'PMD_TFBFASS', 'PMD_UEC',
                     'PMD_UEM', 'PMD_ULBR', 'PMD_USDF', 'PMD_UCIE', 'PMD_ULWCC', 'PMD_UNAION', 'PMD_UV', 'PMD_ACF',
                     'PMD_EF', 'PMD_FDNCSF', 'PMD_FOCSF', 'PMD_FO', 'PMD_FSBP', 'PMD_DIJL', 'PMD_DI', 'PMD_IFSP',
                     'PMD_TMSI', 'PMD_UFQN', 'PMD_DNCSE', 'PMD_LHNC', 'PMD_LISNC', 'PMD_MDBASBNC', 'PMD_RINC',
                     'PMD_RSINC', 'PMD_SEJBFSBF', 'PMD_JUASIM', 'PMD_JUS', 'PMD_JUSS', 'PMD_JUTCTMA', 'PMD_JUTSIA',
                     'PMD_SBA', 'PMD_TCWTC', 'PMD_UBA', 'PMD_UAEIOAT', 'PMD_UANIOAT', 'PMD_UASIOAT', 'PMD_UATIOAE',
                     'PMD_GDL', 'PMD_GLS', 'PMD_PL', 'PMD_UCEL', 'PMD_APST', 'PMD_GLSJU', 'PMD_LINSF', 'PMD_MTOL',
                     'PMD_SP', 'PMD_MSVUID', 'PMD_ADS', 'PMD_AFNMMN', 'PMD_AFNMTN', 'PMD_BGMN', 'PMD_CNC', 'PMD_GN',
                     'PMD_MeNC', 'PMD_MWSNAEC', 'PMD_NP', 'PMD_PC', 'PMD_SCN', 'PMD_SMN', 'PMD_SCFN', 'PMD_SEMN',
                     'PMD_SHMN', 'PMD_VNC', 'PMD_AES', 'PMD_AAL', 'PMD_RFI', 'PMD_UWOC', 'PMD_UALIOV', 'PMD_UAAL',
                     'PMD_USBFSA', 'PMD_AISD', 'PMD_MRIA', 'PMD_ACGE', 'PMD_ACNPE', 'PMD_ACT', 'PMD_ALEI', 'PMD_ARE',
                     'PMD_ATNIOSE', 'PMD_ATNPE', 'PMD_ATRET', 'PMD_DNEJLE', 'PMD_DNTEIF', 'PMD_EAFC', 'PMD_ADL',
                     'PMD_ASBF', 'PMD_CASR', 'PMD_CLA', 'PMD_ISB', 'PMD_SBIWC', 'PMD_StI', 'PMD_STS', 'PMD_UCC',
                     'PMD_UETCS', 'PMD_ClMMIC', 'PMD_LoC', 'PMD_SiDTE', 'PMD_UnI', 'PMD_ULV', 'PMD_UPF', 'PMD_UPM',
                     'file_system_sum_WD', 'author_delta_sum_WD', 'system_WD']

        # endregion PMD_RULES

        pmd_results = dict.fromkeys(PMD_RULES, 0)
        if os.path.getsize(directory_path + "-PMD.txt") != 0:
            pmd = pd.read_csv(directory_path + "-PMD.txt", low_memory=False, delimiter=":", header=None)
            pmd_results.update(Counter(list(map(str.strip, pmd.T.loc[2].to_list()))))
        else:
            pmd_results = dict.fromkeys(PMD_RULES, -1)
        shutil.rmtree(results_dir)
        return dict(list(static_results.items()) + list(pmd_results.items()))

    def replace_method(self, method_data):
        assert method_data.method_name in self.methods
        old_method = self.methods[method_data.method_name]
        self.contents = self.contents[:old_method.start_line] + \
                        self.contents[method_data.start_line:method_data.end_line] + \
                        self.contents[old_method.end_line:]
        self.methods = self.get_methods_by_javalang()

    @staticmethod
    def get_hunks_count(indices):
        if len(indices) == 0:
            return 0
        elif len(indices) == 1:
            return 1
        hunks = 1
        s = sorted(indices)
        for i, j in zip(s, s[1:]):
            if i + 1 != j:
                hunks += 1
        return hunks

    def __repr__(self):
        return self.file_name

    def get_file_metrics(self):
        d = {'changed_lines': len(self.changed_indices), 'used_lines': len(self.used_lines),
             'changed_used_lines': len(self.used_changed_lines),
             'methods_used_lines': sum(list(map(lambda m: len(m.used_lines), self.methods.values()))),
             'methods_changed_used_lines': sum(list(map(lambda m: len(m.used_changed_lines), self.methods.values()))),
             'methods_count': len(self.methods), 'lines_hunks': self.get_hunks_count(self.changed_indices),
             'used_lines_hunks': self.get_hunks_count(self.used_changed_lines)}
        d.update(self.lizard_values)
        d.update(self.osa_metrics)
        d.update(self.decls)
        d.update(self.halstead)
        return d

    def make_ast_graph(self, tree, used_changed_lines):
        g = nx.DiGraph()
        for path, node in tree:
            attrs = {
                k: v for k, v in node.__dict__.items()
                if not isinstance(v, (javalang.ast.Node, list)) and
                   v is not None and
                   len(str(v)) > 0
            }
            attrs['changed'] = None
            if '_position' in attrs:
                attrs['changed'] = attrs['_position'].line in used_changed_lines
            attrs['type'] = node.__class__.__name__
            g.add_node(id(node), **attrs)
            if len(path) > 0:
                parents = path[-1]
                if not isinstance(path[-1], list):
                    parents = [parents]
                for p in parents:
                    g.add_edge(id(p), id(node))
        return g
