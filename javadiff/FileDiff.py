import difflib
import gc
import os
try:
    from .SourceFile import SourceFile
except:
    from SourceFile import SourceFile


class FileDiff(object):
    REMOVED = '- '
    ADDED = '+ '
    UNCHANGED = '  '
    NOT_IN_INPUT = '? '
    BEFORE_PREFIXES = [REMOVED, UNCHANGED]
    AFTER_PREFIXES = [ADDED, UNCHANGED]

    def __init__(self, diff, commit_sha, first_commit=None, second_commit=None, git_dir=None, analyze_source_lines=True):
        self.file_name = diff.b_path
        self.commit_sha = commit_sha
        self.is_ok = self.file_name.endswith(".java")
        if not self.is_ok:
            return
        before_contents = self.get_before_content_from_diff(diff, first_commit)
        after_contents = self.get_after_content_from_diff(diff, git_dir, second_commit)
        before_contents = list(map(lambda x: x.decode("utf-8", errors='ignore'), before_contents))
        after_contents = list(map(lambda x: x.decode("utf-8", errors='ignore'), after_contents))
        before_indices, after_indices = self.get_changed_indices(before_contents, after_contents)
        self.before_file = SourceFile(before_contents, diff.a_path, before_indices, analyze_source_lines=analyze_source_lines)
        self.after_file = SourceFile(after_contents, diff.b_path, after_indices, analyze_source_lines=analyze_source_lines)
        self.modified_names = self.after_file.modified_names

    def get_after_content_from_diff(self, diff, git_dir, second_commit):
        after_contents = ['']
        if diff.deleted_file:
            assert diff.b_blob is None
        else:
            try:
                after_contents = diff.b_blob.data_stream.stream.readlines()
            except:
                if second_commit:
                    try:
                        after_contents = second_commit.repo.git.show(
                            "{0}:{1}".format(second_commit.hexsha, diff.b_path)).split('\n')
                    except:
                        gc.collect()
                elif git_dir:
                    path = os.path.join(git_dir, diff.b_path)
                    with open(path) as f:
                        after_contents = f.readlines()
                gc.collect()
        return after_contents

    def get_before_content_from_diff(self, diff, first_commit):
        before_contents = ['']
        if diff.new_file:
            assert diff.a_blob is None
        else:
            try:
                before_contents = diff.a_blob.data_stream.stream.readlines()
            except:
                gc.collect()
                if first_commit:
                    try:
                        before_contents = first_commit.repo.git.show(
                            "{0}:{1}".format(first_commit.hexsha, diff.a_path)).split('\n')
                    except:
                        gc.collect()
        return before_contents

    def is_java_file(self):
        return self.is_ok


    @staticmethod
    def get_changed_indices(before_contents, after_contents):
        def get_lines_by_prefixes(lines, prefixes):
            return list(filter(lambda x: any(map(lambda p: x.startswith(p), prefixes)), lines))

        def get_indices_by_prefix(lines, prefix):
            return list(map(lambda x: x[0], filter(lambda x: x[1].startswith(prefix), enumerate(lines))))

        diff = list(difflib.ndiff(before_contents, after_contents))

        diff_before_lines = get_lines_by_prefixes(diff, FileDiff.BEFORE_PREFIXES)
        assert list(map(lambda x: x[2:], diff_before_lines)) == before_contents
        before_indices = get_indices_by_prefix(diff_before_lines, FileDiff.REMOVED)

        diff_after_lines = get_lines_by_prefixes(diff, FileDiff.AFTER_PREFIXES)
        assert list(map(lambda x: x[2:], diff_after_lines)) == after_contents
        after_indices = get_indices_by_prefix(diff_after_lines, FileDiff.ADDED)

        return before_indices, after_indices

    def get_changed_methods(self):
        return self.after_file.get_changed_methods() + self.before_file.get_changed_methods()

    def get_methods(self):
        return list(self.before_file.methods.values()) + list(self.after_file.methods.values())

    def get_methods_dict(self):
        before = list(self.before_file.methods.values())
        after = list(self.after_file.methods.values())
        before_changed = list(filter(lambda x: x.changed, before))
        before_unchanged = list(filter(lambda x: not x.changed, before))
        after_changed = list(filter(lambda x: x.changed, after))
        after_unchanged = list(filter(lambda x: not x.changed, after))
        return {'before_changed': before_changed, 'before_unchanged': before_unchanged,
                'after_changed': after_changed, 'after_unchanged': after_unchanged}

    def get_changed_exists_methods(self):
        return list(filter(lambda m: m.id in self.before_file.methods, self.after_file.get_changed_methods())) + \
               list(filter(lambda m: m.id in self.after_file.methods, self.before_file.get_changed_methods()))

    def __repr__(self):
        return self.file_name


class FormatPatchFileDiff(FileDiff):
    def get_after_content_from_diff(self, diff, git_dir, second_commit):
        return diff.after_contents

    def get_before_content_from_diff(self, diff, first_commit):
        return diff.before_contents
