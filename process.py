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
        except OSError as e:
            print("Failed starting ocamlmerlin. Please ensure that ocamlmerlin \
                   binary is executable.")
            raise e

    def send_command(self, *cmd):
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

    def reload(self):
        """ Detect and reload .cmi files that may have changed. """
        return self.send_command("refresh")

    def acquire(self, name):
        """
        Make sure that the process is working on buffer with the specified name.
        """
        if self.name != name:
            self.name = name
            self.reset(name=name)
        return self

    def reset(self, kind="ml", name=None):
        """
        Clear buffer content on merlin side, initialize parser for file of kind
        'ml' or 'mli'.
        """
        if name:
            r = self.send_command("reset", kind, name)
        else:
            r = self.send_command("reset", kind)
        if name == "myocamlbuild.ml":
            self.find_use("ocamlbuild")
        return r

    def _parse_cursor(self,result):
        """ Parser cursor values returned by merlin. """
        position = result['cursor']
        marker = result['marker']
        return (position['line'], position['col'], marker)

    def send_cursor_command(self, *cmd):
        """ Generic method for commands returning cursor position. """
        return self._parse_cursor(self.send_command(*cmd))

    def tell_start(self):
        """ Prepare merlin to receive new input. """
        return self.send_cursor_command("tell", "start")

    def tell_marker(self):
        """ Put marker at current point. """
        return self.send_cursor_command("tell", "marker")

    def tell_source(self, content):
        """ Send content for the current buffer. """
        if content is None:
            return self.send_cursor_command("tell", "eof")
        elif type(content) is list:
            return self.send_cursor_command("tell", "source", "\n".join(content) + "\n")
        else:
            return self.send_cursor_command("tell", "source", content)

    def seek_start(self):
        """ Reset cursor to the beginning of the file. """
        return self.send_cursor_command("seek","before",{'line': 1, 'col': 0})

    def seek_marker(self):
        """
        After satisfaying a tell marker, place the cursor immediately after the
        marker.
        """
        return self.send_cursor_command("seek","marker")

    def complete_cursor(self, base, line, col):
        """ Return possible completions at the current cursor position. """
        pos = {'line': line, 'col': col}
        return self.send_command("complete", "prefix", base, "at", pos)

    def report_errors(self):
        """
        Return all errors detected by merlin while parsing the current file.
        """
        return self.send_command("errors")

    def find_list(self):
        """ List all possible external modules to load. """
        return self.send_command('find', 'list')

    def find_use(self, *packages):
        """ Find and load external modules. """
        return self.send_command('find', 'use', packages)

    def project():
        """
        Returns a tuple
          (dot_merlins, failures)
        where dot_merlins is a list of loaded .merlin files
          and failures is the list of errors which occured during loading
        """
        result = self.send_command("project", "get")
        return (result['result'], result['failures'])

    def sync_buffer_to(self, view, cursor):
        """ Synchronize the buffer up to specified position.  """

        end = view.size()
        content = sublime.Region(0, cursor)

        self.seek_start()
        self.tell_start()
        self.tell_source(view.substr(content))

        _, _, marker = self.tell_marker()
        while marker and cursor < end:
            next_cursor = min(cursor + 1024, end)
            content = sublime.Region(cursor, next_cursor)
            _, _, marker = self.tell_source(view.substr(content))
            cursor = next_cursor
        if marker:
            self.tell_source(None)
        else:
            self.seek_marker()

    def sync_buffer_to_cursor(self, view):
        """ Synchronize the buffer up to user cursor.  """
        return self.sync_buffer_to(view, view.sel()[-1].end())

    def sync_buffer(self, view):
        """ Synchronize the whole buffer.  """
        self.sync_buffer_to(view, view.size())

    # Path management
    def add_build_path(self, path):
        return self.send_command("path", "add", "build", path)
    def add_source_path(self, path):
        return self.send_command("path", "add", "source", path)
    def remove_build_path(self, path):
        return self.send_command("path", "remove", "build", path)
    def remove_source_path(self, path):
        return self.send_command("path", "remove", "source", path)
    def list_build_path(self):
        return self.send_command("path", "list", "build")
    def list_source_path(self):
        return self.send_command("path", "list", "source")

    # File selection
    def which_path(self, names):
        return self.send_command("which", "path", names)
    def which_with_ext(self, extensions):
        return self.send_command("which", "with_ext", extensions)

    # Type information
    def type_enclosing(self, line, col):
        pos = {'line': line, 'col': col}
        return self.send_command("type", "enclosing", "at", pos)

    # Extensions management
    def extension_list(self, crit=None):
        if crit: # "enabled" | "disabled"
            return self.send_command("extension","list",crit)
        else:
            return self.send_command("extension","list")

    def extension_enable(self, exts):
        self.send_command("extension","enable",exts)

    def extension_disable(self, exts):
        self.send_command("extension","disable",exts)

    def locate(self, line, col, ident=""):
        if line is None or col is None:
            return self.send_command("locate", ident)
        else:
            return self.send_command("locate", ident, "at", {'line': line, 'col': col})
