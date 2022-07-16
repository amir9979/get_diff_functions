try:
    import StringIO
except:
    from io import StringIO
import gc
import json
import sys

import git
import jira

try:
    from .CommitsDiff import CommitsDiff
    from .FileDiff import FileDiff
except:
    from CommitsDiff import CommitsDiff
    from FileDiff import FileDiff

from functools import reduce


def get_commit_diff(git_path, child, parent=None, analyze_source_lines=True, analyze_diff=False):
    repo = git.Repo(git_path)
    if isinstance(child, str):
        child = repo.commit(child)
    if not parent:
        if child.parents:
            parent = child.parents[0]
    if not parent:
        return None
    return CommitsDiff(child, parent, analyze_source_lines=analyze_source_lines, analyze_diff=analyze_diff)


def get_commit_methods(git_path, child, parent=None, analyze_source_lines=True, analyze_diff=False):
    repo = git.Repo(git_path)
    if isinstance(child, str):
        child = repo.commit(child)
    if not parent:
        parent = child.parents[0]
    file_diffs =  CommitsDiff(child, parent, analyze_source_lines=analyze_source_lines, analyze_diff=analyze_diff).diffs
    methods = []
    for file_diff in file_diffs:
        gc.collect()
        if file_diff.is_java_file():
            methods.extend(file_diff.get_methods())
    return methods


def get_changed_exists_methods(git_path, child, parent=None, analyze_source_lines=True, analyze_diff=False):
    repo = git.Repo(git_path)
    if isinstance(child, str):
        child = repo.commit(child)
    if not parent:
        parent = child.parents[0]
    return get_changed_exists_methods_from_file_diffs(CommitsDiff(child, parent, analyze_source_lines=analyze_source_lines, analyze_diff=analyze_diff).diffs)


def get_modified_functions(git_path):
    repo = git.Repo(git_path)
    diffs = repo.head.commit.tree.diff(None, None, True, ignore_blank_lines=True, ignore_space_at_eol=True)
    return get_changed_methods_from_file_diffs(map(lambda d: FileDiff(d, repo.head.commit.hexsha, git_dir=git_path), diffs))


def get_modified_exists_functions(git_path):
    repo = git.Repo(git_path)
    diffs = repo.head.commit.tree.diff(None, None, True, ignore_blank_lines=True, ignore_space_at_eol=True)
    return get_changed_exists_methods_from_file_diffs(map(lambda d: FileDiff(d, repo.head.commit.hexsha, git_dir=git_path), diffs))


def get_changed_methods_from_file_diffs(file_diffs):
    methods = []
    for file_diff in file_diffs:
        gc.collect()
        if file_diff.is_java_file():
            methods.extend(file_diff.get_changed_methods())
    return methods


def get_changed_exists_methods_from_file_diffs(file_diffs):
    methods = []
    for file_diff in file_diffs:
        gc.collect()
        if file_diff.is_java_file():
            methods.extend(file_diff.get_changed_exists_methods())
    return methods


def get_java_commits(git_path):
    repo = git.Repo(git_path)
    data = repo.git.log('--pretty=format:"sha: %H"', '--name-only').split("sha: ")
    comms = dict(map(lambda d: (d[0], filter(lambda x: x.endswith(".java"), d[1:-1])),
                     map(lambda d: d.replace('"', '').replace('\n\n', '\n').split('\n'), data)))
    return dict(map(lambda x: (repo.commit(x), comms[x]), filter(lambda x: comms[x], comms)))


def get_methods_descriptions(git_path, json_out_file):
    repo = git.Repo(git_path)
    repo_files = filter(lambda x: x.endswith(".java") and not x.lower().endswith("test.java"),
                        repo.git.ls_files().split())
    commits = []
    for commit, files in get_java_commits(git_path).items():
        if any(filter(lambda f: f in files, repo_files)):
            commits.append(commit)
    methods_descriptions = {}
    print("# commits to check: {0}".format(len(commits)))
    for i in range(len(commits[:30]) - 1):
        print("inspect commit {0} of {1}".format(i, len(commits)))
        methods = get_changed_methods(git_path, commits[i], analyze_source_lines=False)
        if methods:
            map(lambda method: methods_descriptions.setdefault(method, StringIO.StringIO()).write(
                commits[i].message), methods)
    with open(json_out_file, "wb") as f:
        data = dict(map(lambda x: (x[0].method_name_parameters, x[1].getvalue()), methods_descriptions.items()))
        json.dump(data, f)


