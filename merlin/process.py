import subprocess
import json

import sublime

from .helpers import merlin_bin


class MerlinExc(Exception):
    """ Exception returned by merlin. """

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Failure(MerlinExc):
    """ Failure exception. """
    pass


class Error(MerlinExc):
    """ Error exception. """
    pass


class MerlinException(MerlinExc):
    """ Standard exception. """
    pass


class MerlinProcess(object):
    """
    This class launches a merlin process and send/receive commands to
    synchronise buffer, autocomplete...
    """

    def __init__(self):
        self.mainpipe = None
        self.name = None

    def restart(self):
        """ Start a fresh merlin process. """
        if self.mainpipe:
            try:
                try:
                    self.mainpipe.terminate()
                except OSError:
                    pass
                self.mainpipe.communicate()
            except OSError:
                pass
        try:
            user_settings = sublime.load_settings("Merlin.sublime-settings")
            flags = user_settings.get('flags')
            command = [merlin_bin()]
            command.extend(flags)
            self.mainpipe = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
            )
        except (OSError, FileNotFoundError) as e:
            print("Failed starting ocamlmerlin. Please ensure that ocamlmerlin"
                  "binary is executable.")
            raise e

    def send_command(self, cmd):
        """
        Send a command to merlin and wait to return the results.
        Raise an exception if merlin returned an error message.
        """

        if self.mainpipe is None or self.mainpipe.returncode is not None:
            self.restart()

        self.mainpipe.stdin.write(json.dumps(cmd).encode('utf-8'))
        self.mainpipe.stdin.flush()
        line = self.mainpipe.stdout.readline()
        result = json.loads(line.decode('utf-8'))
        content = None
        if len(result) == 2:
            content = result[1]

        if result[0] == "return":
            return content
        elif result[0] == "failure":
            raise Failure(content)
        elif result[0] == "error":
            raise Error(content)
        elif result[0] == "exception":
            raise MerlinException(content)

class MerlinView(object):
    """
    This class wraps commands local to a view/buffer
    """

    def __init__(self, process, view):
        self.process = process
        self.view = view

    def send_query(self, *query):
        document = ["auto",self.view.file_name()]
        command = {'assoc': None, 'document': document, 'query': query}
        return self.process.send_command(command)

    def complete_cursor(self, base, line, col):
        """ Return possible completions at the current cursor position. """
        pos = {'line': line, 'col': col}
        result = self.send_query("complete", "prefix", base, "at", pos)
        if not isinstance(result, dict):
            result = {'entries':result, 'context':None}
        return result

    def report_errors(self):
        """
        Return all errors detected by merlin while parsing the current file.
        """
        return self.send_query("errors")

    def find_list(self):
        """ List all possible external modules to load. """
        return self.send_query('find', 'list')

    def find_use(self, *packages):
        """ Find and load external modules. """
        return self.send_query('find', 'use', packages)

    def project(self):
        """
        Returns a tuple
          (dot_merlins, failures)
        where dot_merlins is a list of loaded .merlin files
          and failures is the list of errors which occured during loading
        """
        result = self.send_query("project", "get")
        return (result['result'], result['failures'])

    def sync(self):
        """ Synchronize the buffer up to specified position.  """

        text = self.view.substr(sublime.Region(0, self.view.size()))
        return self.send_query("tell", "start", "end", text)

    # Path management
    def add_build_path(self, path):
        return self.send_query("path", "add", "build", path)

    def add_source_path(self, path):
        return self.send_query("path", "add", "source", path)

    def remove_build_path(self, path):
        return self.send_query("path", "remove", "build", path)

    def remove_source_path(self, path):
        return self.send_query("path", "remove", "source", path)

    def list_build_path(self):
        return self.send_query("path", "list", "build")

    def list_source_path(self):
        return self.send_query("path", "list", "source")

    # File selection
    def which_path(self, names):
        return self.send_query("which", "path", names)

    def which_with_ext(self, extensions):
        return self.send_query("which", "with_ext", extensions)

    # Type information
    def type_enclosing(self, line, col):
        pos = {'line': line, 'col': col}
        return self.send_query("type", "enclosing", "at", pos)

    # Extensions management
    def extension_list(self, crit=None):
        if crit in ['enabled', 'disabled']:
            return self.send_query("extension", "list", crit)
        else:
            return self.send_query("extension", "list")

    def extension_enable(self, exts):
        self.send_query("extension", "enable", exts)

    def extension_disable(self, exts):
        self.send_query("extension", "disable", exts)

    def locate(self, line, col, ident="", kind="mli"):
        if line is None or col is None:
            return self.send_query("locate", ident, kind)
        else:
            return self.send_query("locate", ident, kind, "at", {
                'line': line,
                'col': col
            })