def get_methods_per_commit(git_path, json_out_file):
    repo = git.Repo(git_path)
    commits = list(repo.iter_commits())
    methods_per_commit = {}
    for i in range(len(commits) - 1):
        try:
            methods = get_changed_methods(git_path, commits[i + 1], analyze_source_lines=False)
        except:
            continue
        if methods:
            methods_per_commit[commits[i].hexsha] = map(repr, methods)
    with open(json_out_file, "wb") as f:
        json.dump(methods_per_commit, f)


def get_jira_issues(project_name, url, bunch=100):
    jira_conn = jira.JIRA(url)
    all_issues = []
    extracted_issues = 0
    while True:
        issues = jira_conn.search_issues("project={0}".format(project_name), maxResults=bunch, startAt=extracted_issues)
        all_issues.extend(filter(lambda issue: issue.fields.description, issues))
        extracted_issues = extracted_issues + bunch
        if len(issues) < bunch:
            break
    return dict(map(lambda issue: (issue.key.strip().split("-")[1].lower(), (
    issue.fields.issuetype.name.lower(), issue.fields.description.encode('utf-8').lower())), all_issues))


def clean_commit_message(commit_message):
    if "git-svn-id" in commit_message:
        return commit_message.split("git-svn-id")[0]
    return commit_message




class Commit(object):
    def __init__(self, bug_id, git_commit):
        self._commit_id = git_commit.hexsha
        self._bug_id = bug_id
        # self._files = Commit.fix_renamed_files(git_commit.stats.files.keys())
        # self._commit_date = time.mktime(git_commit.committed_datetime.timetuple())

    def is_bug(self):
        return self._bug_id != '0'

    @classmethod
    def init_commit_by_git_commit(cls, git_commit, bug_id):
        return Commit(bug_id, git_commit)

    def to_list(self):
        return {self._commit_id: str(self._bug_id)}

    @staticmethod
    def fix_renamed_files(files):
        """
        fix the paths of renamed files.
        before : u'tika-core/src/test/resources/{org/apache/tika/fork => test-documents}/embedded_with_npe.xml'
        after:
        u'tika-core/src/test/resources/org/apache/tika/fork/embedded_with_npe.xml'
        u'tika-core/src/test/resources/test-documents/embedded_with_npe.xml'
        :param files: self._files
        :return: list of modified files in commit
        """
        new_files = []
        for file in files:
            if "=>" in file:
                if "{" and "}" in file:
                    # file moved
                    src, dst = file.split("{")[1].split("}")[0].split("=>")
                    fix = lambda repl: re.sub(r"{[\.a-zA-Z_/\-0-9]* => [\.a-zA-Z_/\-0-9]*}", repl.strip(), file)
                    new_files.extend(map(fix, [src, dst]))
                else:
                    # full path changed
                    new_files.extend(map(lambda x: x.strip(), file.split("=>")))
                    pass
            else:
                new_files.append(file)
        return new_files




def commits_and_issues(git_path, issues):
    def replace(chars_to_replace, replacement, s):
        temp_s = s
        for c in chars_to_replace:
            temp_s = temp_s.replace(c, replacement)
        return temp_s

    def get_bug_num_from_comit_text(commit_text, issues_ids):
        text = replace("[]?#,:(){}", "", commit_text.lower())
        text = replace("-_", " ", text)
        for word in text.split():
            if word.isdigit():
                if word in issues_ids:
                    return word
        return "0"

    commits = []
    issues_ids = map(lambda issue: issue, issues)
    for git_commit in git.Repo(git_path).iter_commits():
        commits.append(
            Commit.init_commit_by_git_commit(git_commit, get_bug_num_from_comit_text(clean_commit_message(git_commit.summary), issues_ids)).to_list())
    return commits


def get_bugs_data(gitPath, jira_project_name, jira_url, json_out, number_of_bugs=100):
    issues = get_jira_issues(jira_project_name, jira_url)
    issues = dict(map(lambda issue: (issue, issues[issue][1]), filter(lambda issue: issues[issue][0] == 'bug', issues)))
    with open(json_out, "wb") as f:
        json.dump(commits_and_issues(gitPath, issues), f)


if __name__ == "__main__":
    bugs = list(set(map(lambda x: x.method_name_parameters.replace(',', ';'),
                        get_modified_exists_functions(r"C:\Temp\commons-collections"))))
    pass
